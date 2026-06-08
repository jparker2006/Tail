"""Phase-2 Step 2.1 — corpus discovery (read-only; no selection, no outcomes).

Enumerates the V1 candidate universe from Gamma and characterizes the volume distribution so
the absolute floor + volume-tier boundaries (CORPUS_PREREG.md §5, amendment A1.4) can be set
from the real data BEFORE any market outcome is computed.

Candidate = CLOB (`enableOrderBook == True`, A1.1) ∧ binary (2 outcomes) ∧ resolved (a side
paid 1). Gamma caps offset at ~10k, so the universe is sliced into volume bands via
`volume_num_min/max`. The >$1M head (< 10k markets/band) is enumerated in full; the abundant
low tiers are bracket-counted cheaply. A floor spot-check pulls distinct trader counts at
candidate floor levels to confirm the floor is a sensible ABSOLUTE activity level.

Run:  .venv/bin/python pipeline/discover_corpus.py
"""
from __future__ import annotations

import json
import os

import requests

import ingest

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
V2_ERA = "2026-04-01"          # cheap first-cut flag; authoritative exclusion is on-chain

HEAD_BANDS = [(50_000_000, None), (25_000_000, 50_000_000), (10_000_000, 25_000_000),
              (5_000_000, 10_000_000), (2_500_000, 5_000_000), (1_000_000, 2_500_000)]
LOW_BANDS = [(500_000, 1_000_000), (250_000, 500_000), (100_000, 250_000),
             (50_000, 100_000), (25_000, 50_000)]
SPOT_LEVELS = [30_000, 60_000, 120_000, 300_000, 1_500_000]


def _is1(p):
    try:
        return abs(float(p) - 1.0) < 1e-9
    except (TypeError, ValueError):
        return False


def _jload(s):
    if isinstance(s, str):
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return None
    return s


def _band_params(vmin, vmax, offset):
    p = dict(closed="true", limit=100, offset=offset, order="volumeNum",
             ascending="false", volume_num_min=vmin)
    if vmax is not None:
        p["volume_num_max"] = vmax
    return p


def _is_candidate(m):
    if m.get("enableOrderBook") is not True:
        return None
    outs = _jload(m.get("outcomes"))
    if not (isinstance(outs, list) and len(outs) == 2):
        return None
    prices = _jload(m.get("outcomePrices"))
    if not (isinstance(prices, list) and any(_is1(p) for p in prices)):
        return None
    return {
        "slug": m.get("slug"), "question": m.get("question"),
        "conditionId": m.get("conditionId"),
        "clobTokenIds": _jload(m.get("clobTokenIds")) or [],
        "volumeNum": float(m.get("volumeNum") or 0),
        "endDate": m.get("endDate"), "createdAt": m.get("createdAt"),
        "negRisk": bool(m.get("negRisk")),
        "resolved_index": next((i for i, p in enumerate(prices) if _is1(p)), None),
    }


def enumerate_band_full(vmin, vmax):
    """Page a band fully (volume-desc); returns (candidates, hit_ceiling)."""
    out, off = [], 0
    while True:
        try:
            batch = ingest.gamma_markets(**_band_params(vmin, vmax, off))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 422):
                return out, True
            raise
        if not batch:
            return out, False
        out.extend(c for c in (_is_candidate(m) for m in batch) if c)
        off += 100
        if len(batch) < 100:
            return out, False
        if off >= 10000:
            return out, True


def bracket_count(vmin, vmax):
    """Cheaply bracket a band's size by probing descending offsets (avoids full paging)."""
    for off in (9900, 4900, 2400, 900, 400, 100, 0):
        try:
            batch = ingest.gamma_markets(**_band_params(vmin, vmax, off))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 422):
                continue
            raise
        if batch:
            lo = off + len(batch)
            return f">= {lo}" + (" (ceiling/abundant)" if off >= 9900 else "")
    return "0"


