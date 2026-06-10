"""Step 2.7 — corpus-level falsification verdict (F1'/F2'/F3').

Aggregates the per-market result caches into the population tests frozen in CORPUS_PREREG.md §3.
Applies ONLY pre-registered thresholds; chooses none. Headline = the EVENT/primary corpus
(recurring is a separate within-type contrast, never pooled — A2.4). All `ok` markets already
cleared the n_directional >= 30 analyzability floor (§5); thin/excluded are not here.

F1' (load-bearing): median Gini and median N_half/n_directional across the corpus, under BOTH
  interval (primary) and per-fill methods. Claim 1 DIES iff the death condition (median Gini < 0.60
  OR median N_half/n > 0.05) holds under BOTH methods; survives-clean iff both methods pass; if they
  disagree it is method-dependent and §1.3 (interval rationale leads) governs. Method-disagreement
  fraction reported. Flatness/window/offset riders are a separate recompute pass (flagged).
F2': fraction of markets whose top-K (K=10) movers beat Null B at the 95th pct, vs the 5%-by-chance
  baseline (one-sided binomial). Smart iff sig>5% under Null B; rich-not-smart iff sig>Null A but not
  B; else no edge.
F3': among in-scope Claim-3 markets (status ok AND n_bins_active >= M=48), fraction with f3_pass
  (peak rho>=0.15 AND >own null p95 AND positive-lag-beats-nonpositive). Benchmarked vs the
  calibrated per-market FPR (mean of FPR_m = P_null(peak >= max(0.15, null_p95))) when the
  per-market claim3 cache includes fpr_m; reports both mean-FPR binomial and Poisson-binomial
  tails. Thin markets in a separate denom.
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy.stats import binomtest

MANIFEST = "data/out/corpus_run_manifest.json"
RESULTS = "data/raw/results"
M_ECHO = 48                      # frozen co-active-bins floor (CORPUS_PREREG §2, M = 4L)
GINI_FLOOR, NHF_CEIL = 0.60, 0.05


def _load_ok():
    man = json.load(open(MANIFEST))
    out = []
    for slug, row in man["rows"].items():
        if row.get("status") != "ok":
            continue
        p = os.path.join(RESULTS, f"{slug}.json")
        if os.path.exists(p):
            out.append(json.load(open(p)))
    return out


def _dist(xs):
    a = np.array([x for x in xs if x is not None], float)
    return {"n": int(a.size), "median": float(np.median(a)), "mean": float(a.mean()),
            "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75)),
            "p10": float(np.percentile(a, 10)), "p90": float(np.percentile(a, 90))}


def _per_market_f1(c):
    """Per-market F1: survives iff Gini >= 0.60 AND N_half/n <= 0.05."""
    if not c or c.get("gini") is None or c.get("N_half_frac") is None:
        return None
    return c["gini"] >= GINI_FLOOR and c["N_half_frac"] <= NHF_CEIL


def f1_prime(rows, label):
    gi = [r["concentration_interval"].get("gini") for r in rows if r.get("concentration_interval")]
    gp = [r["concentration_perfill"].get("gini") for r in rows if r.get("concentration_perfill")]
    ni = [r["concentration_interval"].get("N_half_frac") for r in rows if r.get("concentration_interval")]
    npf = [r["concentration_perfill"].get("N_half_frac") for r in rows if r.get("concentration_perfill")]
    nhalf_i = [r["concentration_interval"].get("N_half") for r in rows if r.get("concentration_interval")]
    di, dp = _dist(gi), _dist(gp)
    ndi, ndp = _dist(ni), _dist(npf)
    death_interval = di["median"] < GINI_FLOOR or ndi["median"] > NHF_CEIL
    death_perfill = dp["median"] < GINI_FLOOR or ndp["median"] > NHF_CEIL
    # method disagreement on the per-market F1 verdict
    disagree = same = 0
    for r in rows:
        a, b = _per_market_f1(r.get("concentration_interval")), _per_market_f1(r.get("concentration_perfill"))
        if a is None or b is None:
            continue
        if a == b:
            same += 1
        else:
            disagree += 1
    verdict = ("FALSIFIED (both methods)" if death_interval and death_perfill
               else "SURVIVES (both methods)" if not death_interval and not death_perfill
               else "METHOD-DEPENDENT — interval rationale leads (§1.3)")
    return {"label": label, "n": len(rows),
            "gini_interval": di, "gini_perfill": dp,
            "nhalf_frac_interval": ndi, "nhalf_frac_perfill": ndp,
            "median_N_half_interval": float(np.median([x for x in nhalf_i if x is not None])),
            "death_interval": death_interval, "death_perfill": death_perfill,
            "per_market_disagree_frac": disagree / max(same + disagree, 1),
            "verdict": verdict}


def f2_prime(rows, label):
    cs = [r.get("claim2") for r in rows if r.get("claim2")]
    valid = [c for c in cs if c.get("beats_B") is not None]
    n = len(valid)
    nb = sum(1 for c in valid if c["beats_B"])
    na = sum(1 for c in valid if c.get("beats_A"))
    frac_b, frac_a = nb / n, na / n
    bt_b = binomtest(nb, n, 0.05, alternative="greater")
    bt_a = binomtest(na, n, 0.05, alternative="greater")
    vd = {"supported": 0, "rich-not-smart": 0, "not-supported": 0}
    for c in valid:
        vd[c.get("verdict", "not-supported")] = vd.get(c.get("verdict", "not-supported"), 0) + 1
    sig_b = bt_b.pvalue < 0.05 and frac_b > 0.05
    sig_a = bt_a.pvalue < 0.05 and frac_a > 0.05
    edge = ("SMART (beats Null B above chance)" if sig_b
            else "RICH-NOT-SMART (beats Null A not B)" if sig_a
            else "NO EDGE")
    return {"label": label, "n": n, "frac_beats_B": frac_b, "n_beats_B": nb,
            "binom_p_vs_5pct_B": bt_b.pvalue, "frac_beats_A": frac_a,
            "binom_p_vs_5pct_A": bt_a.pvalue, "verdict_counts": vd, "edge": edge}


def poisson_binom_sf(probs, k):
    """P[X >= k] for independent, non-identical Bernoulli probabilities."""
    if k <= 0:
        return 1.0
    ps = np.array([p for p in probs if p is not None], float)
    n = int(ps.size)
    if k > n:
        return 0.0
    dp = np.zeros(n + 1)
    dp[0] = 1.0
    for i, p in enumerate(ps, start=1):
        dp[1:i + 1] = dp[1:i + 1] * (1.0 - p) + dp[:i] * p
        dp[0] *= 1.0 - p
    return float(dp[k:].sum())


def f3_prime(rows, label):
    cs = [r.get("claim3") for r in rows if r.get("claim3")]
    inscope = [c for c in cs if c.get("peak_rho") is not None and c.get("n_bins_active", 0) >= M_ECHO]
    excluded = len(cs) - len(inscope)
    n = len(inscope)
    npass = sum(1 for c in inscope if c.get("f3_pass"))
    frac = npass / n if n else 0.0
    bt = binomtest(npass, n, 0.05, alternative="greater") if n else None
    fprs = [c.get("fpr_m") for c in inscope if c.get("fpr_m") is not None]
    if len(fprs) == n and n:
        mean_fpr = float(np.mean(fprs))
        expected = float(np.sum(fprs))
        bt_cal = binomtest(npass, n, mean_fpr, alternative="greater")
        pb_p = poisson_binom_sf(fprs, npass)
        verdict = ("ABOVE CALIBRATED NULL" if frac > mean_fpr and pb_p < 0.05
                   else "NOT ABOVE CALIBRATED NULL")
        note = "calibrated FPR from each market's circular-shift null distribution"
    else:
        mean_fpr = expected = bt_cal = pb_p = verdict = None
        note = f"missing fpr_m for {n - len(fprs)} in-scope markets; rerun claim3 FPR recompute"
    return {"label": label, "n_inscope": n, "n_excluded_thin": excluded,
            "n_f3_pass": npass, "frac_f3_pass": frac,
            "binom_p_vs_flat5pct": (bt.pvalue if bt else None),
            "mean_calibrated_fpr": mean_fpr,
            "expected_passes_calibrated": expected,
            "binom_p_vs_calibrated_fpr": (bt_cal.pvalue if bt_cal else None),
            "poisson_binom_p_vs_calibrated_fpr": pb_p,
            "verdict": verdict,
            "note": note}


def gini_boundary_check(rows):
    """Result-check #1: is Gini stable right at the n_directional >= 30 floor?"""
    near = [r["concentration_interval"]["gini"] for r in rows
            if r.get("concentration_interval") and 30 <= r.get("n_directional", 0) <= 50]
    rest = [r["concentration_interval"]["gini"] for r in rows
            if r.get("concentration_interval") and r.get("n_directional", 0) > 50]
    return {"near_floor_30_50": _dist(near), "above_50": _dist(rest)}


