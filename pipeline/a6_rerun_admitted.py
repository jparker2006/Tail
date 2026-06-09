"""Run the 16 A6-admitted near-complete markets through the amended gate to obtain their Claim-1
stats (Gini, N_half) WITHOUT touching the shared manifest (the timeout re-run may still be merging).
Cache-based: reads each market's cached subgraph tape, the amended is_complete() flips recovered_ok
to True, the claims pipeline runs. Writes data/out/a6_admitted_results.json for the with/without
headline comparison. The authoritative manifest re-merge happens later in one clean pass.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, sys.path[0] or "pipeline")
import run_market as rm

ADMITTED = [
    "will-polymarket-us-go-live-in-2025", "will-avatar-3-be-the-top-grossing-movie-of-2025",
    "will-the-new-york-jets-win-super-bowl-2026", "lighter-market-cap-fdv-2b-one-day-after-launch-3320",
    "will-the-san-francisco-49ers-win-super-bowl-2026",
    "fed-decreases-interest-rates-by-50-bps-after-july-2025-meeting",
    "will-the-tennessee-titans-win-super-bowl-2026", "will-bitcoin-reach-200000-by-december-31-2025",
    "will-the-cleveland-browns-win-super-bowl-2026", "boxing-andrew-tate-vs-chase-demoor",
    "will-the-las-vegas-raiders-win-super-bowl-2026", "lighter-market-cap-fdv-1b-one-day-after-launch",
    "will-the-miami-dolphins-win-super-bowl-2026", "will-kabuto-1st-edition-card-hit-100-by-december-31",
    "china-x-taiwan-military-clash-by-december-31", "nba-mem-min-2025-12-17",
]


def main() -> None:
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    byslug = {m["slug"]: m for m in prim + sec}
    out = []
    for i, slug in enumerate(ADMITTED, 1):
        m = byslug.get(slug)
        if not m:
            print(f"  [{i}/16] MISSING from corpus frame: {slug}", flush=True)
            continue
        t0 = time.time()
        # use_cache=False: bypass the batch's stale 'excluded' RESULT cache so the amended gate runs;
        # raw tape/subgraph/breadth caches are still reused (no re-pull). Overwrites the result cache
        # to 'ok' so the authoritative manifest re-merge (use_cache=True) picks up the flip.
        r = rm.run_market(m, use_cache=False)
        ci = r.get("concentration_interval") or {}
        rec = {"slug": slug, "vol": m["volumeNum"], "cls": m.get("mkt_class"),
               "status": r.get("status"), "tape_source": r.get("tape_source"),
               "n_fills": r.get("n_fills"), "n_directional": r.get("n_directional"),
               "gini": ci.get("gini"), "n_half_frac": ci.get("N_half_frac")}
        out.append(rec)
        print(f"  [{i}/16] {rec['status']:9} {slug[:46]:46} gini={rec['gini']} "
              f"n_dir={rec['n_directional']} ({round(time.time()-t0,1)}s)", flush=True)
    json.dump(out, open("data/out/a6_admitted_results.json", "w"), indent=2)
    oks = [r for r in out if r["status"] == "ok" and r["gini"] is not None]
    print(f"\n{len(oks)}/16 -> ok with gini. -> data/out/a6_admitted_results.json", flush=True)


if __name__ == "__main__":
    main()
