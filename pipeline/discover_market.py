"""Phase-1 market discovery & liquidity assessment.

Enumerates candidate markets (here: Biden "drop out"), pulls the Phase-1 metadata, and
probes liquidity, so we can pick a market that is binary (negRisk==false), liquid enough for
the trade-tape price path to be a faithful discovery proxy, and that actually moved.

Reusable in Phase 2 (swap the gather step for the stratified corpus query).

Run:  .venv/bin/python pipeline/discover_market.py
"""
from __future__ import annotations

import json

import ingest


def gather_biden_candidates() -> list[dict]:
    seen: dict[str, dict] = {}

    def add(markets: list[dict], source: str):
        for m in markets:
            cid = m.get("conditionId")
            if not cid or cid in seen:
                continue
            pm = ingest.parse_market(m)
            pm["_source"] = source
            seen[cid] = pm

    # 1) The canonical multi-sub-market event (daily "will Biden drop out on <date>?").
    for slug in (
        "when-will-biden-drop-out",
        "will-biden-drop-out-before-the-lettuce-expires",
        "will-biden-drop-out-by-next-friday",
    ):
        try:
            for ev in ingest.gamma_events(slug=slug):
                add(ev.get("markets", []) or [], f"event:{slug}")
        except Exception as e:  # noqa: BLE001 — discovery is best-effort
            print(f"  (event {slug} failed: {e})")

    # 2) Full-text search for anything else Biden-withdrawal-shaped.
    try:
        res = ingest.gamma_search("biden drop out", limit_per_type=50)
        add(res.get("markets", []) or [], "search:markets")
        for ev in res.get("events", []) or []:
            add(ev.get("markets", []) or [], "search:event")
    except Exception as e:  # noqa: BLE001
        print(f"  (search failed: {e})")

    return list(seen.values())


def main() -> None:
    cands = gather_biden_candidates()
    # Keep resolved binary Yes/No markets.
    binary = [c for c in cands
              if c.get("closed") and len(c.get("outcomes") or []) == 2
              and c.get("resolved_outcome_index") is not None]
    binary.sort(key=lambda c: float(c.get("volumeNum") or 0), reverse=True)

    print(f"\n{len(cands)} candidates found; {len(binary)} resolved binary.\n")
    print(f"{'vol($)':>12}  {'negRisk':>7}  {'winner':>6}  question")
    print("-" * 100)
    for c in binary[:15]:
        win = (c["outcomes"][c["resolved_outcome_index"]]
               if c["resolved_outcome_index"] is not None else "?")
        vol = float(c.get("volumeNum") or 0)
        print(f"{vol:>12,.0f}  {str(c.get('negRisk')):>7}  {win:>6}  {c.get('question')}")

    # Probe liquidity for the top finalists (prefer binary == not negRisk).
    finalists = [c for c in binary if c.get("negRisk") is False][:5] or binary[:5]
    print("\n=== liquidity probe (top finalists) ===")
    for c in finalists:
        p = ingest.probe_liquidity(c["conditionId"])
        print(f"\n• {c.get('question')}")
        print(f"    slug={c.get('slug')}")
        print(f"    conditionId={c.get('conditionId')}")
        print(f"    clobTokenIds={c.get('clobTokenIds')}")
        print(f"    negRisk={c.get('negRisk')}  closed={c.get('closed')}  "
              f"uma={c.get('umaResolutionStatus')}")
        print(f"    outcomes={c.get('outcomes')}  outcomePrices={c.get('outcomePrices')}  "
              f"winner_idx={c.get('resolved_outcome_index')}")
        print(f"    volumeNum={c.get('volumeNum')}  liquidityNum={c.get('liquidityNum')}")
        print(f"    start={c.get('startDate')}  end={c.get('endDate')}")
        print(f"    PROBE: trades_page_n={p['trades_page_n']} (capped={p['trades_capped']})  "
              f"distinct_wallets_in_page={p['distinct_wallets_in_page']}")
        print(f"    PROBE: ts_min={p['ts_min']} ts_max={p['ts_max']}  "
              f"holders_by_token={p['holder_counts_by_token']}")


if __name__ == "__main__":
    main()
