"""Claim tests and falsification evaluation (Phase 1, Steps 1.7–1.8).

Step 1.7 (this module, claim2): are the top movers RIGHT, and is it skill or size?
  - Top movers selected RESOLUTION-BLIND by net aggressive directional size |Σ d·size|.
  - Edge = realized hold-to-resolution PnL  Σ d·size·(R_yes − p_yes)  (handles round-trips).
  - Null A: randomize each fill's direction at the market base rate.
  - Null B: volume-matched random wallets (the smart-vs-rich test) — the decisive one.
  - Null C: shuffle fill timing, re-price at the prevailing price.
See FALSIFICATION.md. Single-market => p-values are within-market descriptive only.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def wallet_pnls(fills: list[dict], R: int, mm_set: set) -> dict:
    """Per non-MM-aggressor: realized PnL, net directional size, gross volume."""
    agg: dict[str, dict] = defaultdict(
        lambda: {"pnl": 0.0, "net": 0.0, "gross_notional": 0.0, "n": 0, "name": None})
    for f in fills:
        w = f["proxy_wallet"]
        if w in mm_set:
            continue
        a = agg[w]
        a["pnl"] += f["d"] * f["size"] * (R - f["p_yes"])
        a["net"] += f["d"] * f["size"]
        a["gross_notional"] += f["usdc_notional"]
        a["n"] += 1
        if f["wallet_name"] and not a["name"]:
            a["name"] = f["wallet_name"]
    return dict(agg)


def claim2(fills: list[dict], R: int, mm_set: set, K: int = 10, B: int = 10000,
           seed: int = 12345, rank_by: str = "net") -> dict:
    agg = wallet_pnls(fills, R, mm_set)
    wallets = list(agg)
    keyf = ((lambda w: agg[w]["gross_notional"]) if rank_by == "gross"
            else (lambda w: abs(agg[w]["net"])))           # both resolution-blind
    ranked = sorted(wallets, key=keyf, reverse=True)
    topK = ranked[:K]
    topset = set(topK)
    observed = sum(agg[w]["pnl"] for w in topK)

    # top-K fills, for nulls A and C
    d, size, pyes = [], [], []
    for f in fills:
        if f["proxy_wallet"] in topset:
            d.append(f["d"]); size.append(f["size"]); pyes.append(f["p_yes"])
    d, size, pyes = np.array(d), np.array(size), np.array(pyes)
    base_contrib = size * (R - pyes)

    rng = np.random.default_rng(seed)
    nonmm = [f for f in fills if f["proxy_wallet"] not in mm_set]
    base_rate = float(np.mean([1.0 if f["d"] > 0 else 0.0 for f in nonmm]))  # P(buy Yes)
    allp = np.array([f["p_yes"] for f in nonmm])

    # Null A — random direction at the market base rate
    rand_sign = np.where(rng.random((B, len(d))) < base_rate, 1.0, -1.0)
    nullA = (rand_sign * base_contrib).sum(axis=1)

    # Null C — reprice each fill at a randomly-sampled prevailing price (timing shuffle)
    randp = rng.choice(allp, size=(B, len(d)))
    nullC = ((d * size) * (R - randp)).sum(axis=1)

    # Null B — volume-matched random wallets (smart vs rich)
    gn = np.array([agg[w]["gross_notional"] for w in wallets])
    rank = np.argsort(np.argsort(gn))
    decile = np.minimum((rank * 10) // max(len(wallets), 1), 9)
    w_decile = {wallets[i]: int(decile[i]) for i in range(len(wallets))}
    pool_by_dec = {}
    for dd in range(10):
        vals = [agg[w]["pnl"] for w in wallets if w_decile[w] == dd]
        if vals:
            pool_by_dec[dd] = np.array(vals)
    all_pnl = np.array([agg[w]["pnl"] for w in wallets])
    nullB = np.zeros(B)
    for w in topK:
        pool = pool_by_dec.get(w_decile[w], all_pnl)
        nullB += rng.choice(pool, size=B)

    def summ(null):
        return {"mean": float(null.mean()), "p05": float(np.percentile(null, 5)),
                "p95": float(np.percentile(null, 95)),
                "pval": float((null >= observed).mean())}

    a, b, c = summ(nullA), summ(nullB), summ(nullC)
    verdict = ("supported" if observed > b["p95"]
               else "rich-not-smart" if observed > a["p95"]
               else "not-supported")
    return {
        "K": K, "observed_pnl": observed, "base_rate_buy": base_rate,
        "top_movers": [{"wallet": w, "name": agg[w]["name"], "pnl": agg[w]["pnl"],
                        "net_size": agg[w]["net"], "gross_notional": agg[w]["gross_notional"],
                        "decile": w_decile[w]} for w in topK],
        "nullA": a, "nullB": b, "nullC": c,
        "beats_A": observed > a["p95"], "beats_B": observed > b["p95"],
        "beats_C": observed > c["p95"],
        # CORPUS_PREREG F2' anti-wisdom descriptive add (NOT a kill gate): top-K systematically
        # WRONG = observed PnL below Null B's 5th pct (the symmetric lower tail of the rich null).
        "underperforms_B": bool(observed < b["p05"]),
        "verdict": verdict, "rank_by": rank_by,
    }


def claim2_lenses(fills: list[dict], R: int, mm_set: set, K: int = 10) -> dict:
    """Non-circular complementary views of Claim 2."""
    from scipy.stats import spearmanr
    agg = wallet_pnls(fills, R, mm_set)
    wallets = list(agg)
    sign = 1 if R == 1 else -1
    gross = np.array([agg[w]["gross_notional"] for w in wallets])
    netabs = np.array([abs(agg[w]["net"]) for w in wallets])
    pnl = np.array([agg[w]["pnl"] for w in wallets])
    rho_gross = float(spearmanr(gross, pnl).statistic)
    rho_net = float(spearmanr(netabs, pnl).statistic)

    def breakdown(keyf):
        top = sorted(wallets, key=keyf, reverse=True)[:K]
        pos = [agg[w]["pnl"] for w in top if agg[w]["pnl"] > 0]
        neg = [agg[w]["pnl"] for w in top if agg[w]["pnl"] < 0]
        gtot = sum(agg[w]["gross_notional"] for w in top)
        net_truth = sign * sum(agg[w]["net"] for w in top)  # >0 = leaned toward truth
        return {"n_right": len(pos), "n_wrong": len(neg),
                "sum_pos": sum(pos), "sum_neg": sum(neg),
                "net_toward_truth": net_truth,
                "net_toward_truth_frac": (net_truth / gtot) if gtot else None}

    return {"rho_gross_vs_pnl": rho_gross, "rho_netsize_vs_pnl": rho_net,
            "by_net": breakdown(lambda w: abs(agg[w]["net"])),
            "by_gross": breakdown(lambda w: agg[w]["gross_notional"])}


def lagged_xcorr(a: np.ndarray, b: np.ndarray, L: int) -> dict:
    """ρ(τ) = corr(a[t], b[t+τ]); τ>0 means a leads b."""
    az = (a - a.mean()) / (a.std() + 1e-12)
    bz = (b - b.mean()) / (b.std() + 1e-12)
    n = len(az)
    out = {}
    for tau in range(-L, L + 1):
        if abs(tau) >= n:                  # lag exceeds available bins -> no overlap (ρ undefined)
            out[tau] = 0.0                 # (guards against az[:n-tau] negative-index wraparound)
            continue
        x, y = (az[:n - tau], bz[tau:]) if tau >= 0 else (az[-tau:], bz[:n + tau])
        out[tau] = float(np.mean(x * y)) if len(x) > 1 else 0.0
    return out


def claim3(fills: list[dict], R: int, mm_set: set, bin_s: int = 300,
           max_lag_bins: int = 12, B: int = 5000, seed: int = 7) -> dict:
    """Echo coda: do small wallets trade same-direction shortly AFTER big wallets?

    Non-causal. Big = top-decile gross, small = bottom-50%. Lagged cross-correlation of
    big->small net flow, circular-shift null band, plus a price-chasing confound probe.
    """
    nonmm = [f for f in fills if f["proxy_wallet"] not in mm_set]
    gn: dict[str, float] = defaultdict(float)
    for f in nonmm:
        gn[f["proxy_wallet"]] += f["usdc_notional"]
    ranked = sorted(gn, key=gn.get)
    n = len(ranked)
    big = set(ranked[int(0.9 * n):])          # top decile by gross
    small = set(ranked[:int(0.5 * n)])         # bottom half

    ts = [f["ts"] for f in nonmm]
    t0 = min(ts)
    nb = (max(ts) - t0) // bin_s + 1
    big_flow = np.zeros(nb)
    small_flow = np.zeros(nb)
    last_p = np.full(nb, np.nan)
    fbins = []
    for f in nonmm:
        b = (f["ts"] - t0) // bin_s
        fbins.append(b)
        sn = f["d"] * f["usdc_notional"]       # token-0 directional (not truth-signed)
        if f["proxy_wallet"] in big:
            big_flow[b] += sn
        elif f["proxy_wallet"] in small:
            small_flow[b] += sn
        last_p[b] = f["p_yes"]
    # carry price forward; trim to the active window (0.5–99.5 pct of fills)
    cur = last_p[0] if not np.isnan(last_p[0]) else 0.0
    for i in range(nb):
        if np.isnan(last_p[i]):
            last_p[i] = cur
        else:
            cur = last_p[i]
    lo, hi = int(np.percentile(fbins, 0.5)), int(np.percentile(fbins, 99.5))
    bf, sf, pp = big_flow[lo:hi + 1], small_flow[lo:hi + 1], last_p[lo:hi + 1]
    dprice = np.diff(pp, prepend=pp[0])

    L = max_lag_bins
    m = len(sf)
    if m < 2 * L + 3:        # too few active bins for a lead-lag + valid circular-shift null window
        return {"bin_s": bin_s, "n_bins_active": int(m), "n_big": len(big), "n_small": len(small),
                "peak_rho": None, "peak_lag_bins": None, "peak_lag_min": None,
                "nonpos_best_rho": None, "null_p95": None, "pval": None,
                "confound_price_peak_rho": None, "rho0": None, "f3_pass": False,
                "status": "insufficient_bins"}

    rhos = lagged_xcorr(bf, sf, max_lag_bins)
    peak_tau = max(range(1, L + 1), key=lambda t: rhos[t])
    peak = rhos[peak_tau]
    nonpos_best = max(rhos[t] for t in range(-L, 1))

    # circular-shift null on small flow
    rng = np.random.default_rng(seed)
    m = len(sf)
    null_peaks = []
    for _ in range(B):
        k = int(rng.integers(L + 1, m - L - 1))
        rr = lagged_xcorr(bf, np.roll(sf, k), L)
        null_peaks.append(max(rr[t] for t in range(1, L + 1)))
    null_peaks = np.array(null_peaks)
    p95 = float(np.percentile(null_peaks, 95))
    pval = float((null_peaks >= peak).mean())
    fpr_gate = max(0.15, p95)
    fpr_m = float((null_peaks >= fpr_gate).mean())

    # price-chasing confound: does small flow follow PRICE as much as big-wallet flow?
    conf = lagged_xcorr(dprice, sf, max_lag_bins)
    conf_peak = max(conf[t] for t in range(1, L + 1))

    f3 = (peak >= 0.15) and (peak > p95) and (peak > nonpos_best)
    return {"bin_s": bin_s, "n_bins_active": int(m), "n_big": len(big), "n_small": len(small),
            "rho_curve": {str(k): v for k, v in rhos.items()},
            "peak_rho": peak, "peak_lag_bins": peak_tau, "peak_lag_min": peak_tau * bin_s / 60,
            "nonpos_best_rho": nonpos_best, "null_p95": p95, "pval": pval,
            "fpr_m": fpr_m, "fpr_gate": fpr_gate,
            "confound_price_peak_rho": conf_peak, "rho0": rhos[0],
            "f3_pass": bool(f3)}