def main():
    rows = _load_ok()
    event = [r for r in rows if r.get("mkt_class") == "event"]
    recurring = [r for r in rows if r.get("mkt_class") == "recurring"]
    out = {"n_ok_total": len(rows), "n_event": len(event), "n_recurring": len(recurring),
           "F1prime_event": f1_prime(event, "event/headline"),
           "F1prime_recurring": f1_prime(recurring, "recurring/contrast"),
           "F2prime_event": f2_prime(event, "event/headline"),
           "F2prime_recurring": f2_prime(recurring, "recurring/contrast"),
           "F3prime_event": f3_prime(event, "event/headline"),
           "F3prime_recurring": f3_prime(recurring, "recurring/contrast"),
           "result_check_gini_boundary": gini_boundary_check(event)}
    json.dump(out, open("data/out/corpus_verdict.json", "w"), indent=2)

    def banner(t):
        print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)

    banner(f"CORPUS VERDICT — F1'/F2'/F3'  (event headline n={len(event)}, recurring n={len(recurring)})")
    f1 = out["F1prime_event"]
    print("\n--- F1' CONCENTRATION (load-bearing) — EVENT HEADLINE ---")
    print(f"  Gini      interval: median {f1['gini_interval']['median']:.4f}  "
          f"IQR [{f1['gini_interval']['p25']:.4f}, {f1['gini_interval']['p75']:.4f}]")
    print(f"  Gini      per-fill: median {f1['gini_perfill']['median']:.4f}  "
          f"IQR [{f1['gini_perfill']['p25']:.4f}, {f1['gini_perfill']['p75']:.4f}]")
    print(f"  N_half/n  interval: median {f1['nhalf_frac_interval']['median']:.4f}   "
          f"per-fill: median {f1['nhalf_frac_perfill']['median']:.4f}   (floor: Gini>=0.60, N_half/n<=0.05)")
    print(f"  population: in the median event market, N_half = {f1['median_N_half_interval']:.0f} "
          f"wallets accounted for half of all price discovery (interval)")
    print(f"  per-market method disagreement: {f1['per_market_disagree_frac']*100:.1f}%")
    print(f"  >>> F1' {f1['verdict']}")

    f2 = out["F2prime_event"]
    print("\n--- F2' MOVERS' EDGE — EVENT HEADLINE ---")
    print(f"  beats Null B (K=10): {f2['n_beats_B']}/{f2['n']} = {f2['frac_beats_B']*100:.1f}%   "
          f"binom p vs 5%: {f2['binom_p_vs_5pct_B']:.2e}")
    print(f"  beats Null A:        {f2['frac_beats_A']*100:.1f}%   binom p vs 5%: {f2['binom_p_vs_5pct_A']:.2e}")
    print(f"  per-market verdicts: {f2['verdict_counts']}")
    print(f"  >>> F2' edge: {f2['edge']}")

    f3 = out["F3prime_event"]
    print("\n--- F3' ECHO — EVENT HEADLINE ---")
    print(f"  in-scope (co-active >= {M_ECHO} bins): {f3['n_inscope']}   excluded-thin: {f3['n_excluded_thin']}")
    print(f"  f3_pass: {f3['n_f3_pass']}/{f3['n_inscope']} = {f3['frac_f3_pass']*100:.1f}%   "
          f"binom p vs flat-5%: {f3['binom_p_vs_flat5pct']:.2e}")
    if f3["mean_calibrated_fpr"] is not None:
        print(f"  calibrated expected: {f3['expected_passes_calibrated']:.1f}/"
              f"{f3['n_inscope']} = {f3['mean_calibrated_fpr']*100:.2f}%   "
              f"poisson-binomial p: {f3['poisson_binom_p_vs_calibrated_fpr']:.2e}")
        print(f"  >>> F3' {f3['verdict']}")
    print(f"  {f3['note']}")

    print("\n--- recurring contrast (NOT headline) ---")
    rf1 = out["F1prime_recurring"]
    print(f"  F1' Gini interval median {rf1['gini_interval']['median']:.4f} ({rf1['verdict']})")
    print(f"  F2' beats-B {out['F2prime_recurring']['frac_beats_B']*100:.1f}%  "
          f"F3' pass {out['F3prime_recurring']['frac_f3_pass']*100:.1f}% "
          f"of {out['F3prime_recurring']['n_inscope']} in-scope")

    gb = out["result_check_gini_boundary"]
    print(f"\n--- result-check: Gini boundary stability (event) ---")
    print(f"  n_dir 30-50: median {gb['near_floor_30_50']['median']:.4f} (n={gb['near_floor_30_50']['n']})  "
          f"| n_dir>50: median {gb['above_50']['median']:.4f} (n={gb['above_50']['n']})")
    print("\n-> data/out/corpus_verdict.json")


if __name__ == "__main__":
    main()
