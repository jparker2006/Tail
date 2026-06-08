"""Phase-2 Step 2.5 — on-chain validation subset.

Two jobs (A1.2 / A1.3):
  (a) validate the NegRisk-Exchange decoder: decode negRisk-market receipts and check prices
      land in [0,1] and match the /trades tape (gates whether negRisk role is trusted), and
  (b) compare the 2-signal (/trades) vs 3-signal (on-chain) MM filter on the downstream F1
      verdict across the 40 validation markets, applying the A4 escalation rule.

This module: decoder validation (gating). The 2-vs-3 comparison harness follows once the
decoder is confirmed.

Run:  .venv/bin/python pipeline/validate_onchain.py
"""
from __future__ import annotations

import json
import os
import statistics as st

import ingest
import onchain
from run_market import _tape

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))


def exchange_for(m: dict) -> str:
    return onchain.NEGRISK_EXCHANGE_V1 if m.get("negRisk") else onchain.CTF_EXCHANGE_V1


def validate_decoder(m: dict) -> dict:
    slug, cid = m["slug"], m["conditionId"]
    token_ids = m["clobTokenIds"]
    exch = exchange_for(m)
    taker_rows, _ = _tape(cid, slug, taker_only=True)
    join = onchain.build_join(taker_rows, token_ids, exch, slug)

    n = len(join)
    ok = [d for d in join.values() if d["ok"]]
    prices = [d["price"] for d in ok if d["price"] is not None]
    in01 = [p for p in prices if 0.0 <= p <= 1.0]
    has_om = sum(1 for d in ok if d["has_ordersmatched"])

    # price cross-check vs the tape, matched on (tx, asset)
    tape_px = {}
    for r in taker_rows:
        tape_px[(r["transactionHash"], str(r["asset"]))] = float(r["price"])
    diffs, taker_match, taker_tot = [], 0, 0
    tape_taker = {r["transactionHash"]: r["proxyWallet"].lower() for r in taker_rows}
    for tx, d in join.items():
        if not d["ok"] or d["price"] is None:
            continue
        tp = tape_px.get((tx, str(d["asset_id"])))
        if tp is not None:
            diffs.append(abs(d["price"] - tp))
        if d["taker"]:
            taker_tot += 1
            if d["taker"] == tape_taker.get(tx):
                taker_match += 1

    return {
        "slug": slug, "negRisk": bool(m.get("negRisk")), "tier": m.get("tier"),
        "exchange": exch, "n_tx": n, "n_decoded_ok": len(ok),
        "ok_rate": len(ok) / n if n else None,
        "price_in_01_rate": len(in01) / len(prices) if prices else None,
        "ordersmatched_rate": has_om / len(ok) if ok else None,
        "price_vs_tape_median_absdiff": st.median(diffs) if diffs else None,
        "price_vs_tape_p90_absdiff": (sorted(diffs)[int(0.9 * len(diffs))] if diffs else None),
        "taker_match_rate": taker_match / taker_tot if taker_tot else None,
    }


def main() -> None:
    val = json.load(open(os.path.join(OUT, "validation_subset.json")))["markets"]
    negrisk = sorted([m for m in val if m.get("negRisk")], key=lambda x: x["volumeNum"])
    target = negrisk[0]
    print(f"=== Step 2.5 — NegRisk decoder validation (gating) ===")
    print(f"  smallest negRisk validation market: {target['slug'][:54]}")
    print(f"  tier {target['tier']}, vol ${target['volumeNum']:,.0f}, "
          f"exchange {exchange_for(target)[:10]}…")
    r = validate_decoder(target)
    print(f"\n  txs {r['n_tx']}, decoded ok {r['n_decoded_ok']} ({(r['ok_rate'] or 0)*100:.0f}%)")
    print(f"  OrdersMatched present: {(r['ordersmatched_rate'] or 0)*100:.0f}% of decoded")
    print(f"  price in [0,1]      : {(r['price_in_01_rate'] or 0)*100:.0f}%")
    print(f"  price vs tape |Δ|   : median {r['price_vs_tape_median_absdiff']}, "
          f"p90 {r['price_vs_tape_p90_absdiff']}")
    print(f"  taker vs tape match : {(r['taker_match_rate'] or 0)*100:.0f}%")
    verdict = (r["ok_rate"] and r["ok_rate"] > 0.8 and r["price_in_01_rate"]
               and r["price_in_01_rate"] > 0.95
               and r["price_vs_tape_median_absdiff"] is not None
               and r["price_vs_tape_median_absdiff"] < 0.02)
    print(f"\n  NegRisk decoder: {'VALID' if verdict else 'NEEDS WORK / segregate (A1.3 fallback)'}")
    with open(os.path.join(OUT, "negrisk_decoder_validation.json"), "w") as f:
        json.dump(r, f, indent=2)


if __name__ == "__main__":
    main()
