"""Validity check (F1') — does the 0.60 Gini floor DISCRIMINATE, or does any heavy-tailed market clear it?

The worry: "a few wallets dominate price impact" might be a tautology of heavy-tailed trading. To test
it we break the only thing the thesis claims — the link between wallet IDENTITY and price-move credit —
while preserving everything mechanical (the price path, the per-fill sizes/directions, the per-wallet
fill counts, the MM set, the attribution method). For each market we PERMUTE the non-MM wallet labels
across fills and recompute the interval-attributed Gini. If the real Gini >> the permuted Gini, the
concentration reflects that SPECIFIC wallets persistently take net positions that move price (the
thesis); if real ~= permuted, the concentration is mechanical and 0.60 does not discriminate.

Also reports, per market, the Gini of gross NOTIONAL across the same directional wallets (the
"is it just money?" comparison): impact concentration >> volume concentration would mean the movers are
more concentrated than the dollars.

Cached-only; event/headline. P permutations per market, fixed seed (deterministic). A baseline guard
asserts the real interval Gini reproduces the cached concentration_interval.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

import attribution
import f1_riders as fr

P = 5                       # permutations per market
SEED = 20260610
N_PRIMARY = 25
FLOOR = 0.60
OUT = os.path.join("data", "out", "corpus_null_concentration.json")


def _vol_gini(fills, mm_set):
    gn = {}
    for f in fills:
        w = f["proxy_wallet"]
        if w in mm_set:
            continue
        gn[w] = gn.get(w, 0.0) + f.get("usdc_notional", 0.0)
    return attribution.gini(gn.values())


def _perm_gini(fills, R, mm_set, n_dir, rng):
    idx = [i for i, f in enumerate(fills) if f["proxy_wallet"] not in mm_set]
    labels = [fills[i]["proxy_wallet"] for i in idx]
    order = rng.permutation(len(labels))
    pf = [dict(f) for f in fills]
    for j, i in enumerate(idx):
        pf[i]["proxy_wallet"] = labels[order[j]]
    ia = attribution.interval_attribute(pf, R, mm_set, n_per_window=N_PRIMARY, offset=0)
    return attribution.concentration(ia["C"], n_dir)["gini"]


def main(cls="event"):
    rows = fr._load(fr.MANIFEST)["rows"]
    markets = fr._markets_union()
    slugs = [s for s, r in rows.items() if r.get("status") == "ok" and r.get("cls") == cls]
    rng = np.random.default_rng(SEED)

    real_g, perm_g, vol_g = [], [], []
    by_tier = {t: {"real": [], "perm": []} for t in ("T1", "T2", "T3", "T4")}
    real_pass, perm_pass = 0, 0
    real_gt_perm = 0
    guard_fail = 0
    n = 0
    t0 = time.time()
    print(f"=== F1' null-concentration check ({cls}, P={P} perms) ===", flush=True)
    for i, slug in enumerate(slugs, 1):
        market, result = markets.get(slug), fr._load(os.path.join(fr.RESULTS, f"{slug}.json"))
        if market is None:
            continue
        fills, R, wstats, breadth, aggr, vol = fr._ingredients(market, result)
        mm = fr._mm_set(wstats, vol, breadth, aggr, fr.FLAT_PRIMARY)
        n_dir = len(aggr - mm)
        rg = fr._conc(fills, R, mm, aggr, N_PRIMARY, 0)["gini"]
        cg = (result.get("concentration_interval") or {}).get("gini")
        if cg is not None and rg is not None and abs(rg - cg) > 1e-6:
            guard_fail += 1
        pg = [g for g in (_perm_gini(fills, R, mm, n_dir, rng) for _ in range(P)) if g is not None]
        if rg is None or not pg:
            continue
        mpg = float(np.mean(pg))
        vg = _vol_gini(fills, mm)
        real_g.append(rg); perm_g.append(mpg)
        tier = rows[slug].get("tier")
        if tier in by_tier:
            by_tier[tier]["real"].append(rg); by_tier[tier]["perm"].append(mpg)
        if vg is not None:
            vol_g.append(vg)
        real_pass += rg >= FLOOR
        perm_pass += mpg >= FLOOR
        real_gt_perm += rg > mpg
        n += 1
        if i == 1 or i % 200 == 0 or i == len(slugs):
            print(f"  {i:4d}/{len(slugs)}  real_med={np.median(real_g):.3f}  "
                  f"perm_med={np.median(perm_g):.3f}  guard_fail={guard_fail}  "
                  f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)

    def med(x):
        return float(np.median(x)) if x else None

    out = {"cls": cls, "n": n, "permutations_each": P, "guard_fail": guard_fail,
           "real_median_gini": med(real_g), "perm_median_gini": med(perm_g),
           "volume_median_gini": med(vol_g),
           "real_frac_pass_0.60": real_pass / n, "perm_frac_pass_0.60": perm_pass / n,
           "frac_real_gt_perm": real_gt_perm / n,
           "real_p10": float(np.percentile(real_g, 10)), "real_p90": float(np.percentile(real_g, 90)),
           "perm_p10": float(np.percentile(perm_g, 10)), "perm_p90": float(np.percentile(perm_g, 90)),
           "by_tier": {t: {"n": len(d["real"]), "real_median": med(d["real"]),
                           "perm_median": med(d["perm"])} for t, d in by_tier.items()}}
    json.dump(out, open(OUT if cls == "event" else OUT.replace(".json", f"_{cls}.json"), "w"), indent=2)

    print(f"\n--- F1' NULL-CONCENTRATION ({cls}) ---")
    print(f"  guard failures: {guard_fail}/{n}")
    print(f"  median Gini: REAL {out['real_median_gini']:.4f}  vs  PERMUTED {out['perm_median_gini']:.4f}"
          f"  (volume-Gini {out['volume_median_gini']:.4f})")
    print(f"  frac >= 0.60: REAL {out['real_frac_pass_0.60']*100:.1f}%  vs  PERMUTED "
          f"{out['perm_frac_pass_0.60']*100:.1f}%")
    print(f"  frac real > permuted (per market): {out['frac_real_gt_perm']*100:.1f}%")
    print("  by tier (real vs permuted median Gini):")
    for t in ("T1", "T2", "T3", "T4"):
        bt = out["by_tier"][t]
        if bt["n"]:
            print(f"    {t}: n={bt['n']:>4}  real {bt['real_median']:.4f}  perm {bt['perm_median']:.4f}"
                  f"  Δ {bt['real_median']-bt['perm_median']:+.4f}")
    print(f"-> {OUT if cls=='event' else OUT.replace('.json', f'_{cls}.json')}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main(sys.argv[1] if len(sys.argv) > 1 else "event")
