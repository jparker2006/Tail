"""On-chain role-join (Phase 1, Step 1.3).

The public Data API exposes no maker/taker role, so we recover it from Polygon. Each taker
fill is its own transaction; we fetch the receipt, decode the CTF Exchange's OrderFilled /
OrdersMatched logs, and extract:
  - the aggressor   = OrdersMatched.takerOrderMaker   (the OrderFilled.taker field is usually
                      the Exchange contract, so we DON'T use it)
  - the resting LPs = OrderFilled.maker (one per maker leg)
  - asset id + execution price (collateral/shares), as an on-chain cross-check of the tape.

Free public RPCs, rotated, with retry/backoff. Decoded results are cached to a JSONL so the
join is resumable and re-runs are instant.
"""
from __future__ import annotations

import json
import itertools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from eth_abi import decode as abi_decode
from eth_utils import keccak

RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))

# Polymarket V1 settlement contracts on Polygon (pre-April-2026; our 2024 market is here).
CTF_EXCHANGE_V1 = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"      # binary (negRisk=False)
NEGRISK_EXCHANGE_V1 = "0xc5d563a36ae78145c45a50134d48a1215220f80a"  # negRisk markets

# Free endpoints that actually retain historical receipts (ARCHIVE). Probed 2026-06: most
# public nodes are pruned and return null for July-2024 receipts; these two return them.
POLYGON_RPCS = [
    "https://polygon.drpc.org",
    "https://polygon.gateway.tenderly.co",
]

ORDERFILLED_SIG = "0x" + keccak(
    text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
).hex()
ORDERSMATCHED_SIG = "0x" + keccak(
    text="OrdersMatched(bytes32,address,uint256,uint256,uint256,uint256)"
).hex()

_rpc_cycle = itertools.cycle(POLYGON_RPCS)
_rpc_lock = threading.Lock()


def _next_rpc() -> str:
    with _rpc_lock:
        return next(_rpc_cycle)


def rpc_call(method: str, params: list, max_tries: int = 10, retry_on_null: bool = False):
    """Call a rotating RPC. If retry_on_null, a null result (pruned node) is retried on the
    next endpoint rather than accepted — needed for historical eth_getTransactionReceipt."""
    last = None
    for i in range(max_tries):
        url = _next_rpc()
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                         "params": params}, timeout=30)
            if r.status_code in (429, 401, 403, 520, 521):
                last = f"HTTP {r.status_code}"
                time.sleep(0.5 + 0.3 * i)
                continue
            r.raise_for_status()
            j = r.json()
            if "error" in j:
                last = j["error"]
                time.sleep(0.4)
                continue
            result = j["result"]
            if result is None and retry_on_null:
                last = "null result (pruned node)"
                time.sleep(0.2)
                continue
            return result
        except requests.RequestException as e:
            last = e
            time.sleep(0.4 + 0.3 * i)
    raise RuntimeError(f"rpc {method} failed after {max_tries} tries: {last}")


def _addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def decode_receipt(receipt: dict | None, token_ids, exchange: str) -> dict:
    """Pull aggressor / makers / asset / price for OUR market's fill out of a tx receipt."""
    out = {"ok": False, "taker": None, "makers": [], "asset_id": None, "price": None,
           "is_buy": None, "n_orderfilled": 0, "has_ordersmatched": False}
    if not receipt:
        return out
    token_ids = {str(t) for t in token_ids}
    for log in receipt.get("logs", []):
        try:
            if log["address"].lower() != exchange:
                continue
            t0 = log["topics"][0].lower()
            data = bytes.fromhex(log["data"][2:]) if len(log.get("data", "0x")) > 2 else b""
            if t0 == ORDERFILLED_SIG:
                m_asset, t_asset, m_amt, t_amt, _fee = abi_decode(
                    ["uint256"] * 5, data)
                tok = (str(m_asset) if str(m_asset) in token_ids
                       else str(t_asset) if str(t_asset) in token_ids else None)
                if tok is None:
                    continue
                out["n_orderfilled"] += 1
                out["makers"].append(_addr(log["topics"][2]))
                out["asset_id"] = tok
                if m_asset == 0:
                    out["is_buy"] = True
                    out["price"] = (m_amt / t_amt) if t_amt else None
                elif t_asset == 0:
                    out["is_buy"] = False
                    out["price"] = (t_amt / m_amt) if m_amt else None
            elif t0 == ORDERSMATCHED_SIG:
                m_asset, t_asset, _m_amt, _t_amt = abi_decode(["uint256"] * 4, data)
                tok = (str(m_asset) if str(m_asset) in token_ids
                       else str(t_asset) if str(t_asset) in token_ids else None)
                if tok is None:
                    continue
                out["has_ordersmatched"] = True
                out["taker"] = _addr(log["topics"][2])
        except (KeyError, IndexError, ValueError):
            continue
    out["ok"] = out["asset_id"] is not None
    return out


def build_join(tape: list[dict], token_ids, exchange: str, slug: str,
               max_workers: int = 4) -> dict:
    """Fetch+decode receipts for every tx in `tape`, cached to a resumable JSONL.

    Returns {tx_hash: decoded}.
    """
    cache_path = os.path.join(RAW_DIR, f"{slug}_onchain.jsonl")
    cached: dict = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if d.get("ok"):  # only trust successful decodes; retry the rest
                        cached[d["tx"]] = d
    txs = list(dict.fromkeys(r["transactionHash"] for r in tape))  # unique, in order
    todo = [t for t in txs if t not in cached]
    if todo:
        os.makedirs(RAW_DIR, exist_ok=True)

        def work(tx: str) -> dict:
            rec = rpc_call("eth_getTransactionReceipt", [tx], retry_on_null=True)
            d = decode_receipt(rec, token_ids, exchange)
            d["tx"] = tx
            return d

        done = 0
        with open(cache_path, "a") as f, ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(work, tx): tx for tx in todo}
            for fut in as_completed(futs):
                try:
                    d = fut.result()
                except Exception as e:  # noqa: BLE001 — record failure, keep going
                    d = {"tx": futs[fut], "ok": False, "error": str(e)}
                cached[d["tx"]] = d
                f.write(json.dumps(d) + "\n")
                f.flush()
                done += 1
                if done % 250 == 0:
                    print(f"  ... {done}/{len(todo)} receipts")
    return cached
