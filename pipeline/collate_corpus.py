"""Collate per-market results into one corpus-wide DESCRIPTIVE summary (data cleanup, Step 2.6).

DESCRIPTIVE ONLY. Produces inventory + concentration (Claim-1) distributions from the already-
computed per-market stats in the run manifest. It does NOT evaluate the frozen F1'/F2'/F3' corpus
falsification thresholds, does NOT declare pass/fail, and draws no cross-market verdict — that is
Step 2.7, done with fresh eyes. Gini / N_half here are raw distributions, not a test result.

Output: data/out/corpus_collated.json + a printed summary.
"""
from __future__ import annotations

import json
import os
from collections import Counter

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
MANIFEST = os.path.join(OUT, "corpus_run_manifest.json")
GIANT_LEGS = 400_000


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _dist(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 4),
            "min": round(min(xs), 4), "p10": round(_pct(xs, .10), 4),
            "p25": round(_pct(xs, .25), 4), "median": round(_pct(xs, .50), 4),
            "p75": round(_pct(xs, .75), 4), "p90": round(_pct(xs, .90), 4),
            "max": round(max(xs), 4)}


def _hist(xs: list[float], edges: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    out = {}
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        out[f"[{lo:.2f},{hi:.2f})"] = sum(1 for x in xs if lo <= x < hi)
    out[f">={edges[-1]:.2f}"] = sum(1 for x in xs if x >= edges[-1])
    return out


def main() -> None:
    man = json.load(open(MANIFEST))
    rows = list(man["rows"].values())
    ok = [r for r in rows if r["status"] == "ok"]
    excl = [r for r in rows if r["status"] == "excluded"]

    # --- inventory ---
    inv = {"n_total": len(rows), "by_status": dict(Counter(r["status"] for r in rows)),
           "by_class_ok": dict(Counter(r.get("cls") for r in ok)),
           "by_tier_ok": dict(Counter(r.get("tier") for r in ok)),
           "n_detruncated_ok": sum(1 for r in ok if r.get("tape_source") == "subgraph")}

    # --- coverage gap, split by KIND (giants vs near-complete-gate vs other) ---
    def gap_kind(r):
        tq = r.get("trades_quantity") or 0
        reason = r.get("excluded_reason")
        if reason in ("giant_skip", "giant_timeout") or tq > GIANT_LEGS:
            return "giant"
        return "near_complete_or_other"   # gate-too-strict + the taker-count anomalies (for A6 review)
    corpus_vol = sum(r["vol"] for r in rows) or 1
    giants = [r for r in excl if gap_kind(r) == "giant"]
    pending = [r for r in excl if gap_kind(r) != "giant"]
    coverage = {
        "giants_legit_gap": {"n": len(giants),
                             "vol_share": round(sum(r["vol"] for r in giants) / corpus_vol, 4),
                             "markets": sorted([r["slug"] for r in giants])},
        "pending_a6_review": {"n": len(pending),
                              "vol_share": round(sum(r["vol"] for r in pending) / corpus_vol, 4),
                              "note": "tapes complete (tradesQuantity gap 2-8) or taker-count "
                                      "anomaly; excluded ONLY by the exact-equality gate. Awaiting "
                                      "the A6 tolerance-amendment decision. NOT a true coverage gap.",
                              "markets": sorted([r["slug"] for r in pending])}}

    # --- concentration (Claim 1) DESCRIPTIVE distributions (NO threshold test) ---
    def conc(subset):
        return {"gini": _dist([r.get("gini") for r in subset]),
                "gini_hist": _hist([r.get("gini") for r in subset if r.get("gini") is not None],
                                   [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]),
                "n_half_frac": _dist([r.get("n_half_frac") for r in subset]),
                "n_directional": _dist([r.get("n_directional") for r in subset])}
    by_cls = {c: conc([r for r in ok if r.get("cls") == c])
              for c in sorted({r.get("cls") for r in ok if r.get("cls")})}
    concentration = {"_descriptive_only": "raw distributions; F1' threshold test deferred to 2.7",
                     "all_ok": conc(ok), "by_class": by_cls}

    collated = {"inventory": inv, "coverage": coverage, "concentration_claim1": concentration}
    json.dump(collated, open(os.path.join(OUT, "corpus_collated.json"), "w"), indent=2)

    # --- printed summary ---
    print("=== CORPUS COLLATION (descriptive — no verdict) ===")
    print("inventory:", json.dumps(inv))
    print(f"\ncoverage: giants(legit gap)={coverage['giants_legit_gap']['n']} "
          f"(vol {coverage['giants_legit_gap']['vol_share']:.1%}) | "
          f"pending A6 review={coverage['pending_a6_review']['n']} "
          f"(vol {coverage['pending_a6_review']['vol_share']:.2%})")
    g = concentration["all_ok"]["gini"]
    print(f"\nClaim-1 Gini (all {g['n']} ok): median={g['median']} mean={g['mean']} "
          f"p10={g['p10']} p25={g['p25']} p75={g['p75']} p90={g['p90']} min={g['min']} max={g['max']}")
    print("Gini histogram:", json.dumps(concentration["all_ok"]["gini_hist"]))
    nh = concentration["all_ok"]["n_half_frac"]
    print(f"N_half_frac (all ok): median={nh['median']} mean={nh['mean']} p90={nh['p90']}")
    for c, cc in by_cls.items():
        print(f"  [{c}] n={cc['gini']['n']} gini median={cc['gini']['median']} "
              f"N_half_frac median={cc['n_half_frac']['median']}")
    print("\n-> data/out/corpus_collated.json")


if __name__ == "__main__":
    main()
