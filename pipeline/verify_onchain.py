"""Phase-1 Step 1.3 — verify the on-chain role-join and decide the data source.

Validates (on a representative sample first, then the full tape) that:
  - we can decode our market's fill out of each tx receipt,
  - the on-chain aggressor (OrdersMatched.takerOrderMaker) matches the Data API taker
    proxyWallet  -> confirms the takerOnly tape gives us the aggressor identity,
  - the on-chain execution price matches the tape price,
and reports role_coverage to choose hybrid (>=0.70) vs Data-API-only.

Run sample:  .venv/bin/python pipeline/verify_onchain.py
Run full:    .venv/bin/python pipeline/verify_onchain.py full
"""
from __future__ import annotations

import sys

import ingest
import onchain

SLUG = "biden-drops-out-in-july"
EXCHANGE = onchain.CTF_EXCHANGE_V1  # negRisk=False for this market


def main() -> None:
    tape = ingest.load_raw(f"{SLUG}_trades_taker.json")
    market = ingest.load_raw(f"{SLUG}_market.json")
    token_ids = ingest.parse_market(market)["clobTokenIds"]

    full = "full" in sys.argv
    if full:
        sel = tape
    else:
        n = 40
        step = max(1, len(tape) // n)
        sel = tape[::step][:n]  # spread across the whole timeline, not just the start

    print(f"resolving {len(sel)} receipts (full={full}) via rotating public Polygon RPCs ...")
    decoded = onchain.build_join(sel, token_ids, EXCHANGE, SLUG)

    ok = has_om = taker_match = price_close = asset_match = total = 0
    mismatches = []
    for r in sel:
        d = decoded.get(r["transactionHash"])
        if not d or not d.get("ok"):
            continue
        total += 1
        ok += 1
        if d.get("has_ordersmatched"):
            has_om += 1
        tmatch = d.get("taker") and d["taker"].lower() == r["proxyWallet"].lower()
        if tmatch:
            taker_match += 1
        elif len(mismatches) < 5:
            mismatches.append((r["transactionHash"][:12], d.get("taker"), r["proxyWallet"]))
        if d.get("price") is not None and abs(d["price"] - float(r["price"])) < 0.02:
            price_close += 1
        if d.get("asset_id") == r.get("asset"):
            asset_match += 1

    print(f"\n=== SAMPLE/JOIN VALIDATION (n_selected={len(sel)}, decoded_ok={ok}) ===")
    if total:
        print(f"  has OrdersMatched              : {has_om}/{total}")
        print(f"  on-chain aggressor == tape taker: {taker_match}/{total} "
              f"({100*taker_match/total:.1f}%)")
        print(f"  on-chain price ≈ tape price ±.02: {price_close}/{total}")
        print(f"  on-chain asset == tape asset    : {asset_match}/{total}")
        if mismatches:
            print("  sample taker mismatches (tx, onchain_taker, tape_proxy):")
            for m in mismatches:
                print(f"    {m}")

    if full:
        notional = lambda r: float(r.get("price", 0)) * float(r.get("size", 0))
        cov_fills = sum(1 for r in tape
                        if decoded.get(r["transactionHash"], {}).get("ok"))
        cov_notional = sum(notional(r) for r in tape
                           if decoded.get(r["transactionHash"], {}).get("ok"))
        tot_notional = sum(notional(r) for r in tape)
        match_fills = sum(
            1 for r in tape
            if (d := decoded.get(r["transactionHash"], {})).get("taker")
            and d["taker"].lower() == r["proxyWallet"].lower())
        print(f"\n=== ROLE COVERAGE (FULL TAPE) ===")
        print(f"  decoded ok        : {cov_fills}/{len(tape)} "
              f"({100*cov_fills/len(tape):.1f}% of fills, "
              f"{100*cov_notional/tot_notional:.1f}% of notional)")
        print(f"  aggressor matched : {match_fills}/{len(tape)} "
              f"({100*match_fills/len(tape):.1f}%)")
        decision = "HYBRID (use native role)" if cov_fills / len(tape) >= 0.70 \
            else "DATA-API-ONLY fallback (inventory+breadth)"
        print(f"  --> DECISION: {decision}")


if __name__ == "__main__":
    main()
