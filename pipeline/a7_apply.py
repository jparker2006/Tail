"""Apply A7: admit the 3 truncated taker-anomalies (now gated by A6 leg-completeness alone) and
split-clean the 5 un-truncated split-contaminated markets (re-source from the verified-clean
subgraph). use_cache=False to bypass stale results; raw tape caches reused (truncated) or pulled
(un-truncated force_subgraph). Writes data/out/a7_results.json for the with/without-A7 headline.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, sys.path[0] or "pipeline")
import run_market as rm

TRUNCATED_ADMIT = [   # were excluded by the split-confounded taker gate; A6-complete (gap 0)
    "will-trump-visit-china-by-may-15-835-774-595",
    "megaeth-market-cap-fdv-1pt5b-one-day-after-launch-371-844-879-681",
    "us-escorts-commercial-ship-through-hormuz-by-april-30-894",
]
UNTRUNCATED_CLEAN = [r["slug"] for r in
                     json.load(open("data/out/corpus_integrity_untruncated.json")) if r.get("missing")]


def main() -> None:
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    byslug = {m["slug"]: m for m in prim + sec}
    out = []

    def run(slug, force):
        m = byslug.get(slug)
        if not m:
            print(f"  MISSING from frame: {slug}"); return
        t0 = time.time()
        r = rm.run_market(m, use_cache=False, force_subgraph=force)
        ci = r.get("concentration_interval") or {}
        rec = {"slug": slug, "vol": m["volumeNum"], "group": "admit" if not force else "split-clean",
               "status": r.get("status"), "tape_source": r.get("tape_source"),
               "n_fills": r.get("n_fills"), "n_directional": r.get("n_directional"),
               "gini": ci.get("gini")}
        out.append(rec)
        print(f"  {rec['status']:9} {slug[:50]:50} src={rec['tape_source']} fills={rec['n_fills']} "
              f"gini={rec['gini']} ({round(time.time()-t0,1)}s)", flush=True)

    print("=== A7: admit 3 truncated taker-anomalies (A6 leg-gate only) ===", flush=True)
    for s in TRUNCATED_ADMIT:
        run(s, force=False)
    print("=== A7: split-clean 5 un-truncated (force subgraph = split-filtered /trades) ===", flush=True)
    for s in UNTRUNCATED_CLEAN:
        run(s, force=True)
    json.dump(out, open("data/out/a7_results.json", "w"), indent=2)
    oks = [r for r in out if r["status"] == "ok"]
    print(f"\n{len(oks)}/{len(out)} -> ok. -> data/out/a7_results.json", flush=True)


if __name__ == "__main__":
    main()
