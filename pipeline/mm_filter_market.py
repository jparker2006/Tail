"""Phase-1 Step 1.5 — run the market-maker filter and validate it.

Probes cross-market breadth for above-floor wallets, classifies MMs via the frozen 3-signal
rule, runs validation diagnostics (gross-vs-net flow, flatness bimodality, top removed), and
checks robustness across flatness bands. Caches the classification.

Run:  .venv/bin/python pipeline/mm_filter_market.py
"""
from __future__ import annotations

import ingest
import mm_filter

SLUG = "biden-drops-out-in-july"
CONDITION_ID = "0xb124766234e1f19bc156a0edfb492f8c4cc3fa25303e722ad52780b66a3b70df"


def get_breadth(wstats: dict, floor: float) -> dict:
    """Breadth-probe every above-floor wallet, cached to data/raw."""
    cache = ingest.load_raw(f"{SLUG}_breadth.json") or {}
    above = [a for a, w in wstats.items() if w["gross_notional"] >= floor]
    todo = [a for a in above if a not in cache]
    if todo:
        print(f"  breadth-probing {len(todo)} above-floor wallets ({len(above)} total) ...")
        for i, addr in enumerate(todo):
            try:
                cache[addr] = ingest.breadth_probe(addr, CONDITION_ID)
            except Exception as e:  # noqa: BLE001
                cache[addr] = {"breadth": None, "this_market_share": None, "error": str(e)}
            if (i + 1) % 25 == 0:
                print(f"    ... {i+1}/{len(todo)}")
        ingest.save_raw(f"{SLUG}_breadth.json", cache)
    return cache


def main() -> None:
    market = ingest.parse_market(ingest.load_raw(f"{SLUG}_market.json"))
    wstats = ingest.load_raw(f"{SLUG}_wallet_stats.json")
    volume_num = float(market["volumeNum"])
    floor = mm_filter.mm_min_notional(volume_num)
    print(f"MM_MIN_NOTIONAL floor = ${floor:,.0f}  (0.5% of ${volume_num:,.0f} vol)")

    breadth = get_breadth(wstats, floor)

    cls, meta = mm_filter.classify(wstats, volume_num, breadth, role_coverage=1.0)
    diag = mm_filter.diagnostics(wstats, cls)
    ingest.save_raw(f"{SLUG}_mm_classification.json", cls)

    print(f"\n=== MM FILTER (primary, flatness<{meta['flatness_thresh']}) ===")
    print(f"  wallets total      : {diag['n_total']}")
    print(f"  classified MM      : {diag['n_mm']}")
    print(f"  directional universe: {diag['n_directional']}")
    print(f"  signals firing: A(flat)={sum(c['A_flat'] for c in cls.values())} "
          f"B(breadth)={sum(c['B_breadth'] for c in cls.values())} "
          f"C(role)={sum(c['C_role'] for c in cls.values())}")
    print(f"\n  VALIDATION (MMs should be HIGH gross, LOW net flow):")
    print(f"    MM share of gross notional : {100*diag['mm_gross_share']:.1f}%  (expect high)")
    print(f"    MM share of net directional: {100*diag['mm_net_share']:.1f}%  (expect low)")

    print(f"\n  flatness distribution among above-floor wallets (bimodality check):")
    for lo, ct in mm_filter.flatness_histogram(wstats, floor):
        print(f"    {lo:.2f}-{lo+0.05:.2f} | {'#'*ct} {ct}")

    print(f"\n  top 12 wallets removed as MM (by gross notional):")
    removed = sorted([(a, c) for a, c in cls.items() if c["is_mm"]],
                     key=lambda kv: kv[1]["gross_notional"], reverse=True)[:12]
    print(f"    {'wallet':>14} {'gross$':>11} {'flat':>6} {'aggr':>6} {'brdth':>6} {'thisSh':>7} sig  name")
    for a, c in removed:
        tms = f"{c['this_market_share']:.3f}" if c["this_market_share"] is not None else "  -  "
        sig = "".join(s for s, on in [("A", c["A_flat"]), ("B", c["B_breadth"]), ("C", c["C_role"])] if on)
        print(f"    {a[:12]+'..':>14} {c['gross_notional']:>11,.0f} {c['flatness']:>6.3f} "
              f"{(c['aggressor_share'] or 0):>6.3f} {str(c['breadth']):>6} {tms:>7} {sig:>3}  {c['name'] or ''}")

    print(f"\n  ROBUSTNESS across flatness bands:")
    for thr in mm_filter.BANDS:
        c2, _ = mm_filter.classify(wstats, volume_num, breadth, flatness_thresh=thr)
        d2 = mm_filter.diagnostics(wstats, c2)
        print(f"    flatness<{thr}: MM={d2['n_mm']:>3}  directional={d2['n_directional']:>4}  "
              f"MM_gross={100*d2['mm_gross_share']:.0f}%  MM_net={100*d2['mm_net_share']:.0f}%")


if __name__ == "__main__":
    main()
