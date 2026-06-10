"""Step 2.7d — within-tier event-vs-recurring concentration contrast (CORPUS_PREREG A2.4).

The pooled event-vs-recurring Gini gap (0.866 vs 0.831) confounds market TYPE with VOLUME: the event
sample skews to higher tiers (T4 is take-all event). A2.4 freezes the contrast WITHIN each volume
tier so volume is held fixed and only type varies. This answers: is the concentration finding a
property of belief/event markets specifically, or of all V1 markets regardless of type?

Reads the manifest (interval Gini + N_half/n + tier + class per ok market — no cache loading). Per
tier reports event vs recurring median Gini and median N_half/n, plus a Mann-Whitney U on the Gini
distributions (two-sided; type-effect is a finding in either direction). Recurring is never pooled
into the F1' headline (A2.4); this is the only place the two populations are compared.
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy.stats import mannwhitneyu

MANIFEST = os.path.join("data", "out", "corpus_run_manifest.json")
OUT = os.path.join("data", "out", "corpus_event_vs_recurring.json")
TIERS = ("T1", "T2", "T3", "T4")


def _stats(vals):
    a = np.array([v for v in vals if v is not None], float)
    if not a.size:
        return {"n": 0, "median": None, "p25": None, "p75": None}
    return {"n": int(a.size), "median": float(np.median(a)),
            "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75))}


def main():
    rows = [r for r in json.load(open(MANIFEST))["rows"].values() if r.get("status") == "ok"]
    out = {"by_tier": {}, "pooled": {}}
    print("=== A2.4 within-tier event-vs-recurring concentration contrast ===")
    print(f"{'tier':5} {'n_ev':>5} {'n_rec':>5} {'gini_ev':>8} {'gini_rec':>8} {'Δ(ev-rec)':>10} "
          f"{'MWU_p':>9}  {'Nhf_ev':>7} {'Nhf_rec':>7}")
    for tier in (*TIERS, "ALL"):
        ev = [r for r in rows if r.get("cls") == "event" and (tier == "ALL" or r.get("tier") == tier)]
        rec = [r for r in rows if r.get("cls") == "recurring" and (tier == "ALL" or r.get("tier") == tier)]
        ge = [r.get("gini") for r in ev]
        gr = [r.get("gini") for r in rec]
        ne = [r.get("n_half_frac") for r in ev]
        nr = [r.get("n_half_frac") for r in rec]
        se, sr = _stats(ge), _stats(gr)
        sne, snr = _stats(ne), _stats(nr)
        ge_c = [g for g in ge if g is not None]
        gr_c = [g for g in gr if g is not None]
        mwu_p = (float(mannwhitneyu(ge_c, gr_c, alternative="two-sided").pvalue)
                 if len(ge_c) >= 3 and len(gr_c) >= 3 else None)
        delta = (se["median"] - sr["median"]) if (se["median"] is not None and sr["median"] is not None) else None
        rec_out = {"n_event": se["n"], "n_recurring": sr["n"],
                   "gini_event": se, "gini_recurring": sr,
                   "delta_median_gini": delta, "mannwhitney_p": mwu_p,
                   "nhalf_frac_event": sne, "nhalf_frac_recurring": snr}
        (out["pooled"] if tier == "ALL" else out["by_tier"]).__setitem__(tier, rec_out)
        print(f"{tier:5} {se['n']:>5} {sr['n']:>5} "
              f"{(se['median'] or 0):>8.4f} {(sr['median'] or 0):>8.4f} "
              f"{(delta if delta is not None else 0):>+10.4f} "
              f"{(mwu_p if mwu_p is not None else float('nan')):>9.2e}  "
              f"{(sne['median'] or 0):>7.4f} {(snr['median'] or 0):>7.4f}")
    json.dump(out, open(OUT, "w"), indent=2)
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
