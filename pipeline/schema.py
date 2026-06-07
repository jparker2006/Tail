"""Canonical normalized trade schema (Phase 1, Step 1.4).

Collapses both outcome tokens into token-0 ("Yes") space and derives the fields the rest of
the pipeline consumes: p_yes, signed direction d, truth-signed d_star, role, and per-wallet
aggregates (taker vs maker volume) that feed the MM filter. See FALSIFICATION.md for the
frozen definitions.

Conventions:
  - token-0 == outcomes[0] == "Yes"; p_yes in [0,1].
  - d  (token-0 direction of the aggressor) = +1 if (outcome_index==0)==(side=="BUY") else -1.
  - R_yes = 1 if token-0 (Yes) resolved true, else 0; d_star = d if R==1 else -d.
  - A maker trades the SAME token opposite the taker, so the maker's token-0 signed delta is
    -d * maker_shares.
"""
from __future__ import annotations

from collections import defaultdict


def market_truth(market: dict) -> int:
    """R_yes: 1 if token-0 ("Yes") won, else 0."""
    return 1 if market.get("resolved_outcome_index") == 0 else 0


def normalize_fills(tape: list[dict], decoded_by_tx: dict, market: dict) -> tuple[list[dict], int]:
    """One canonical record per aggressor fill, time-sorted, in token-0 space."""
    R = market_truth(market)
    fills: list[dict] = []
    for r in tape:
        oi = int(r["outcomeIndex"])
        side = r["side"]
        price = float(r["price"])
        size = float(r["size"])
        p_yes = price if oi == 0 else 1.0 - price
        d = 1 if ((oi == 0) == (side == "BUY")) else -1
        usdc = price * size
        dec = decoded_by_tx.get(r["transactionHash"], {})
        fills.append({
            "fill_id": f"{r['transactionHash']}:{r['asset']}",
            "tx_hash": r["transactionHash"],
            "ts": int(r["timestamp"]),
            "asset_id": r["asset"],
            "outcome_index": oi,
            "proxy_wallet": r["proxyWallet"].lower(),
            "wallet_name": r.get("name") or r.get("pseudonym"),
            "raw_side": side,
            "raw_price": price,
            "size": size,
            "usdc_notional": usdc,
            "p_yes": p_yes,
            "d": d,
            "d_star": d if R == 1 else -d,
            "signed_shares": d * size,
            "signed_notional": d * usdc,
            "role": "aggressor",
            "maker_legs": dec.get("maker_legs", []),
        })
    fills.sort(key=lambda f: (f["ts"], f["tx_hash"]))
    return fills, R


def _blank() -> dict:
    return {"taker_shares": 0.0, "taker_notional": 0.0, "taker_signed": 0.0, "n_taker": 0,
            "maker_shares": 0.0, "maker_notional": 0.0, "maker_signed": 0.0, "n_maker": 0,
            "name": None}


def wallet_stats(fills: list[dict]) -> dict:
    """Per-wallet aggregates over BOTH roles (the MM-filter substrate).

    flatness = |net_shares| / gross_shares ; aggressor_share = taker_shares / gross_shares.
    Pure LPs (never aggress) appear here via their maker legs even though they're absent from
    the taker tape.
    """
    W: dict[str, dict] = defaultdict(_blank)
    for f in fills:
        w = W[f["proxy_wallet"]]
        w["taker_shares"] += f["size"]
        w["taker_notional"] += f["usdc_notional"]
        w["taker_signed"] += f["signed_shares"]
        w["n_taker"] += 1
        if f["wallet_name"] and not w["name"]:
            w["name"] = f["wallet_name"]
        d, price = f["d"], f["raw_price"]
        for addr, msh in f["maker_legs"]:
            m = W[addr.lower()]
            m["maker_shares"] += msh
            m["maker_signed"] += -d * msh
            m["maker_notional"] += msh * price
            m["n_maker"] += 1
    out: dict[str, dict] = {}
    for addr, w in W.items():
        gross = w["taker_shares"] + w["maker_shares"]
        net = w["taker_signed"] + w["maker_signed"]
        out[addr] = {**w,
                     "gross_shares": gross,
                     "net_shares": net,
                     "gross_notional": w["taker_notional"] + w["maker_notional"],
                     "flatness": (abs(net) / gross) if gross > 0 else None,
                     "aggressor_share": (w["taker_shares"] / gross) if gross > 0 else None}
    return out


def price_path(fills: list[dict]) -> list[list]:
    """Executed token-0 price path: [[ts, p_yes], ...] in time order."""
    return [[f["ts"], f["p_yes"]] for f in fills]
