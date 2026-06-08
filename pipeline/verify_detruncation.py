"""De-truncation wired into run_market — connectivity + regression test (A5).

Three checks before the smoke slice:
  1. nba (truncated CTF) — REGRESSION vs the bar-2-certified tape: n_fills must equal 7382 and the
     resulting Gini/F1 are recorded as the known-correct baseline (we have ground truth here, so
     this is a regression check, not a smell test).
  2. a truncated NEGRISK market — no certified baseline, so the bar is: recovered from subgraph,
     completeness gate passes, result sane.
  3. SYNTHETIC forced failure (bad token ids) — the recovery must fail and route to the A5 exclude
     branch, proving the safety valve actually fires (real data is expected never to exercise it).

Run:  .venv/bin/python pipeline/verify_detruncation.py
"""
from __future__ import annotations

import json
import os

import run_market as rm

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))


def _f1(ci: dict) -> bool | None:
    g, nf = ci.get("gini"), ci.get("N_half_frac")
    if g is None or nf is None:
        return None
    return bool(g >= 0.60 and nf <= 0.05)


def main() -> None:
    val = {x["slug"]: x for x in json.load(open(os.path.join(OUT, "validation_subset.json")))["markets"]}
    rows = json.load(open(os.path.join(OUT, "validation_2v3.json")))["rows"]
    res = {}

    # 1) nba regression — n_fills == 7382 (bar-2 certified), record Gini/F1 baseline
    print("=== 1) nba regression (vs bar-2-certified tape) ===")
    r = rm.run_market(val["nba-okc-den-2026-02-01"], use_cache=False)
    ci = r.get("concentration_interval", {})
    res["nba_regression"] = {
        "n_fills": r["n_fills"], "expected_n_fills": 7382, "n_fills_match": r["n_fills"] == 7382,
        "tape_source": r["tape_source"], "recovery_ratio": r.get("detruncation", {}).get("recovery_ratio"),
        "status": r.get("status"), "gini_interval": ci.get("gini"),
        "n_half_frac": ci.get("N_half_frac"), "f1_survives": _f1(ci)}
    print(f"  n_fills {r['n_fills']} (expect 7382) -> {'MATCH' if r['n_fills']==7382 else 'MISMATCH'} "
          f"| source {r['tape_source']} | recovery {res['nba_regression']['recovery_ratio']:.2f}x")
    print(f"  Gini {ci.get('gini')} | N_half_frac {ci.get('N_half_frac')} | F1 {_f1(ci)} (BASELINE)")

    # 2) a truncated negRisk market — recovered, complete, sane
    print("\n=== 2) truncated negRisk recovery ===")
    nr = next(x for x in rows if x.get("negRisk") and x.get("trades_truncated")
              and x["slug"] in val)
    r2 = rm.run_market(val[nr["slug"]], use_cache=False)
    d2 = r2.get("detruncation", {})
    res["negrisk_recovery"] = {"slug": nr["slug"], "tape_source": r2["tape_source"],
        "recovery_ratio": d2.get("recovery_ratio"), "subgraph_complete": d2.get("subgraph_complete"),
        "status": r2.get("status"), "n_fills": r2["n_fills"],
        "gini_interval": r2.get("concentration_interval", {}).get("gini")}
    print(f"  {nr['slug'][:46]}: source {r2['tape_source']} | complete {d2.get('subgraph_complete')} "
          f"| recovery {d2.get('recovery_ratio')} | n_fills {r2['n_fills']} | status {r2.get('status')}")

    # 3) synthetic forced failure — bad token ids must trip the exclude branch
    print("\n=== 3) synthetic forced failure (exclude valve) ===")
    fake = {"slug": "__synthetic_bad_tokens__", "clobTokenIds": ["123", "456"], "negRisk": False}
    _, _, meta = rm._subgraph_tapes(fake, n_trades_taker=5000)
    excludes = not meta["recovered_ok"]
    res["synthetic_failure"] = {"n_legs": meta["n_legs"], "trades_quantity": meta["trades_quantity"],
        "recovered_ok": meta["recovered_ok"], "routes_to_exclude": excludes}
    print(f"  bad tokens -> n_legs {meta['n_legs']}, recovered_ok {meta['recovered_ok']} -> "
          f"{'EXCLUDE branch fires' if excludes else 'DID NOT EXCLUDE (bug!)'}")

    ok = (res["nba_regression"]["n_fills_match"] and res["negrisk_recovery"]["tape_source"] == "subgraph"
          and res["negrisk_recovery"]["subgraph_complete"] and res["synthetic_failure"]["routes_to_exclude"])
    res["all_pass"] = bool(ok)
    json.dump(res, open(os.path.join(OUT, "detruncation_connectivity.json"), "w"), indent=2)
    print(f"\n  --> de-truncation connectivity {'PASS' if ok else 'FAIL'} "
          f"-> data/out/detruncation_connectivity.json")


if __name__ == "__main__":
    main()
