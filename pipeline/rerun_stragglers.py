"""Solo retry of the post-batch stragglers: timeouts_to_review UNION errored.

After the 35-timeout batch, a handful of ~380k-leg markets failed on TRANSIENT shard load — some as
'timeout' (statement timeout), some as 'error' (HTTP 503) — clustered at the hot tail of a ~5h run.
Both are the same recoverable shard-capacity blip (CORPUS_PREREG A5), NOT a coverage gap; the
index-asymmetry fix (step 2.6g) is already proven on the 30 that recovered. rerun_timeouts.py only
reads timeouts_to_review, so this variant unions in `errored` too. Optional COOLDOWN_SEC (argv[1],
default 600) lets the sustained-load shard recover before re-hammering. Reuses run_corpus.process +
_merge — recovered markets drop out of both lists on the re-merge. Resumable; updates the manifest
in place.
"""
from __future__ import annotations

import json
import sys
import time

import run_corpus as rc

COOLDOWN_SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 600


def main() -> None:
    man = json.load(open(rc.MANIFEST))
    s = man["summary"]
    todo = list(dict.fromkeys(list(s.get("timeouts_to_review", [])) + list(s.get("errored", []))))
    by_slug = {m["slug"]: m for m in rc._corpus()}
    work = [by_slug[sl] for sl in todo if sl in by_slug]
    print(f"=== straggler retry: {len(work)} markets (timeout+error) @ concurrency 1 ===", flush=True)
    for sl in todo:
        print(f"    - {sl}", flush=True)
    if COOLDOWN_SEC > 0:
        print(f"=== cooling down {COOLDOWN_SEC}s for the shard to recover from sustained load ===",
              flush=True)
        time.sleep(COOLDOWN_SEC)

    rows, t_start = [], time.time()
    for i, m in enumerate(work, 1):
        r = rc.process(m)
        rows.append(r)
        st = r.get("status")
        extra = (f"src={r.get('tape_source')} fills={r.get('n_fills')} gini={r.get('gini')}"
                 if st == "ok" else (r.get("error", "") or r.get("excluded_reason") or "")[:70])
        print(f"  [{i}/{len(work)}] {st:9} {r['slug'][:46]:46} {extra}", flush=True)
    summary = rc._merge(rows)
    print(f"\n=== done in {round((time.time()-t_start)/60,1)} min ===", flush=True)
    print("by_status:", summary["by_status"], flush=True)
    print("timeouts_to_review NOW:", summary.get("timeouts_to_review"), flush=True)
    print("errored NOW:", summary.get("errored"), flush=True)
    print("coverage_gap n_excluded NOW:", summary["coverage_gap"]["n_excluded"],
          "vol share:", round(summary["coverage_gap"]["excluded_volume_share"], 4), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    main()
