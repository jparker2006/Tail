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
    """Decode OUR market's fill from a tx receipt.

    matchOrders emits one OrderFilled per *order* — including the taker's own order — plus an
    OrdersMatched naming the real aggressor (takerOrderMaker). We split the taker self-leg
    (price / direction / taker shares) from the genuine resting-maker legs (each LP's share
    amount), so the MM filter can weigh wallets by volume-as-aggressor vs volume-as-LP.
    """
    out = {"ok": False, "taker": None, "asset_id": None, "price": None, "is_buy": None,
           "taker_shares": None, "maker_legs": [], "n_makers": 0, "has_ordersmatched": False}
    if not receipt:
        return out
    token_ids = {str(t) for t in token_ids}
    legs: list[tuple] = []  # (maker_addr, m_asset, t_asset, m_amt, t_amt)
    taker = None
    asset_id = None
    for log in receipt.get("logs", []):
        try:
            if log["address"].lower() != exchange:
                continue
            t0 = log["topics"][0].lower()
            raw = log.get("data", "0x")
            data = bytes.fromhex(raw[2:]) if len(raw) > 2 else b""
            if t0 == ORDERFILLED_SIG:
                m_asset, t_asset, m_amt, t_amt, _fee = abi_decode(["uint256"] * 5, data)
                if str(m_asset) in token_ids:
                    asset_id = str(m_asset)
                elif str(t_asset) in token_ids:
                    asset_id = str(t_asset)
                else:
                    continue
                legs.append((_addr(log["topics"][2]), m_asset, t_asset, m_amt, t_amt))
            elif t0 == ORDERSMATCHED_SIG:
                m_asset, t_asset, _m, _t = abi_decode(["uint256"] * 4, data)
                if str(m_asset) in token_ids or str(t_asset) in token_ids:
                    taker = _addr(log["topics"][2])
                    out["has_ordersmatched"] = True
        except (KeyError, IndexError, ValueError):
            continue
    if asset_id is None:
        return out
    out["asset_id"] = asset_id
    out["taker"] = taker
    tok = int(asset_id)
    # Taker self-leg: price, direction, taker shares.
    for (addr, m_asset, t_asset, m_amt, t_amt) in legs:
        if taker and addr == taker:
            if m_asset == 0:            # taker paid collateral -> BUY the token
                out["is_buy"] = True
                out["price"] = (m_amt / t_amt) if t_amt else None
                out["taker_shares"] = t_amt / 1e6
            elif t_asset == 0:          # taker received collateral -> SELL the token
                out["is_buy"] = False
                out["price"] = (t_amt / m_amt) if m_amt else None
                out["taker_shares"] = m_amt / 1e6
            break
    # Genuine resting-maker legs (exclude the taker self-leg): each LP's token shares.
    for (addr, m_asset, t_asset, m_amt, t_amt) in legs:
        if taker and addr == taker:
            continue
        shares = (m_amt if m_asset == tok else t_amt) / 1e6
        out["maker_legs"].append([addr, shares])
    out["n_makers"] = len(out["maker_legs"])
    out["ok"] = True
    return out


def fetch_receipts(tape: list[dict], slug: str, max_workers: int = 4) -> dict:
    """Fetch raw Polygon receipts for every tx in `tape`, cached to a resumable JSONL.

    Caching the RAW receipts (not just a decode) lets later steps re-decode for free.
    Returns {tx_hash: receipt}.
    """
    cache_path = os.path.join(RAW_DIR, f"{slug}_receipts.jsonl")
    receipts: dict = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if d.get("receipt"):
                        receipts[d["tx"]] = d["receipt"]
    txs = list(dict.fromkeys(r["transactionHash"] for r in tape))
    todo = [t for t in txs if t not in receipts]
    if todo:
        os.makedirs(RAW_DIR, exist_ok=True)

        def work(tx: str):
            return tx, rpc_call("eth_getTransactionReceipt", [tx], retry_on_null=True)

        done = 0
        with open(cache_path, "a") as f, ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(work, tx): tx for tx in todo}
            for fut in as_completed(futs):
                try:
                    tx, rec = fut.result()
                except Exception:  # noqa: BLE001 — leave for a later retry
                    tx, rec = futs[fut], None
                if rec:
                    receipts[tx] = rec
                    f.write(json.dumps({"tx": tx, "receipt": rec}) + "\n")
                    f.flush()
                done += 1
                if done % 250 == 0:
                    print(f"  ... {done}/{len(todo)} receipts fetched")
    return receipts


def build_join(tape: list[dict], token_ids, exchange: str, slug: str,
               max_workers: int = 4) -> dict:
    """Fetch (cached) raw receipts and decode each. Returns {tx_hash: decoded}."""
    receipts = fetch_receipts(tape, slug, max_workers=max_workers)
    return {tx: {**decode_receipt(rec, token_ids, exchange), "tx": tx}
            for tx, rec in receipts.items()}


def fetch_orderfilled_logs(exchange: str, from_block: int, to_block: int, token_ids=None,
                           chunk: int = 1000, on_progress=None) -> list[dict]:
    """Verifier-grade complete-tape reconstruction: eth_getLogs OrderFilled for `exchange` over
    [from_block, to_block], chunked + RPC-rotated. The asset id is NON-indexed (in log.data), so
    getLogs can't filter by market — the exchange-wide sweep returns EVERY market's fills (~tens
    of millions over a 6-day window). `token_ids` filters to one market INLINE so memory stays
    bounded (retaining only that market's ~thousands of legs); without it, all legs are kept.

    Returns leg dicts shaped exactly like the subgraph's orderFilledEvents, so the SAME validated
    mapper consumes both. Halves the window on a range/result-size error and grows it back on
    success — adapting to each free RPC's getLogs cap without a hardcoded guess.
    """
    tokens = {str(t) for t in token_ids} if token_ids else None
    legs: list[dict] = []
    seen = 0
    start, cur = from_block, chunk
    while start <= to_block:
        end = min(start + cur - 1, to_block)
        try:
            raw = rpc_call("eth_getLogs", [{"address": exchange, "topics": [ORDERFILLED_SIG],
                                            "fromBlock": hex(start), "toBlock": hex(end)}],
                           max_tries=4)
        except RuntimeError:
            if cur > 1:                      # window too big for this provider -> shrink
                cur = max(cur // 2, 1)
                continue
            raise
        for log in raw:
            seen += 1
            t = log["topics"]
            d = log.get("data", "0x")
            try:
                data = bytes.fromhex(d[2:]) if len(d) > 2 else b""
                m_asset, t_asset, m_amt, t_amt, _fee = abi_decode(["uint256"] * 5, data)
            except (ValueError, KeyError, IndexError):
                continue
            ma, ta = str(m_asset), str(t_asset)
            if tokens is not None and ma not in tokens and ta not in tokens:
                continue                     # drop other markets' fills immediately
            legs.append({"transactionHash": log["transactionHash"],
                         "maker": _addr(t[2]), "taker": _addr(t[3]),
                         "makerAssetId": ma, "takerAssetId": ta,
                         "makerAmountFilled": str(m_amt), "takerAmountFilled": str(t_amt),
                         "timestamp": int(log["blockNumber"], 16)})
        if on_progress:
            on_progress(end, to_block, seen, len(legs))
        start = end + 1
        if cur < chunk:                      # recovered -> grow the window back
            cur = min(cur * 2, chunk)
    return legs