def spot_check(levels):
    """Pull distinct trader counts at candidate floor levels (floor calibration)."""
    rows = []
    for lvl in levels:
        band = ingest.gamma_markets(**_band_params(int(lvl * 0.9), int(lvl * 1.1), 0))
        cands = [c for c in (_is_candidate(m) for m in band) if c][:2]
        for c in cands:
            pl = ingest.probe_liquidity(c["conditionId"])
            rows.append({"level": lvl, "volume": round(c["volumeNum"]),
                         "slug": c["slug"], "distinct_takers_in_page": pl["distinct_wallets_in_page"],
                         "trades_in_page": pl["trades_page_n"], "capped": pl["trades_capped"]})
    return rows


def main() -> None:
    print("=== Step 2.1 — corpus discovery (read-only; no outcomes) ===")
    frame, band_stats = [], []
    print("\n  head bands (>$1M, full enumeration):")
    for vmin, vmax in HEAD_BANDS:
        cands, ceil = enumerate_band_full(vmin, vmax)
        frame.extend(cands)
        v2 = sum(1 for c in cands if c["endDate"] and c["endDate"] >= V2_ERA)
        neg = sum(c["negRisk"] for c in cands)
        band_stats.append({"band": [vmin, vmax], "n": len(cands), "v1": len(cands) - v2,
                           "v2": v2, "negRisk": neg, "ceiling": ceil, "mode": "full"})
        hi = "inf" if vmax is None else f"${vmax:,}"
        flag = " [CEILING-may undercount]" if ceil else ""
        print(f"     ${vmin:>11,} – {hi:<13}: n={len(cands):>4} (V1 {len(cands)-v2}, V2 {v2}, "
              f"negRisk {neg}){flag}")

    # dedup by conditionId (band boundaries are inclusive on both sides)
    seen, dedup = set(), []
    for c in frame:
        if c["conditionId"] and c["conditionId"] not in seen:
            seen.add(c["conditionId"]); dedup.append(c)
    frame = dedup

    print("\n  low tiers (<$1M, bracket counts — abundant population to sample from):")
    for vmin, vmax in LOW_BANDS:
        cnt = bracket_count(vmin, vmax)
        band_stats.append({"band": [vmin, vmax], "count_estimate": cnt, "mode": "bracket"})
        print(f"     ${vmin:>9,} – ${vmax:>11,}: {cnt}")

    print("\n  floor spot-check (distinct takers in one /trades page):")
    spot = spot_check(SPOT_LEVELS)
    for r in spot:
        print(f"     ~${r['level']:>9,} (vol ${r['volume']:>10,}): "
              f"{r['distinct_takers_in_page']:>4} takers / {r['trades_in_page']} trades"
              f"{'  [PAGE CAPPED]' if r['capped'] else ''}  {r['slug']}")

    vols = sorted(c["volumeNum"] for c in frame)
    n = len(frame)
    v2 = sum(1 for c in frame if c["endDate"] and c["endDate"] >= V2_ERA)
    neg = sum(c["negRisk"] for c in frame)
    print(f"\n  >$1M head frame: {n} candidates (V1 {n-v2}, V2 {v2}, negRisk {neg})")
    if vols:
        ps = (0, 25, 50, 75, 90, 95, 99, 100)
        print("  head volume percentiles ($): " +
              ", ".join(f"p{p}={int(vols[min(n-1,int(p/100*n))]):,}" for p in ps))

    ingest.save_raw("corpus_frame_head.json", frame)
    summary = {"head_frame_n": n, "head_v1": n - v2, "head_v2": v2, "head_negRisk": neg,
               "band_stats": band_stats, "spot_check": spot, "v2_era_cutoff": V2_ERA,
               "note": "Discovery only — no floor frozen, no market selected, no outcome "
                       "computed. Floor + tiers proposed from this distribution for approval."}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "corpus_discovery.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n  frame  -> data/raw/corpus_frame_head.json")
    print("  summary-> data/out/corpus_discovery.json")


if __name__ == "__main__":
    main()
