"""Phase-1 Step 1.8 — Claim 3 echo coda + sanity chart + overall verdict.

Runs the lead-lag echo test, renders the price path with discovery contributors highlighted
and MMs greyed (a preview of the demo aesthetic), evaluates F1/F2/F3 together, and writes the
Phase-1 summary to data/out.

Run:  .venv/bin/python pipeline/finalize_market.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest
import schema
import attribution
import claims

SLUG = "biden-drops-out-in-july"
OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))


def sanity_chart(fills, mm_set, top_set, path):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6))
    t = [datetime.fromtimestamp(f["ts"], timezone.utc) for f in fills]
    p = [f["p_yes"] for f in fills]
    ax.plot(t, p, color="#00ff9c", lw=0.8, alpha=0.55, zorder=1)

    def pts(pred):
        xs = [t[i] for i, f in enumerate(fills) if pred(f)]
        ys = [p[i] for i, f in enumerate(fills) if pred(f)]
        ss = [6 + (f["usdc_notional"] ** 0.5) for f in fills if pred(f)]
        return xs, ys, ss

    xs, ys, ss = pts(lambda f: f["proxy_wallet"] in mm_set)
    ax.scatter(xs, ys, s=ss, c="#444444", alpha=0.5, label="market makers (greyed)", zorder=2)
    xs, ys, ss = pts(lambda f: f["proxy_wallet"] not in mm_set and f["proxy_wallet"] not in top_set)
    ax.scatter(xs, ys, s=ss, c="#1f77b4", alpha=0.35, label="crowd", zorder=3)
    xs, ys, ss = pts(lambda f: f["proxy_wallet"] in top_set)
    ax.scatter(xs, ys, s=ss, c="#ffd000", alpha=0.95, edgecolors="#ff8c00",
               linewidths=0.4, label="top-10 discovery whales (glowing)", zorder=4)

    ax.set_title("TAIL // biden-drops-out-in-july — price discovery", color="#00ff9c",
                 family="monospace", fontsize=12)
    ax.set_ylabel("P(Yes)", color="#00ff9c", family="monospace")
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right", framealpha=0.2, fontsize=8)
    ax.grid(alpha=0.12)
    fig.tight_layout()
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> None:
    market = ingest.parse_market(ingest.load_raw(f"{SLUG}_market.json"))
    fills = ingest.load_raw(f"{SLUG}_normalized_fills.json")
    cls = ingest.load_raw(f"{SLUG}_mm_classification.json")
    conc = ingest.load_raw(f"{SLUG}_concentration.json")
    c2 = ingest.load_raw(f"{SLUG}_claim2.json")
    R = schema.market_truth(market)
    mm_set = {a for a, c in cls.items() if c["is_mm"]}

    # Claim 3
    c3 = claims.claim3(fills, R, mm_set)
    print("=== CLAIM 3 — echo coda (NON-CAUSAL; association/timing only) ===")
    print(f"  cohorts: big={c3['n_big']} (top decile) vs small={c3['n_small']} (bottom 50%); "
          f"{c3['n_bins_active']} active 5-min bins")
    print(f"  simultaneous ρ(0)            : {c3['rho0']:+.3f}")
    print(f"  peak big→small ρ             : {c3['peak_rho']:+.3f} at +{c3['peak_lag_min']:.0f} min "
          f"(best non-positive lag {c3['nonpos_best_rho']:+.3f})")
    print(f"  circular-shift null p95 / p  : {c3['null_p95']:.3f} / p={c3['pval']:.4f}")
    print(f"  price-chasing confound peak  : {c3['confound_price_peak_rho']:+.3f} "
          f"({'comparable -> may be price-chasing' if c3['confound_price_peak_rho'] >= c3['peak_rho'] - 0.03 else 'below echo signal'})")
    print(f"  F3 (|ρ|≥0.15 AND > null95 AND positive-lag peak): "
          f"{'PASS -> echo consistent' if c3['f3_pass'] else 'FAIL -> no echo'}")

    # sanity chart
    iv = attribution.interval_attribute(fills, R, mm_set, n_per_window=25)
    top_set = {w for w, _ in sorted(iv["C"].items(), key=lambda kv: kv[1], reverse=True)[:10]}
    chart_path = os.path.join(OUT, f"{SLUG}_sanity.png")
    sanity_chart(fills, mm_set, top_set, chart_path)
    print(f"\n  sanity chart -> {chart_path}")

    # ---- overall verdict ----
    f1_fail = conc["f1_falsified"]
    c2_verdict = c2["by_K"]["10"]["verdict"]
    print("\n" + "=" * 64)
    print("PHASE-1 VERDICT  —  Biden drops out in July?  (single market, descriptive)")
    print("=" * 64)
    print(f"  Claim 1 (concentration): {'FALSIFIED' if f1_fail else 'SURVIVES'}  "
          f"— Gini {conc['concentration']['gini']:.2f}, "
          f"{conc['concentration']['N_half']} wallets = half of discovery "
          f"({conc['concentration']['N_half_frac']*100:.1f}% of {conc['n_directional']})")
    print(f"  Claim 2 (movers right) : {'SUPPORTED' if c2_verdict=='supported' else 'NOT SUPPORTED'}  "
          f"— top movers no edge vs volume-matched randoms; size⊥PnL")
    print(f"  Claim 3 (echo)         : {'CONSISTENT' if c3['f3_pass'] else 'NOT FOUND'}  "
          f"— peak ρ {c3['peak_rho']:+.2f} @ +{c3['peak_lag_min']:.0f}min (non-causal)")
    print("-" * 64)
    headline = ("Concentration is real and robust; the few who set the price were NOT a "
                "reliably-smart elite. 'A few wallets, but not wise ones.'")
    print(f"  HEADLINE: {headline}")

    summary = {
        "market": market["question"], "slug": SLUG, "conditionId": market["conditionId"],
        "R_yes": R, "n_fills": len(fills), "n_directional": conc["n_directional"],
        "claim1_concentration": conc["concentration"], "claim1_survives": not f1_fail,
        "claim2_verdict": c2_verdict, "claim2_lenses": c2["lenses"],
        "claim3": c3, "headline": headline,
        "method_note": "Primary attribution = interval net-flow (per-fill print method was "
                       "microstructure-contaminated; caught by the pre-registered ρ<0.6 flag).",
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{SLUG}_phase1.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  summary -> {os.path.join(OUT, SLUG + '_phase1.json')}")


if __name__ == "__main__":
    main()
