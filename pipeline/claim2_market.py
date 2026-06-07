"""Phase-1 Step 1.7 — "the movers are right" (Claim 2).

Runs the resolution-blind top-mover edge test with three nulls and the F2 verdict.

Run:  .venv/bin/python pipeline/claim2_market.py
"""
from __future__ import annotations

import ingest
import schema
import claims

SLUG = "biden-drops-out-in-july"


def show(res: dict) -> None:
    print(f"\n--- K={res['K']} top movers (selected resolution-blind by |net directional size|) ---")
    print(f"  observed aggregate PnL : ${res['observed_pnl']:,.0f}   "
          f"(market base rate P(buy Yes)={res['base_rate_buy']:.2f})")
    for tag in ("nullA", "nullB", "nullC"):
        n = res[tag]
        beat = res[{"nullA": "beats_A", "nullB": "beats_B", "nullC": "beats_C"}[tag]]
        label = {"nullA": "A random-direction", "nullB": "B volume-matched (smart-vs-rich)",
                 "nullC": "C timing-shuffle"}[tag]
        print(f"    Null {label:<34} mean ${n['mean']:>9,.0f}  p95 ${n['p95']:>9,.0f}  "
              f"p={n['pval']:.4f}  {'BEATS' if beat else 'no'}")
    print(f"  VERDICT: {res['verdict'].upper()}")
    print(f"  top movers (name | net size | gross$ | PnL | decile):")
    for m in res["top_movers"]:
        print(f"    {(m['name'] or m['wallet'][:12]):<28} net={m['net_size']:>+9.0f} "
              f"gross=${m['gross_notional']:>9,.0f} pnl=${m['pnl']:>+9,.0f} dec={m['decile']}")


def main() -> None:
    market = ingest.parse_market(ingest.load_raw(f"{SLUG}_market.json"))
    fills = ingest.load_raw(f"{SLUG}_normalized_fills.json")
    cls = ingest.load_raw(f"{SLUG}_mm_classification.json")
    R = schema.market_truth(market)
    mm_set = {a for a, c in cls.items() if c["is_mm"]}

    print("=== CLAIM 2 — are the top movers right? (single market => descriptive only) ===")
    out = {}
    for K in (5, 10, 20):
        res = claims.claim2(fills, R, mm_set, K=K)
        out[K] = res
        show(res)

    primary = out[10]
    print("\n=== F2 (kills Claim 2 if top-10 fail to beat Null B at 95th pct) ===")
    print(f"  observed ${primary['observed_pnl']:,.0f}  vs  Null-B p95 ${primary['nullB']['p95']:,.0f}")
    if primary["verdict"] == "supported":
        print("  --> Claim 2 SUPPORTED: movers beat volume-matched randoms (skill, not just size)")
    elif primary["verdict"] == "rich-not-smart":
        print("  --> Claim 2 PARTIAL: beat random-direction but NOT volume-matched -> RICH, NOT SMART")
    else:
        print("  --> Claim 2 NOT SUPPORTED on this market")

    ingest.save_raw(f"{SLUG}_claim2.json",
                    {k: {kk: vv for kk, vv in v.items() if kk != "top_movers"} | {"top_movers": v["top_movers"]}
                     for k, v in out.items()})


if __name__ == "__main__":
    main()
