"""Validity check (F2') — do top movers have positive CENTRAL/mean edge, or only variance?

F2's kill criterion tests the UPPER tail (beat Null B's 95th pct more than 5% of the time). That is
consistent with either (a) positive expected edge or (b) zero expected edge + higher variance than
volume-matched wallets — and the fat underperform tail (top-K below Null B's 5th pct in ~30% of
markets) means (b) is at least partly real. This check isolates the CENTER.

For each market, claim2 cached Null B's mean and pval = P(nullB >= observed). The observed top-K PnL's
rank inside its own null is `1 - pval`. Under the no-central-edge null (movers ~ volume-matched
wallets), that rank is Uniform(0,1) -> median 0.5, and observed > nullB.mean in ~50% of markets. A
median rank > 0.5 (Wilcoxon) and frac-above-mean > 0.5 (binomial) is positive central edge; ~0.5 is
"variance, not skill." Cached-only; reports event and recurring.
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy.stats import binomtest, wilcoxon

MANIFEST = "data/out/corpus_run_manifest.json"
RESULTS = "data/raw/results"


def _rows(cls):
    man = json.load(open(MANIFEST))["rows"]
    out = []
    for slug, r in man.items():
        if r.get("status") != "ok" or r.get("cls") != cls:
            continue
        p = os.path.join(RESULTS, f"{slug}.json")
        if os.path.exists(p):
            out.append(json.load(open(p)))
    return out


def analyze(cls):
    rows = _rows(cls)
    ranks, above_mean, pvals = [], [], []
    for r in rows:
        c = r.get("claim2") or {}
        b = c.get("nullB") or {}
        obs, pv, mean = c.get("observed_pnl"), b.get("pval"), b.get("mean")
        if pv is None or obs is None or mean is None:
            continue
        ranks.append(1.0 - pv)                 # observed's percentile inside its own Null B
        pvals.append(pv)
        above_mean.append(obs > mean)
    n = len(ranks)
    ranks = np.array(ranks)
    nb_above = int(np.sum(above_mean))
    bt = binomtest(nb_above, n, 0.5, alternative="greater")
    # Wilcoxon signed-rank of (rank - 0.5) vs 0 (two-sided); positive median => central edge
    w = wilcoxon(ranks - 0.5, alternative="greater", zero_method="zsplit")
    return {"cls": cls, "n": n,
            "median_rank": float(np.median(ranks)),
            "mean_rank": float(np.mean(ranks)),
            "median_pval": float(np.median(pvals)),
            "frac_obs_above_nullB_mean": nb_above / n,
            "binom_p_above_mean_vs_0.5": float(bt.pvalue),
            "wilcoxon_p_rank_gt_0.5": float(w.pvalue)}


def main():
    print("=== F2' mean-edge check: positive central edge, or just variance? ===")
    print(f"{'cls':10} {'n':>5} {'med_rank':>9} {'mean_rank':>9} {'med_pval':>9} "
          f"{'>mean':>7} {'binom_p':>10} {'wilcox_p':>10}")
    out = {}
    for cls in ("event", "recurring"):
        a = analyze(cls)
        out[cls] = a
        print(f"{cls:10} {a['n']:>5} {a['median_rank']:>9.4f} {a['mean_rank']:>9.4f} "
              f"{a['median_pval']:>9.4f} {a['frac_obs_above_nullB_mean']*100:>6.1f}% "
              f"{a['binom_p_above_mean_vs_0.5']:>10.2e} {a['wilcoxon_p_rank_gt_0.5']:>10.2e}")
    json.dump(out, open("data/out/check_mean_edge.json", "w"), indent=2)
    print("\nInterpretation: median_rank/frac>mean near 0.50 => variance not central edge; "
          ">0.50 (sig) => positive expected edge.\n-> data/out/check_mean_edge.json")


if __name__ == "__main__":
    main()
