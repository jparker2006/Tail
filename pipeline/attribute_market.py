"""Phase-1 Step 1.6 — attribution + concentration (Claim 1).

Primary = interval net-flow (robust to the per-fill print artifact the gut-check exposed).
Reports per-fill and crude alongside for transparency, the F1 verdict on the primary, and
robustness across window size and MM-filter bands.

Run:  .venv/bin/python pipeline/attribute_market.py
"""
from __future__ import annotations

import ingest
import schema
import mm_filter
import attribution

SLUG = "biden-drops-out-in-july"
N_WINDOW = 25


def conc_line(tag, conc, gini_first=True):
    return (f"  {tag:<22} Gini {conc['gini']:.3f} | top1/5/10 "
            f"{conc['top1_share']*100:4.1f}/{conc['top5_share']*100:4.1f}/{conc['top10_share']*100:4.1f}% | "
            f"N_half {conc['N_half']} ({conc['N_half_frac']*100:.2f}%)")


def f1_verdict(conc):
    gini_fail = conc["gini"] is not None and conc["gini"] < 0.60
    frac_fail = conc["N_half_frac"] is not None and conc["N_half_frac"] > 0.05
    return (gini_fail or frac_fail), gini_fail, frac_fail


def main() -> None:
    market = ingest.parse_market(ingest.load_raw(f"{SLUG}_market.json"))
    fills = ingest.load_raw(f"{SLUG}_normalized_fills.json")
    cls = ingest.load_raw(f"{SLUG}_mm_classification.json")
    R = schema.market_truth(market)
    mm_set = {a for a, c in cls.items() if c["is_mm"]}
    aggressors = {f["proxy_wallet"] for f in fills}
    n_directional = len(aggressors - mm_set)

    # --- three attributions ---
    iv = attribution.interval_attribute(fills, R, mm_set, n_per_window=N_WINDOW)
    pf = attribution.attribute(fills, R, mm_set)
    iv_conc = attribution.concentration(iv["C"], n_directional)
    pf_conc = attribution.concentration(pf["C"], n_directional)
    cr_conc = attribution.concentration(pf["crude"], n_directional)
    iv_cc = attribution.crosscheck(iv["C"], pf["crude"])

    print("=== ATTRIBUTION METHODS (directional universe = "
          f"{n_directional} non-MM aggressors) ===")
    print(conc_line("INTERVAL (primary)", iv_conc))
    print(conc_line("per-fill print", pf_conc))
    print(conc_line("crude net-notional", cr_conc))
    print(f"\n  interval attributed {iv['attributed']:+.4f} of {iv['attributed']+iv['unexplained']:+.4f} "
          f"travel; unexplained {iv['unexplained']:+.4f} "
          f"({100*iv['unexplained']/(iv['attributed']+iv['unexplained']):.0f}% bot/maker-driven)")
    print(f"  interval-vs-crude Spearman ρ = {iv_cc['spearman']:.3f}  "
          f"(was 0.47 for per-fill; higher = robust)")

    fail, gfail, ffail = f1_verdict(iv_conc)
    print("\n=== F1 (kills Claim 1 if Gini<0.60 OR N_half/n>0.05) — on INTERVAL primary ===")
    print(f"  Gini {iv_conc['gini']:.3f} ({'FAIL <0.60' if gfail else 'ok >=0.60'}) ; "
          f"N_half_frac {iv_conc['N_half_frac']*100:.2f}% ({'FAIL >5%' if ffail else 'ok <=5%'})")
    print(f"  --> Claim 1 {'FALSIFIED' if fail else 'SURVIVES'} on this market")

    print("\n=== ROBUSTNESS ===")
    print("  window size N (interval):")
    for n in (10, 25, 50, 100):
        c = attribution.concentration(
            attribution.interval_attribute(fills, R, mm_set, n_per_window=n)["C"], n_directional)
        print(f"    N={n:>3}: Gini {c['gini']:.3f}  N_half {c['N_half']} ({c['N_half_frac']*100:.2f}%)")
    print("  MM-filter flatness band (interval, N=25):")
    vol = float(market["volumeNum"])
    breadth = ingest.load_raw(f"{SLUG}_breadth.json") or {}
    wstats = ingest.load_raw(f"{SLUG}_wallet_stats.json")
    for thr in mm_filter.BANDS:
        c2, _ = mm_filter.classify(wstats, vol, breadth, flatness_thresh=thr)
        mm2 = {a for a, cc in c2.items() if cc["is_mm"]}
        nd2 = len(aggressors - mm2)
        c = attribution.concentration(
            attribution.interval_attribute(fills, R, mm2, n_per_window=N_WINDOW)["C"], nd2)
        print(f"    flatness<{thr}: Gini {c['gini']:.3f}  N_half {c['N_half']} ({c['N_half_frac']*100:.2f}%)")

    # save primary
    out = {"market": market["question"], "slug": SLUG, "R_yes": R,
           "n_directional": n_directional,
           "primary": "interval_netflow", "n_per_window": N_WINDOW,
           "concentration": iv_conc, "interval_meta": {k: iv[k] for k in ("attributed", "unexplained")},
           "methods": {"interval": iv_conc, "per_fill": pf_conc, "crude": cr_conc},
           "interval_vs_crude_spearman": iv_cc["spearman"],
           "f1_falsified": fail}
    ingest.save_raw(f"{SLUG}_concentration.json", out)

    print("\n  top 10 contributors (interval C_w):")
    wn = {f["proxy_wallet"]: f["wallet_name"] for f in fills}
    tot = sum(v for v in iv["C"].values() if v > 0)
    for a, v in sorted(iv["C"].items(), key=lambda kv: kv[1], reverse=True)[:10]:
        print(f"    {a[:12]+'..':>14}  C={v:+.4f} ({v/tot*100:4.1f}%)  {wn.get(a) or ''}")


if __name__ == "__main__":
    main()
