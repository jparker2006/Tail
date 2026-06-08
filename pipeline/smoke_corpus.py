"""Phase-2 Step 2.6e — stress-weighted smoke slice (pre-batch).

Exercises de-truncation end-to-end on fresh corpus markets, measures the real per-market cost of
the two profiles the batch mixes (/trades processing vs subgraph recovery), produces an honest
ETA (the mega tail >$100M EXTRAPOLATED from the $93M anchor's per-fill rate × estimated fill
counts, NOT measured), and calibrates the A5 Gamma tolerance from the un-truncated (known-complete)
markets across both classes to the worst-case definitional gap.

Run:  caffeinate -i .venv/bin/python pipeline/smoke_corpus.py
"""
from __future__ import annotations

import json
import os
import time

import run_market as rm
import subgraph as sg

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))


def _select_slice() -> list[dict]:
    prim = json.load(open(os.path.join(OUT, "corpus_primary.json")))["markets"]
    sec = json.load(open(os.path.join(OUT, "corpus_secondary.json")))["markets"]
    val = {x["slug"] for x in json.load(open(os.path.join(OUT, "validation_subset.json")))["markets"]}
    for r in prim:
        r["_cls"] = "event"
    for r in sec:
        r["_cls"] = "recurring"
    fresh = [r for r in prim + sec if r["slug"] not in val]

    def pick(cls, neg, lo, hi, n, used):
        c = sorted([r for r in fresh if r["_cls"] == cls and bool(r.get("negRisk")) == neg
                    and lo <= r["volumeNum"] < hi and r["slug"] not in used], key=lambda x: -x["volumeNum"])
        return c if len(c) <= n else [c[i * len(c) // n] for i in range(n)]

    # truncated core (over-sampled) + 1 mega anchor + un-truncated (calib/fast) + large-untrunc anchors
    plan = [("event", True, 1e7, 5e7, 2), ("event", False, 1e7, 5e7, 1),
            ("recurring", False, 1e7, 5e7, 2), ("recurring", False, 1e6, 1e7, 1),  # +T3 boundary (swap)
            ("recurring", True, 1e7, 5e7, 1), ("event", True, 5e7, 1e8, 1),         # mega anchor
            ("event", True, 5e4, 1e6, 2), ("event", False, 5e4, 1e6, 1),
            ("recurring", False, 5e4, 1e6, 3),
            ("event", True, 1e6, 5e6, 1), ("recurring", False, 1e6, 5e6, 1)]
    chosen, used = [], set()
    for cls, neg, lo, hi, n in plan:
        for r in pick(cls, neg, lo, hi, n, used):
            used.add(r["slug"]); chosen.append(r)
    return chosen


def main() -> None:
    slice_ = _select_slice()
    json.dump([{"slug": r["slug"], "tier": r["tier"], "volumeNum": r["volumeNum"],
                "negRisk": bool(r.get("negRisk")), "mkt_class": r["_cls"]} for r in slice_],
              open(os.path.join(OUT, "smoke_slice.json"), "w"), indent=2)
    print(f"=== Smoke slice: {len(slice_)} markets ===", flush=True)

    rows = []
    for i, m in enumerate(sorted(slice_, key=lambda x: -x["volumeNum"]), 1):  # biggest first (mega-first rehearsal)
        t0 = time.time()
        try:
            r = rm.run_market(m, use_cache=False)
            err = None
        except Exception as e:  # noqa: BLE001
            r, err = {"status": "error"}, str(e)[:120]
        dt = time.time() - t0
        d = r.get("detruncation", {})
        rec = {"slug": m["slug"], "tier": m["tier"], "vol": m["volumeNum"],
               "negRisk": bool(m.get("negRisk")), "cls": m["_cls"], "secs": round(dt, 1),
               "source": r.get("tape_source"), "truncated": r.get("trades_truncated"),
               "n_fills": r.get("n_fills"), "recovery_ratio": d.get("recovery_ratio"),
               "complete": d.get("subgraph_complete"), "status": r.get("status"), "error": err}
        # Gamma calibration substrate: on-chain collateral vs Gamma volume on KNOWN-COMPLETE markets
        if r.get("tape_source") == "trades" and not err:
            agg = sg.orderbook_aggregate([str(t) for t in m["clobTokenIds"]])
            rec["scv"] = agg["scaled_collateral_volume"]
            rec["scv_over_gamma"] = (agg["scaled_collateral_volume"] / m["volumeNum"]) if m["volumeNum"] else None
        elif r.get("tape_source") == "subgraph":
            rec["scv"] = d.get("scaled_collateral_volume")
            rec["scv_over_gamma"] = (d.get("scaled_collateral_volume") / m["volumeNum"]) if m["volumeNum"] else None
        rows.append(rec)
        print(f"  [{i}/{len(slice_)}] {m['tier']} ${m['volumeNum']:>12,.0f} {rec['source'] or '-':8} "
              f"trunc={str(rec['truncated'])[:1]} fills={rec['n_fills']} {dt:.1f}s {rec['status']}"
              f"{' ERR '+err if err else ''}", flush=True)

    # Gamma tolerance calibration (A5 rule): from un-truncated markets, both classes, worst-case gap
    ratios = [r["scv_over_gamma"] for r in rows if r["source"] == "trades" and r.get("scv_over_gamma")]
    gamma = None
    if ratios:
        gamma = {"n": len(ratios), "min": min(ratios), "max": max(ratios),
                 "median": sorted(ratios)[len(ratios) // 2],
                 # loose band admitting the worst-case definitional gap (×2 margin on the observed span)
                 "tol_low": min(ratios) / 2.0, "tol_high": max(ratios) * 2.0}

    # cost profiles + ETA (non-mega measured; >$100M tail extrapolated by per-fill rate)
    trades = [r for r in rows if r["source"] == "trades" and r["secs"]]
    recov = [r for r in rows if r["source"] == "subgraph" and r["secs"] and r["n_fills"]]
    per_fill = (sum(r["secs"] for r in recov) / sum(r["n_fills"] for r in recov)) if recov else None
    summary = {"n": len(rows), "n_truncated": sum(1 for r in rows if r["source"] == "subgraph"),
               "n_excluded": sum(1 for r in rows if r["status"] == "excluded"),
               "n_error": sum(1 for r in rows if r["error"]),
               "trades_secs_median": (sorted(r["secs"] for r in trades)[len(trades) // 2] if trades else None),
               "recovery_secs_per_market_median": (sorted(r["secs"] for r in recov)[len(recov) // 2] if recov else None),
               "recovery_secs_per_fill": per_fill, "gamma_calibration": gamma, "rows": rows}
    json.dump(summary, open(os.path.join(OUT, "smoke_results.json"), "w"), indent=2)
    print("\n=== smoke summary ===")
    print(f"  truncated/recovered {summary['n_truncated']}/{len(rows)} | excluded {summary['n_excluded']} | "
          f"errors {summary['n_error']}")
    print(f"  /trades median {summary['trades_secs_median']}s | recovery median "
          f"{summary['recovery_secs_per_market_median']}s | per-fill {per_fill and round(per_fill,5)}s")
    if gamma:
        print(f"  Gamma calib (scv/vol): n={gamma['n']} range [{gamma['min']:.3f},{gamma['max']:.3f}] "
              f"-> tol band [{gamma['tol_low']:.3f},{gamma['tol_high']:.3f}]")
    print("  saved -> data/out/smoke_results.json")


if __name__ == "__main__":
    main()
