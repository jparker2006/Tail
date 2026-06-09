"""Targeted re-run of `timeouts_to_review` at concurrency 1 on the quiet shard.

A load-timeout during the hammered batch is a transient blip, NOT a coverage gap (CORPUS_PREREG
A5). Re-running each timed-out market alone, on an unloaded shard, recovers the ones that were only
starved for shard capacity. Reuses run_corpus.process + run_corpus._merge so the manifest format and
the coverage-gap / timeouts_to_review bookkeeping stay identical — recovered markets simply drop out
of timeouts_to_review on the re-merge. Resumable: markets with a cached result are skipped by
run_market's own use_cache path. Writes nothing new; only updates corpus_run_manifest.json in place.
"""
from __future__ import annotations

import json
import sys
import time

import run_corpus as rc


def main() -> None:
    man = json.load(open(rc.MANIFEST))
    todo = list(man["summary"].get("timeouts_to_review", []))
    by_slug = {m["slug"]: m for m in rc._corpus()}
    work = [by_slug[s] for s in todo if s in by_slug]
    print(f"=== timeout re-run: {len(work)} markets @ concurrency 1 (quiet shard) ===", flush=True)

    rows, t_start = [], time.time()
    for i, m in enumerate(work, 1):
        r = rc.process(m)                      # same path as the batch (run_market, use_cache)
        rows.append(r)
        st = r.get("status")
        extra = (f"src={r.get('tape_source')} fills={r.get('n_fills')} gini={r.get('gini')}"
                 if st == "ok" else r.get("excluded_reason") or r.get("error", "")[:60] or "")
        print(f"  [{i}/{len(work)}] {st:9} {r['slug'][:48]:48} {extra}", flush=True)
        if i % 5 == 0:                         # checkpoint the manifest periodically
            rc._merge(rows); rows = []
    summary = rc._merge(rows)
    print(f"\n=== done in {round((time.time()-t_start)/60,1)} min ===", flush=True)
    print("by_status:", summary["by_status"], flush=True)
    print("timeouts_to_review NOW:", len(summary.get("timeouts_to_review", [])), flush=True)
    print("coverage_gap n_excluded NOW:", summary["coverage_gap"]["n_excluded"], flush=True)


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    main()
