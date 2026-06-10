"""Step 2.7c — F2' K-robustness {5,10,20} + the anti-wisdom underperform tail, event/headline.

The F2' kill criterion (fraction of markets whose top-K=10 movers beat Null B at the 95th pct,
vs the 5%-by-chance baseline) already reads SMART (step 2.7). This adds the two frozen companions
from CORPUS_PREREG §F2':
  - K robustness: report the beats-Null-B fraction at K = 5, 10, 20 (K=10 stays the kill).
  - anti-wisdom: the fraction where the top-K systematically UNDERPERFORM (observed PnL below Null
    B's 5th pct) — a descriptive add (not a kill gate), pre-registered so it stays credible if it
    appears (Phase 1 hinted at it: two whales shorted Yes and lost).

Cached-only (no network); reuses the f1_riders tape/MM-set plumbing. A K=10 guard asserts the
recomputed beats_B reproduces the cached claim2 (deterministic seed) — proving the recompute path
is the one that produced the closed corpus. Refreshes each event result cache's claim2 (now with
nullB p05 + underperforms_B) and writes the K-sweep summary to data/out/corpus_f2_ksweep.json.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
from scipy.stats import binomtest

import claims
import f1_riders as fr

KS = (5, 10, 20)
K_PRIMARY = 10
RESULTS = fr.RESULTS
OUT = os.path.join("data", "out", "corpus_f2_ksweep.json")


def main():
    rows = fr._load(fr.MANIFEST)["rows"]
    markets = {m["slug"]: m for m in fr._load(fr.PRIMARY)["markets"]}
    slugs = [s for s, r in rows.items() if r.get("status") == "ok" and r.get("cls") == "event"]

    beats = {k: 0 for k in KS}
    under = {k: 0 for k in KS}
    n_valid = {k: 0 for k in KS}
    guard_fail = []
    n_eval = 0
    t0 = time.time()
    print(f"=== F2' K-sweep + underperform — event ok markets n={len(slugs)} ===", flush=True)
    for i, slug in enumerate(slugs, 1):
        market, result = markets.get(slug), fr._load(os.path.join(RESULTS, f"{slug}.json"))
        if market is None:
            raise KeyError(f"{slug}: not in corpus_primary.json")
        fills, R, wstats, breadth, aggr, vol = fr._ingredients(market, result)
        mm = fr._mm_set(wstats, vol, breadth, aggr, fr.FLAT_PRIMARY)

        c2 = {}
        for k in KS:
            c2[k] = claims.claim2(fills, R, mm, K=k)
            if c2[k].get("beats_B") is not None:
                n_valid[k] += 1
                beats[k] += int(bool(c2[k]["beats_B"]))
                under[k] += int(bool(c2[k].get("underperforms_B")))

        # guard: K=10 reproduces the cached beats_B (deterministic seed=12345)
        cached = result.get("claim2") or {}
        if cached.get("beats_B") is not None and c2[K_PRIMARY]["beats_B"] != cached["beats_B"]:
            guard_fail.append((slug, c2[K_PRIMARY]["beats_B"], cached["beats_B"]))
        # refresh the cached K=10 claim2 with the new fields (p05 + underperforms_B)
        result["claim2"] = c2[K_PRIMARY]
        with open(os.path.join(RESULTS, f"{slug}.json"), "w") as f:
            json.dump(result, f)
        n_eval += 1
        if i == 1 or i % 200 == 0 or i == len(slugs):
            print(f"  {i:4d}/{len(slugs)}  beatsB(K10)={beats[10]}/{n_valid[10]}  "
                  f"guard_fail={len(guard_fail)}  elapsed={(time.time()-t0)/60:.1f}m", flush=True)

    def report(counts, label):
        d = {}
        for k in KS:
            n = n_valid[k]
            frac = counts[k] / n if n else None
            bt = binomtest(counts[k], n, 0.05, alternative="greater") if n else None
            d[str(k)] = {"n": n, "count": counts[k], "frac": frac,
                         "binom_p_vs_5pct": (bt.pvalue if bt else None)}
        return d

    out = {"label": "event/headline", "n_eval": n_eval, "guard_fail_count": len(guard_fail),
           "guard_fail_sample": guard_fail[:5],
           "beats_B_by_K": report(beats, "beats_B"),
           "underperforms_B_by_K": report(under, "underperforms_B")}
    json.dump(out, open(OUT, "w"), indent=2)

    print("\n--- F2' K-SWEEP (event headline) ---")
    print(f"  K=10 guard reproduction failures: {len(guard_fail)} / {n_eval}")
    for k in KS:
        b = out["beats_B_by_K"][str(k)]
        u = out["underperforms_B_by_K"][str(k)]
        print(f"  K={k:2d}: beats Null B {b['count']}/{b['n']} = {b['frac']*100:.1f}%  "
              f"(p vs 5% = {b['binom_p_vs_5pct']:.2e})   | underperforms B "
              f"{u['count']}/{u['n']} = {u['frac']*100:.1f}%")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
