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

import sys

import ingest
import onchain
import schema
import mm_filter
import attribution
from run_market import _tape, _market_for_truth, build_flatness_stats, N_WINDOW

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


def _breadth_map(wstats, aggressors, vol, cid, slug):
    floor = mm_filter.mm_min_notional(vol)
    bm = {}
    for w, s in wstats.items():
        if s["gross_notional"] >= floor and w in aggressors:
            bname = f"breadth_{w[:10]}_{slug}.json"
            b = ingest.load_raw(bname)
            if b is None:
                b = ingest.breadth_probe(w, cid)
                ingest.save_raw(bname, b)
            bm[w] = b
    return bm


def f1_survives(conc):
    g, nf = conc.get("gini"), conc.get("N_half_frac")
    if g is None or nf is None:
        return None
    return bool(g >= 0.60 and nf <= 0.05)


def compare_market(m: dict) -> dict:
    """2-signal (/trades) vs 3-signal (on-chain) MM filter on the SAME aggressor fills."""
    slug, cid = m["slug"], m["conditionId"]
    vol = float(m.get("volumeNum") or 0)
    market = _market_for_truth(m)
    taker_rows, t_meta = _tape(cid, slug, taker_only=True)
    full_rows, _ = _tape(cid, slug, taker_only=False)
    fills, R = schema.normalize_fills(taker_rows, {}, market)
    aggressors = {f["proxy_wallet"] for f in fills}
    base = {"slug": slug, "tier": m.get("tier"), "negRisk": bool(m.get("negRisk")),
            "n_fills": len(fills), "n_aggressors": len(aggressors),
            "trades_truncated": bool(t_meta.get("truncated"))}

    # 2-signal MM set (flatness from maker-inclusive tape + breadth)
    full_fills, _ = schema.normalize_fills(full_rows, {}, market)
    wstats2 = build_flatness_stats(full_fills)
    bm = _breadth_map(wstats2, aggressors, vol, cid, slug)
    cls2, _ = mm_filter.classify(wstats2, vol, bm, role_coverage=0.0)
    mm2 = {w for w, c in cls2.items() if c["is_mm"]} & aggressors

    # 3-signal MM set (on-chain role: maker legs + aggressor_share, signal C)
    join = onchain.build_join(taker_rows, m["clobTokenIds"], exchange_for(m), slug)
    fills_oc, _ = schema.normalize_fills(taker_rows, join, market)
    wstats3 = schema.wallet_stats(fills_oc)
    covered = sum(1 for f in fills if join.get(f["tx_hash"], {}).get("ok")
                  and join[f["tx_hash"]].get("has_ordersmatched"))
    role_cov = covered / len(fills) if fills else 0.0
    bm3 = _breadth_map(wstats3, aggressors, vol, cid, slug)
    cls3, _ = mm_filter.classify(wstats3, vol, bm3, role_coverage=role_cov)
    mm3 = {w for w, c in cls3.items() if c["is_mm"]} & aggressors

    # attribution under each MM set (same fills) -> downstream F1 verdict
    nd2, nd3 = len(aggressors - mm2), len(aggressors - mm3)
    c2 = attribution.concentration(attribution.interval_attribute(fills, R, mm2, N_WINDOW)["C"], nd2)
    c3 = attribution.concentration(attribution.interval_attribute(fills, R, mm3, N_WINDOW)["C"], nd3)
    v2, v3 = f1_survives(c2), f1_survives(c3)
    thin = nd2 < 30 or nd3 < 30
    base.update({"role_coverage": round(role_cov, 3), "n_mm_2": len(mm2), "n_mm_3": len(mm3),
                 "n_directional_2": nd2, "n_directional_3": nd3,
                 "gini_2": c2["gini"], "gini_3": c3["gini"],
                 "dgini": (abs(c2["gini"] - c3["gini"]) if c2["gini"] and c3["gini"] else None),
                 "nhalf_frac_2": c2["N_half_frac"], "nhalf_frac_3": c3["N_half_frac"],
                 "verdict_2": v2, "verdict_3": v3,
                 "flip": (v2 != v3) if (v2 is not None and v3 is not None) else None,
                 "thin": thin})
    return base


def compare_all(markets: list[dict]) -> dict:
    rows = []
    for i, m in enumerate(markets, 1):
        print(f"  [{i}/{len(markets)}] {m['tier']} {m['slug'][:48]} "
              f"(vol ${m['volumeNum']:,.0f}, negRisk {bool(m.get('negRisk'))})", flush=True)
        try:
            r = compare_market(m)
        except Exception as e:  # noqa: BLE001
            print(f"      ERROR {e}", flush=True)
            r = {"slug": m["slug"], "tier": m["tier"], "error": str(e)}
        rows.append(r)
        if "gini_2" in r:
            print(f"      role_cov {r['role_coverage']} | MM 2/3 {r['n_mm_2']}/{r['n_mm_3']} | "
                  f"Gini {r['gini_2']}/{r['gini_3']} (Δ{r['dgini']}) | "
                  f"verdict {r['verdict_2']}/{r['verdict_3']} {'FLIP' if r.get('flip') else ''}",
                  flush=True)

    valid = [r for r in rows if r.get("flip") is not None and not r.get("thin")]
    flips = [r for r in valid if r["flip"]]
    t4 = [r for r in valid if r["tier"] == "T4"]
    t4_flips = [r for r in t4 if r["flip"]]
    dg = [r["dgini"] for r in valid if r["dgini"] is not None]
    flip_rate = len(flips) / len(valid) if valid else None
    med_dg = (sorted(dg)[len(dg) // 2] if dg else None)
    escalate = bool((flip_rate is not None and flip_rate > 0.15)
                    or (med_dg is not None and med_dg > 0.05) or t4_flips)
    summary = {"n": len(rows), "n_valid": len(valid), "n_flips": len(flips),
               "flip_rate": flip_rate, "median_dgini": med_dg,
               "t4_n": len(t4), "t4_flips": len(t4_flips),
               "escalate": escalate, "rows": rows}
    print("\n=== A4 escalation gate ===")
    print(f"  valid markets {len(valid)}/{len(rows)} | verdict flips {len(flips)} "
          f"(rate {flip_rate}) | median |ΔGini| {med_dg}")
    print(f"  T4: {len(t4_flips)}/{len(t4)} flipped")
    print(f"  --> {'ESCALATE (T4-first)' if escalate else 'NO ESCALATION — 2-signal filter validated'}")
    with open(os.path.join(OUT, "validation_2v3.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("  saved -> data/out/validation_2v3.json")
    return summary


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    val = json.load(open(os.path.join(OUT, "validation_subset.json")))["markets"]
    if mode == "compare":
        order = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}     # cheapest tiers first
        compare_all(sorted(val, key=lambda m: (order.get(m["tier"], 9), m["volumeNum"])))
        return
    if mode == "compare-test":
        small = sorted([m for m in val if m["tier"] in ("T1", "T2")],
                       key=lambda m: m["volumeNum"])[:2]
        compare_all(small)
        return
    # mode == "decoder"
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
