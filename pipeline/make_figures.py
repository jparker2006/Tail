"""Generate the four paper figures (PNG) from committed artifacts + result caches. Deterministic.

  Fig 1  one illustrative market: truth-signed price path + Lorenz curve of contributions (the hook)
  Fig 2  F1 — real vs identity-permuted median Gini, by tier (event)        [corpus_null_concentration]
  Fig 3  F2 — distribution of top-K PnL rank within own Null B (event)      [result caches: claim2 pval]
  Fig 4  F3 — echo pass-rate vs calibrated false-positive rate, event/rec.  [corpus_f3_calibration*]

Run: .venv/bin/python pipeline/make_figures.py  ->  paper/figures/fig{1..4}_*.png
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIGDIR = os.path.join("paper", "figures")
RESULTS = os.path.join("data", "raw", "results")
INK = "#1a1a1a"
ACCENT = "#b3202c"      # real / observed
MUTE = "#9aa0a6"        # null / permuted
plt.rcParams.update({"font.size": 10, "axes.edgecolor": INK, "axes.labelcolor": INK,
                     "text.color": INK, "xtick.color": INK, "ytick.color": INK,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})


def _load(p):
    return json.load(open(p))


def fig1_market():
    man = _load("data/out/corpus_run_manifest.json")["rows"]
    best = None
    for slug, row in man.items():
        if row.get("status") != "ok" or row.get("cls") != "event" or (row.get("gini") or 0) < 0.90:
            continue
        p = os.path.join(RESULTS, f"{slug}.json")
        if not os.path.exists(p):
            continue
        r = _load(p)
        pp = r.get("price_path") or []
        if len(pp) < 120:
            continue
        R = r.get("R_yes")
        ps = np.array([x[1] for x in pp])
        pstar = ps if R == 1 else 1.0 - ps          # truth-signed: rises toward realized outcome
        travel = float(pstar[-1] - np.median(pstar[:10]))
        if travel > 0.5:
            score = travel * (row.get("gini") or 0)
            if best is None or score > best[0]:
                best = (score, slug, r, pstar)
    _, slug, r, pstar = best
    ci = r["concentration_interval"]
    lz = np.array(ci["lorenz"])
    ts = np.array([x[0] for x in r["price_path"]], float)
    t = (ts - ts[0]) / max(ts[-1] - ts[0], 1)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.0, 3.5))
    ax1.plot(t, pstar, color=ACCENT, lw=1.6)
    ax1.set_ylim(-0.02, 1.02)
    ax1.set_xlabel("market lifetime (normalized)")
    ax1.set_ylabel("truth-signed price  $p^*$")
    ax1.set_title("(a) price discovers the outcome", fontsize=10)
    ax1.axhline(1.0, color=MUTE, lw=0.8, ls=":")

    ax2.plot([0, 1], [0, 1], color=MUTE, lw=0.9, ls="--", label="equality")
    ax2.plot(lz[:, 0], lz[:, 1], color=ACCENT, lw=1.8, label="contributions")
    ax2.fill_between(lz[:, 0], lz[:, 1], lz[:, 0], color=ACCENT, alpha=0.10)
    ax2.set_xlim(0, 1); ax2.set_ylim(0, 1)
    ax2.set_xlabel("cumulative share of directional wallets")
    ax2.set_ylabel("cumulative share of price discovery")
    ax2.set_title(f"(b) Lorenz curve (Gini = {ci['gini']:.2f})", fontsize=10)
    ax2.legend(frameon=False, loc="upper left", fontsize=8)
    fig.suptitle(f"Figure 1.  An illustrative market — {slug[:48]}", fontsize=10, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGDIR, "fig1_market.png"), bbox_inches="tight")
    plt.close(fig)
    return slug


def fig2_null_by_tier():
    d = _load("data/out/corpus_null_concentration.json")["by_tier"]
    tiers = ["T1", "T2", "T3", "T4"]
    real = [d[t]["real_median"] for t in tiers]
    perm = [d[t]["perm_median"] for t in tiers]
    x = np.arange(len(tiers)); w = 0.38
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.bar(x - w / 2, real, w, color=ACCENT, label="real")
    ax.bar(x + w / 2, perm, w, color=MUTE, label="identity-permuted null")
    for i, (rr, pp) in enumerate(zip(real, perm)):
        ax.annotate(f"+{rr-pp:.3f}", (i, max(rr, pp) + 0.012), ha="center", fontsize=8, color=INK)
    ax.axhline(0.60, color=INK, lw=0.8, ls=":")
    ax.text(3.42, 0.61, "F1 floor 0.60", fontsize=7.5, color=INK, ha="right")
    ax.set_xticks(x); ax.set_xticklabels(tiers)
    ax.set_ylim(0.5, 0.97)
    ax.set_ylabel("median Gini")
    ax.set_xlabel("volume tier (T1 smallest → T4 largest)")
    ax.set_title("Figure 2.  Concentration vs. an identity-permuted null, by tier", fontsize=10)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGDIR, "fig2_null_by_tier.png"), bbox_inches="tight")
    plt.close(fig)


def fig3_mover_rank():
    man = _load("data/out/corpus_run_manifest.json")["rows"]
    ranks = []
    for slug, row in man.items():
        if row.get("status") != "ok" or row.get("cls") != "event":
            continue
        p = os.path.join(RESULTS, f"{slug}.json")
        if not os.path.exists(p):
            continue
        c = (_load(p).get("claim2") or {}).get("nullB") or {}
        if c.get("pval") is not None:
            ranks.append(1.0 - c["pval"])         # observed top-K percentile within its own Null B
    ranks = np.array(ranks)
    med = float(np.median(ranks))
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.hist(ranks, bins=25, range=(0, 1), color=MUTE, edgecolor="white")
    ax.axvline(0.5, color=INK, lw=1.0, ls="--", label="no central edge (0.50)")
    ax.axvline(med, color=ACCENT, lw=1.6, label=f"median = {med:.3f}")
    ax.axvline(0.95, color="#444", lw=0.8, ls=":")
    ax.text(0.955, ax.get_ylim()[1] * 0.92, "beats-B gate (0.95)", rotation=90, va="top",
            fontsize=7, color="#444")
    ax.set_xlabel("rank of observed top-K PnL within its own volume-matched Null B")
    ax.set_ylabel("number of markets")
    ax.set_title("Figure 3.  The median mover underperforms its volume-matched null", fontsize=10)
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGDIR, "fig3_mover_rank.png"), bbox_inches="tight")
    plt.close(fig)


def fig4_echo():
    ev = _load("data/out/corpus_f3_calibration.json")
    rc = _load("data/out/corpus_f3_calibration_recurring.json")
    groups = ["event\n(belief)", "recurring\n(algorithmic)"]
    obs = [ev["frac_f3_pass"] * 100, rc["frac_f3_pass"] * 100]
    fpr = [ev["mean_calibrated_fpr"] * 100, rc["mean_calibrated_fpr"] * 100]
    x = np.arange(2); w = 0.38
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.bar(x - w / 2, obs, w, color=ACCENT, label="observed echo pass-rate")
    ax.bar(x + w / 2, fpr, w, color=MUTE, label="calibrated false-positive rate")
    for i, (o, f) in enumerate(zip(obs, fpr)):
        ax.annotate(f"{o:.1f}%", (i - w / 2, o + 0.3), ha="center", fontsize=8)
        ax.annotate(f"{f:.2f}%", (i + w / 2, f + 0.3), ha="center", fontsize=8, color="#555")
    ax.set_xticks(x); ax.set_xticklabels(groups)
    ax.set_ylabel("share of in-scope markets passing echo test (%)")
    ax.set_title("Figure 4.  Echo is rare behind beliefs, common behind algorithms", fontsize=10)
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGDIR, "fig4_echo.png"), bbox_inches="tight")
    plt.close(fig)


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    slug = fig1_market()
    fig2_null_by_tier()
    fig3_mover_rank()
    fig4_echo()
    print(f"wrote 4 figures to {FIGDIR}/  (Fig 1 market: {slug})")


if __name__ == "__main__":
    main()
