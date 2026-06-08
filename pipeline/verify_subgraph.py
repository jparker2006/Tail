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


def _load_trades(slug: str) -> list[dict]:
    """Cached taker /trades tape — Phase-1 used `_trades_taker`, the param run uses `_taker`."""
    for suffix in ("_trades_taker.json", "_taker.json"):
        p = os.path.join(RAW, slug + suffix)
        if os.path.exists(p):
            tp = json.load(open(p))
            return tp["rows"] if isinstance(tp, dict) and "rows" in tp else tp
    raise FileNotFoundError(f"no cached taker tape for {slug}")


def bar1(slug: str, exchange: str) -> dict:
    """Mapped subgraph tape vs trusted (un-truncated) /trades tape, fill for fill."""
    trades = _load_trades(slug)
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


def _reconcile(A: dict, B: dict) -> dict:
    """Fill-level reconciliation of two keyed tapes on (tx,wallet,token,side), raw-int shares."""
    kA, kB = set(A), set(B)
    both = kA & kB
    sh = sum(1 for k in both if A[k]["shares_int"] == B[k]["shares_int"])
    return {"n_A": len(A), "n_B": len(B), "in_both": len(both),
            "only_A": len(kA - kB), "only_B": len(kB - kA),
            "shares_exact": sh, "shares_exact_rate": sh / len(both) if both else None,
            "exact": bool(len(kA - kB) == 0 and len(kB - kA) == 0 and both and sh == len(both))}


def _leg_key(l: dict) -> tuple:
    return (l["transactionHash"], l["maker"].lower(), l["taker"].lower(),
            str(l["makerAssetId"]), str(l["takerAssetId"]),
            str(l["makerAmountFilled"]), str(l["takerAmountFilled"]))


