"""Market-maker filter — the make-or-break step (Phase 1, Step 1.5).

Three-signal classifier separating market makers (plumbing) from informed directional takers,
per the frozen design in FALSIFICATION.md:
  A  inventory flatness  : |net_shares|/gross_shares < THRESH, above a volume floor
  B  cross-market breadth: active in many markets, tiny share here
  C  native role         : aggressor_share < 0.20 (only when role coverage >= 0.70)
Remove a wallet if >=2 signals fire, OR a single unmistakable flat+top-decile signal.
Over-removal is conservative for Claim 1 (it can only LOWER measured concentration).
"""
from __future__ import annotations

import numpy as np

FLATNESS_THRESH = 0.15
BANDS = (0.10, 0.15, 0.20)
AGGRESSOR_MM_MAX = 0.20
BREADTH_MIN = 30
BREADTH_THIS_SHARE_MAX = 0.05


def mm_min_notional(volume_num: float) -> float:
    """Frozen floor: max($5k, 0.5% of market volume)."""
    return max(5000.0, 0.005 * float(volume_num or 0))


def classify(wstats: dict, volume_num: float, breadth_map: dict,
             flatness_thresh: float = FLATNESS_THRESH, role_coverage: float = 1.0) -> tuple[dict, dict]:
    floor = mm_min_notional(volume_num)
    gn = [w["gross_notional"] for w in wstats.values() if w["gross_notional"] > 0]
    top_decile = float(np.percentile(gn, 90)) if gn else 0.0
    use_role = role_coverage >= 0.70

    out: dict[str, dict] = {}
    for addr, w in wstats.items():
        fl, gnv, ash = w["flatness"], w["gross_notional"], w["aggressor_share"]
        A = fl is not None and fl < flatness_thresh and gnv >= floor
        C = use_role and ash is not None and ash < AGGRESSOR_MM_MAX and gnv >= floor
        b = breadth_map.get(addr)
        B = bool(b and b["breadth"] >= BREADTH_MIN
                 and b.get("this_market_share") is not None
                 and b["this_market_share"] < BREADTH_THIS_SHARE_MAX)
        score = int(A) + int(B) + int(C)
        remove = score >= 2 or (score == 1 and fl is not None and fl < 0.05 and gnv >= top_decile)
        out[addr] = {"is_mm": remove, "score": score, "A_flat": A, "B_breadth": B, "C_role": C,
                     "flatness": fl, "aggressor_share": ash, "gross_notional": gnv,
                     "breadth": (b or {}).get("breadth"),
                     "this_market_share": (b or {}).get("this_market_share"),
                     "name": w["name"]}
    return out, {"floor": floor, "top_decile": top_decile, "use_role": use_role,
                 "flatness_thresh": flatness_thresh}


def diagnostics(wstats: dict, classification: dict) -> dict:
    """Validate the filter: MMs should be high GROSS volume but low NET directional flow."""
    mm = [a for a, c in classification.items() if c["is_mm"]]
    allw = list(wstats)
    g = lambda a: wstats[a]["gross_notional"]
    n = lambda a: abs(wstats[a]["net_shares"])
    tot_g, tot_n = sum(g(a) for a in allw) or 1, sum(n(a) for a in allw) or 1
    return {"n_mm": len(mm), "n_total": len(allw),
            "n_directional": len(allw) - len(mm),
            "mm_gross_share": sum(g(a) for a in mm) / tot_g,
            "mm_net_share": sum(n(a) for a in mm) / tot_n}


def flatness_histogram(wstats: dict, floor: float, bins: int = 20) -> list[tuple]:
    """Distribution of flatness among above-floor wallets (look for bimodality)."""
    vals = [w["flatness"] for w in wstats.values()
            if w["flatness"] is not None and w["gross_notional"] >= floor]
    if not vals:
        return []
    counts, edges = np.histogram(vals, bins=bins, range=(0.0, 1.0))
    return [(round(float(edges[i]), 2), int(counts[i])) for i in range(len(counts))]
