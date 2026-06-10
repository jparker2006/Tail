"""Price-discovery attribution and concentration metrics (Phase 1, Step 1.6).

Primary method (frozen): reconstruct the executed token-0 price path; credit each fill's
truth-signed price move Δ*_t to its aggressor (makers get zero); C_w = Σ Δ*_t. Wrong-way
pushes are naturally negative. Conservation: Σ_all-aggressor C_w == p*_end − p*_0.

Crude cross-check: each wallet's net truth-signed notional (direction × dollars), which
ignores microstructure — high Spearman vs the primary means concentration isn't an artifact.

Concentration (Claim 1): Gini + Lorenz + top-N share + N_half over positive contributors,
within the directional aggressor universe (MMs removed). See FALSIFICATION.md.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.stats import spearmanr


def attribute(fills: list[dict], R: int, mm_set: set) -> dict:
    """Per-fill discovery decomposition. fills must be time-sorted.

    Returns C (non-MM aggressor contributions), the crude net-notional, and bookkeeping for
    conservation (total travel, MM-aggressor share, maker share=0 by construction).
    """
    sign = 1 if R == 1 else -1
    C: dict[str, float] = defaultdict(float)        # primary: price-move credit
    crude: dict[str, float] = defaultdict(float)    # cross-check: net truth-signed notional
    total = 0.0
    mm_contrib = 0.0
    prev = None
    for f in fills:
        p = f["p_yes"]
        dstar = 0.0 if prev is None else (p - prev) * sign
        prev = p
        total += dstar
        w = f["proxy_wallet"]
        if w in mm_set:
            mm_contrib += dstar
            continue
        C[w] += dstar
        crude[w] += f["d_star"] * f["usdc_notional"]
    return {"C": dict(C), "crude": dict(crude), "total_travel": total,
            "mm_aggressor_contrib": mm_contrib}


def interval_attribute(fills: list[dict], R: int, mm_set: set, n_per_window: int = 25,
                       offset: int = 0) -> dict:
    """Interval net-flow attribution (robust primary).

    Group fills into per-N blocks. Each block's truth-signed price move Δ* is split among the
    non-MM aggressors whose NET flow pushed in the move's direction, pro-rata by net flow. A
    flat bot's buys/sells cancel within a block (~0 net), so it absorbs ~no credit — which is
    exactly what fixes the per-fill print artifact. Moves with no aligned non-MM flow (e.g.
    bot/maker-driven prints) fall to an explicit `unexplained` bucket.

    `offset` (CORPUS_PREREG §1.5 phase-offset robustness sweep): shift where the window grid
    starts by `offset` fills, so the first block is the partial [0:offset) and full N-blocks
    follow. `offset=0` is the single-grid PRIMARY and is bit-identical to the original loop
    (block starts unchanged); the sweep never replaces the primary, it only probes it.
    """
    from collections import defaultdict
    pstar = lambda p: p if R == 1 else 1.0 - p
    C: dict[str, float] = defaultdict(float)
    attributed = 0.0
    unexplained = 0.0
    prev = pstar(fills[0]["p_yes"])
    if offset and 0 < offset < len(fills):
        starts = [0] + list(range(offset, len(fills), n_per_window))
    else:
        starts = list(range(0, len(fills), n_per_window))
    for j, i in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(fills)
        block = fills[i:end]
        cur = pstar(block[-1]["p_yes"])
        dstar = cur - prev
        prev = cur
        nf: dict[str, float] = defaultdict(float)
        for f in block:
            w = f["proxy_wallet"]
            if w in mm_set:
                continue
            nf[w] += f["d_star"] * f["size"]          # truth-signed net shares
        if dstar > 0:
            contrib = {w: v for w, v in nf.items() if v > 0}
        elif dstar < 0:
            contrib = {w: v for w, v in nf.items() if v < 0}
        else:
            contrib = {}
        s = sum(contrib.values())
        if contrib and s != 0:
            for w, v in contrib.items():
                C[w] += dstar * (v / s)
            attributed += dstar
        else:
            unexplained += dstar
    return {"C": dict(C), "attributed": attributed, "unexplained": unexplained,
            "n_per_window": n_per_window}


def gini(values) -> float | None:
    xs = sorted(x for x in values if x > 0)
    n = len(xs)
    s = sum(xs)
    if n == 0 or s == 0:
        return None
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * s) - (n + 1) / n


def lorenz(values) -> list[list]:
    xs = sorted(x for x in values if x > 0)
    s = sum(xs)
    if not xs or s == 0:
        return [[0.0, 0.0], [1.0, 1.0]]
    pts = [[0.0, 0.0]]
    c = 0.0
    for i, x in enumerate(xs):
        c += x
        pts.append([(i + 1) / len(xs), c / s])
    return pts


def concentration(C: dict, n_directional: int) -> dict:
    """Gini/Lorenz/top-N/N_half over positive contributors; fraction vs the directional universe."""
    pos = sorted((v for v in C.values() if v > 0), reverse=True)
    total_pos = sum(pos)
    n_pos = len(pos)
    n_neg = sum(1 for v in C.values() if v < 0)

    def top_share(k):
        return sum(pos[:k]) / total_pos if total_pos > 0 and pos else None

    n_half = None
    if total_pos > 0:
        c = 0.0
        for i, v in enumerate(pos):
            c += v
            if c >= 0.5 * total_pos:
                n_half = i + 1
                break
    return {
        "n_directional": n_directional,
        "n_positive": n_pos,
        "n_negative": n_neg,
        "gini": gini(C.values()),
        "lorenz": lorenz(C.values()),
        "top1_share": top_share(1),
        "top5_share": top_share(5),
        "top10_share": top_share(10),
        "N_half": n_half,
        "N_half_frac": (n_half / n_directional) if (n_half and n_directional) else None,
    }


def crosscheck(C: dict, crude: dict) -> dict:
    keys = [w for w in C if w in crude]
    if len(keys) < 3:
        return {"spearman": None, "n": len(keys)}
    rho, _ = spearmanr([C[w] for w in keys], [crude[w] for w in keys])
    return {"spearman": float(rho), "n": len(keys)}
