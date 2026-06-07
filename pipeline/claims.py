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
        return {"mean": float(null.mean()), "p95": float(np.percentile(null, 95)),
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
        "beats_C": observed > c["p95"], "verdict": verdict, "rank_by": rank_by,
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
