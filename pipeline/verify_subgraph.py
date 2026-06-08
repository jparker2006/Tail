"""Phase-2 — subgraph transport verification (two bars, before it is trusted/used).

The subgraph (subgraph.py) is the de-truncation source: complete per-market aggressor tapes past
the /trades 8000-cap. Before any corpus market is analyzed from it, it must clear two bars
(CORPUS_PREREG A5, queued):

  bar 1  — mapped subgraph fills match the trusted /trades tape EXACTLY on an un-truncated
           market (validates the dual-leg -> canonical aggressor mapping, the load-bearing risk).
  bar 2  — mapped subgraph fills match on-chain getLogs on a truncated market's BEYOND-ceiling
           fills (validates the fills /trades can't see). [added with the verifier-grade getLogs]

Reconciliation is on raw 6-dp integer amounts, keyed by (tx, wallet, token, side). Aggregates
(n_fills, Gini, F1) match by construction once the fills do.

Run:  .venv/bin/python pipeline/verify_subgraph.py bar1
"""
from __future__ import annotations

import json
import os
import sys

import subgraph as sg

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
RAW = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


def _agg_trades(rows: list[dict]) -> dict:
    """/trades rows -> {(tx,wallet,token,side): {shares_int, collateral_int}} in 6-dp integers."""
    out: dict[tuple, dict] = {}
    for r in rows:
        key = (r["transactionHash"], r["proxyWallet"].lower(), str(r["asset"]), r["side"])
        o = out.setdefault(key, {"shares": 0.0, "notional": 0.0})
        o["shares"] += float(r["size"])
        o["notional"] += float(r["size"]) * float(r["price"])
    return {k: {"shares_int": round(v["shares"] * 1e6),
                "collateral_int": round(v["notional"] * 1e6)} for k, v in out.items()}


def _keyed(fills: list[dict]) -> dict:
    return {(f["transactionHash"], f["proxyWallet"].lower(), f["asset"], f["side"]):
            {"shares_int": f["shares_int"], "collateral_int": f["collateral_int"]} for f in fills}


def bar1(slug: str, exchange: str) -> dict:
    """Mapped subgraph tape vs trusted (un-truncated) /trades tape, fill for fill."""
    tp = json.load(open(os.path.join(RAW, f"{slug}_trades_taker.json")))
    trades = tp["rows"] if isinstance(tp, dict) and "rows" in tp else tp
    tokens = sorted({str(r["asset"]) for r in trades})
    T = _agg_trades(trades)
    G = _keyed(sg.map_aggressor_fills(sg.fetch_market_legs(tokens), tokens, exchange))
    kT, kG = set(T), set(G)
    both = kT & kG
    sh_exact = sum(1 for k in both if T[k]["shares_int"] == G[k]["shares_int"])
    rel = sorted(abs(T[k]["collateral_int"] - G[k]["collateral_int"])
                 / max(T[k]["collateral_int"], G[k]["collateral_int"], 1) for k in both)
    res = {
        "bar": "1_vs_trades", "slug": slug, "n_trades_keys": len(T), "n_subgraph_keys": len(G),
        "in_both": len(both), "only_trades": len(kT - kG), "only_subgraph": len(kG - kT),
        "shares_exact": sh_exact, "shares_exact_rate": sh_exact / len(both) if both else None,
        "collateral_reldiff_median": rel[len(rel) // 2] if rel else None,
        "collateral_reldiff_p99": rel[int(0.99 * len(rel))] if rel else None,
    }
    res["pass"] = bool(res["only_trades"] == 0 and res["only_subgraph"] == 0
                       and res["shares_exact_rate"] == 1.0)
    return res


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "bar1"
    if mode == "bar1":
        # biden-drops-out-in-july: un-truncated (2716 rows), binary (CTF) — the trusted baseline.
        r = bar1("biden-drops-out-in-july", sg.CTF_EXCHANGE_V1)
        print("=== Subgraph verification — bar 1 (vs /trades, un-truncated) ===")
        print(f"  {r['slug']}: /trades {r['n_trades_keys']} keys, subgraph {r['n_subgraph_keys']}")
        print(f"  in-both {r['in_both']} | only-/trades {r['only_trades']} | "
              f"only-subgraph {r['only_subgraph']}")
        print(f"  shares EXACT {r['shares_exact']}/{r['in_both']} "
              f"({(r['shares_exact_rate'] or 0)*100:.2f}%)")
        print(f"  collateral rel-diff: median {r['collateral_reldiff_median']:.2e} "
              f"p99 {r['collateral_reldiff_p99']:.2e}")
        print(f"  --> bar 1 {'PASS' if r['pass'] else 'FAIL'}")
        path = os.path.join(OUT, "subgraph_validation.json")
        prev = json.load(open(path)) if os.path.exists(path) else {}
        prev["bar1"] = r
        json.dump(prev, open(path, "w"), indent=2)
        print("  saved -> data/out/subgraph_validation.json")


if __name__ == "__main__":
    main()