def bar2(slug: str, exchange: str, from_block: int, to_block: int) -> dict:
    """Certify the subgraph's BEYOND-ceiling fills against on-chain getLogs.

    Trust chain (so a mismatch is never ambiguous):
      2a  getLogs aggressor fills vs /trades on the recency overlap — validates the NEW getLogs
          extraction against the gold standard on the region /trades can see.
      2b  getLogs vs subgraph on the FULL tape — getLogs now trusted, so a beyond-ceiling match
          certifies the subgraph; any mismatch is attributed to the subgraph.
      2c  RAW-leg multiset reconciliation getLogs vs subgraph — validates the MAKER legs (the
          flatness substrate the MM filter consumes), which the aggressor-collapse never touched.
    Plus a completeness check: paginated legs == the subgraph's own Σ tradesQuantity aggregate.
    """
    import onchain
    from collections import Counter
    trades = _load_trades(slug)
    tokens = sorted({str(r["asset"]) for r in trades})
    span = to_block - from_block

    sg_legs, sg_meta = sg.fetch_market_legs_checked(tokens)   # + completeness vs aggregate

    cache = os.path.join(RAW, f"{slug}_getlogs_legs.json")
    if os.path.exists(cache):
        gl_legs = json.load(open(cache))
        print(f"  getLogs legs loaded from cache ({len(gl_legs)})")
    else:
        def prog(end, hi, seen, kept):
            pct = 100 * (end - from_block) / span
            if int(pct) % 10 == 0 and int(pct) != getattr(prog, "_last", -1):
                prog._last = int(pct)
                print(f"    getLogs {pct:3.0f}%  ({seen:,} scanned, {kept} kept)", flush=True)
        print(f"  reconstructing via getLogs ({span} blocks)…", flush=True)
        gl_legs = onchain.fetch_orderfilled_logs(exchange, from_block, to_block,
                                                 token_ids=tokens, on_progress=prog)
        json.dump(gl_legs, open(cache, "w"))

    # 2c — raw legs as multisets (maker + taker + self legs); validates the flatness substrate
    gl_m, sg_m = Counter(_leg_key(l) for l in gl_legs), Counter(_leg_key(l) for l in sg_legs)
    legs = {"n_getlogs_legs": len(gl_legs), "n_subgraph_legs": len(sg_legs),
            "only_getlogs": sum((gl_m - sg_m).values()),
            "only_subgraph": sum((sg_m - gl_m).values()), "exact": bool(gl_m == sg_m)}

    getlogs = _keyed(sg.map_aggressor_fills(gl_legs, tokens, exchange))
    subg = _keyed(sg.map_aggressor_fills(sg_legs, tokens, exchange))
    trd = _agg_trades(trades)
    r2a = _reconcile(getlogs, trd)          # getLogs vs /trades overlap
    r2b = _reconcile(getlogs, subg)         # getLogs vs subgraph aggressor collapse

    res = {"bar": "2_vs_getlogs", "slug": slug, "from_block": from_block, "to_block": to_block,
           "n_getlogs_fills": len(getlogs), "n_subgraph_fills": len(subg),
           "n_trades_partial": len(trd), "subgraph_completeness": sg_meta,
           "bar2a_getlogs_vs_trades_overlap": r2a, "bar2b_getlogs_vs_subgraph_full": r2b,
           "bar2c_raw_legs_vs_subgraph": legs,
           "bar2a_pass": bool(r2a["only_B"] == 0 and r2a["shares_exact_rate"] == 1.0),
           "bar2b_pass": r2b["exact"], "bar2c_legs_pass": legs["exact"],
           "completeness_pass": sg_meta["complete"],
           "detruncation_factor": len(subg) / max(len(trd), 1)}
    res["pass"] = bool(res["bar2a_pass"] and res["bar2b_pass"]
                       and res["bar2c_legs_pass"] and res["completeness_pass"])
    return res


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "bar1"
    if mode == "bar1":
        # Bar 1 across BOTH subgraph exchange paths, on un-truncated markets (no getLogs needed):
        #   CTF     — biden-drops-out-in-july (2716 fills, negRisk=False)
        #   NegRisk — atlanta-braves-win-2025-world-series (6946 fills, negRisk=True)
        targets = [("biden-drops-out-in-july", sg.CTF_EXCHANGE_V1, "ctf"),
                   ("will-the-atlanta-braves-win-the-2025-world-series",
                    sg.NEGRISK_EXCHANGE_V1, "negrisk")]
        print("=== Subgraph verification — bar 1 (mapped fills vs /trades, un-truncated) ===")
        path = os.path.join(OUT, "subgraph_validation.json")
        prev = json.load(open(path)) if os.path.exists(path) else {}
        all_pass = True
        for slug, exch, label in targets:
            r = bar1(slug, exch)
            r["exchange_path"] = label
            all_pass = all_pass and r["pass"]
            print(f"\n  [{label}] {slug[:50]}")
            print(f"    /trades {r['n_trades_keys']} keys, subgraph {r['n_subgraph_keys']} | "
                  f"in-both {r['in_both']} | only-/trades {r['only_trades']} | "
                  f"only-subgraph {r['only_subgraph']}")
            print(f"    shares EXACT {r['shares_exact']}/{r['in_both']} "
                  f"({(r['shares_exact_rate'] or 0)*100:.2f}%) | "
                  f"collateral rel-diff median {r['collateral_reldiff_median']:.2e} | "
                  f"{'PASS' if r['pass'] else 'FAIL'}")
            prev[f"bar1_{label}"] = r
        json.dump(prev, open(path, "w"), indent=2)
        print(f"\n  --> bar 1 (both paths) {'PASS' if all_pass else 'FAIL'}  "
              f"-> data/out/subgraph_validation.json")

    elif mode == "bar2":
        # nba-okc-den: truncated (4947/trades, recency-biased), CTF, short ~6-day block range.
        FROM, TO = 82181759, 82451744
        r = bar2("nba-okc-den-2026-02-01", sg.CTF_EXCHANGE_V1, FROM, TO)
        print("\n=== Subgraph verification — bar 2 (beyond-ceiling, vs on-chain getLogs) ===")
        a, b, c = (r["bar2a_getlogs_vs_trades_overlap"], r["bar2b_getlogs_vs_subgraph_full"],
                   r["bar2c_raw_legs_vs_subgraph"])
        cm = r["subgraph_completeness"]
        print(f"  getLogs fills {r['n_getlogs_fills']} | subgraph fills {r['n_subgraph_fills']} | "
              f"/trades partial {r['n_trades_partial']}")
        print(f"  2a getLogs vs /trades overlap : /trades keys missing from getLogs {a['only_B']} "
              f"| shares {a['shares_exact']}/{a['in_both']} -> {'PASS' if r['bar2a_pass'] else 'FAIL'}")
        print(f"  2b getLogs vs subgraph (fills): only-gl {b['only_A']} only-sg {b['only_B']} "
              f"| shares {b['shares_exact']}/{b['in_both']} -> {'PASS' if r['bar2b_pass'] else 'FAIL'}")
        print(f"  2c raw legs (maker substrate) : gl {c['n_getlogs_legs']} sg {c['n_subgraph_legs']} "
              f"| only-gl {c['only_getlogs']} only-sg {c['only_subgraph']} -> "
              f"{'PASS' if r['bar2c_legs_pass'] else 'FAIL'}")
        print(f"  completeness (legs==ΣtradesQty): {cm['n_legs']} vs {cm['trades_quantity']} -> "
              f"{'PASS' if r['completeness_pass'] else 'FAIL'}")
        print(f"  de-truncation: subgraph recovered {r['detruncation_factor']:.2f}x /trades")
        print(f"  --> bar 2 {'PASS' if r['pass'] else 'FAIL'}")
        path = os.path.join(OUT, "subgraph_validation.json")
        prev = json.load(open(path)) if os.path.exists(path) else {}
        prev["bar2"] = r
        json.dump(prev, open(path, "w"), indent=2)
        print("  saved -> data/out/subgraph_validation.json")


if __name__ == "__main__":
    main()
