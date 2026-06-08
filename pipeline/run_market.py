"""Phase-2 Step 2.4 — parameterized per-market pipeline (/trades-only, 2-signal path).

One reusable `run_market(market)` that takes a corpus market dict and runs the validated
Phase-1 machinery end to end WITHOUT on-chain (the broad-corpus path, A1.2):

  taker tape (takerOnly=true)  -> aggressor fills -> interval + per-fill attribution -> Gini/N_half
  full tape  (takerOnly=false) -> per-wallet net/gross -> flatness signal A
  /trades?user= probes          -> cross-market breadth signal B   (above-floor wallets only)
  MM filter with role_coverage=0 (signals A+B; C reserved for the on-chain validation subset)
  claim2 (movers' edge) + claim3 (echo) as in Phase 1.

On-chain role (signal C / full validation) is reserved for the 2.5 validation subset and any
market whose tape exceeds the /trades ceiling (`trades_truncated`). Results cache to
data/raw/results for checkpoint/resume; the per-market dict is the analysis + demo record.

Run:  .venv/bin/python pipeline/run_market.py        # smoke test on a few corpus markets
"""
from __future__ import annotations

import json
import os

import ingest
import schema
import mm_filter
import attribution
import claims
import subgraph

RESULTS = os.path.join(ingest.RAW_DIR, "results")
MIN_DIRECTIONAL = 30          # analyzability floor (A1.2); below -> reported thin, not a null
N_WINDOW = 25                 # interval attribution window (frozen)


def _market_for_truth(m: dict) -> dict:
    """Corpus dicts carry `resolved_index`; schema.market_truth wants `resolved_outcome_index`."""
    return {**m, "resolved_outcome_index": m.get("resolved_index")}


def build_flatness_stats(full_fills: list[dict]) -> dict:
    """Per-wallet net/gross over the maker-inclusive tape -> mm_filter-compatible wstats.

    aggressor_share is left None (signal C is off in the 2-signal path)."""
    agg: dict[str, dict] = {}
    for f in full_fills:
        w = agg.setdefault(f["proxy_wallet"], {"gross_shares": 0.0, "net_shares": 0.0,
                                               "gross_notional": 0.0, "name": None})
        w["gross_shares"] += f["size"]
        w["net_shares"] += f["signed_shares"]
        w["gross_notional"] += f["usdc_notional"]
        if f["wallet_name"] and not w["name"]:
            w["name"] = f["wallet_name"]
    for w in agg.values():
        g = w["gross_shares"]
        w["flatness"] = (abs(w["net_shares"]) / g) if g > 0 else None
        w["aggressor_share"] = None
    return agg


def _tape(cid: str, slug: str, taker_only: bool):
    name = f"{slug}_{'taker' if taker_only else 'full'}.json"
    cached = ingest.load_raw(name)
    if cached is not None:
        return cached["rows"], cached["meta"]
    rows, meta = ingest.pull_all_trades(cid, taker_only=taker_only)
    ingest.save_raw(name, {"rows": rows, "meta": meta})
    return rows, meta


def _exchange_for(m: dict) -> str:
    return subgraph.NEGRISK_EXCHANGE_V1 if m.get("negRisk") else subgraph.CTF_EXCHANGE_V1


def _subgraph_tapes(m: dict, n_trades_taker: int):
    """Recover the COMPLETE taker+full tapes from the subgraph (A5), one legs pull, cached.

    Gated for completeness: paginated legs == the subgraph's own Σ tradesQuantity AND non-empty
    AND recovers ≥ what /trades saw. A failure marks the market for the A5 exclude branch."""
    slug = m["slug"]
    cached = ingest.load_raw(f"{slug}_subgraph.json")
    if cached is not None:
        return cached["taker"], cached["full"], cached["meta"]
    tokens = [str(t) for t in m["clobTokenIds"]]
    exch = _exchange_for(m)
    legs, comp = subgraph.fetch_market_legs_checked(tokens)
    taker = subgraph.market_rows(tokens, exch, taker_only=True, legs=legs)
    full = subgraph.market_rows(tokens, exch, taker_only=False, legs=legs)
    recovered_ok = bool(comp["complete"] and comp["n_legs"] > 0
                        and len(taker) >= n_trades_taker)
    meta = {**comp, "n_taker": len(taker), "n_full": len(full),
            "recovery_ratio": (len(taker) / n_trades_taker) if n_trades_taker else None,
            "recovered_ok": recovered_ok,
            "gamma_volume": float(m.get("volumeNum") or 0)}
    ingest.save_raw(f"{slug}_subgraph.json", {"taker": taker, "full": full, "meta": meta})
    return taker, full, meta


def _market_tapes(m: dict):
    """Hybrid tape acquisition (A5): /trades primary; subgraph only when /trades is truncated.

    Returns (taker_rows, full_rows, meta). meta['source'] ∈ {'trades','subgraph','excluded'}."""
    cid, slug = m["conditionId"], m["slug"]
    taker_rows, t_meta = _tape(cid, slug, taker_only=True)
    full_rows, f_meta = _tape(cid, slug, taker_only=False)
    truncated = bool(t_meta.get("truncated") or f_meta.get("truncated"))
    meta = {"source": "trades", "trades_truncated": truncated,
            "n_trades_taker": len(taker_rows)}
    if not truncated:
        return taker_rows, full_rows, meta
    sg_taker, sg_full, comp = _subgraph_tapes(m, len(taker_rows))
    meta.update({"source": "subgraph" if comp["recovered_ok"] else "excluded",
                 "recovery_ratio": comp["recovery_ratio"],
                 "subgraph_complete": comp["complete"], "n_legs": comp["n_legs"],
                 "trades_quantity": comp["trades_quantity"],
                 "scaled_collateral_volume": comp["scaled_collateral_volume"]})
    return sg_taker, sg_full, meta


def run_market(m: dict, use_cache: bool = True) -> dict:
    slug, cid = m["slug"], m["conditionId"]
    os.makedirs(RESULTS, exist_ok=True)
    rpath = os.path.join(RESULTS, f"{slug}.json")
    if use_cache and os.path.exists(rpath):
        with open(rpath) as f:
            return json.load(f)

    market = _market_for_truth(m)
    volume = float(m.get("volumeNum") or 0)
    taker_rows, full_rows, tape_meta = _market_tapes(m)    # hybrid: /trades, or subgraph if truncated

    fills, R = schema.normalize_fills(taker_rows, {}, market)
    aggressors = {f["proxy_wallet"] for f in fills}
    result = {"slug": slug, "conditionId": cid, "tier": m.get("tier"),
              "mkt_class": m.get("mkt_class"), "negRisk": m.get("negRisk"),
              "volumeNum": volume, "R_yes": R, "n_fills": len(fills),
              "n_aggressors": len(aggressors),
              "trades_truncated": tape_meta["trades_truncated"],
              "tape_source": tape_meta["source"]}
    if tape_meta["source"] in ("subgraph", "excluded"):
        result["detruncation"] = {k: tape_meta.get(k) for k in
                                  ("recovery_ratio", "subgraph_complete", "n_legs",
                                   "trades_quantity", "scaled_collateral_volume")}
    if tape_meta["source"] == "excluded":                  # A5 coverage gap (reported with/without)
        result["status"] = "excluded"
        with open(rpath, "w") as f:
            json.dump(result, f)
        return result

    # flatness substrate from the maker-inclusive tape
    full_fills, _ = schema.normalize_fills(full_rows, {}, market)
    wstats = build_flatness_stats(full_fills)

    # breadth probe only for wallets above the MM volume floor (bounds API calls)
    floor = mm_filter.mm_min_notional(volume)
    cand = [w for w, s in wstats.items()
            if s["gross_notional"] >= floor and w in aggressors]
    breadth_map = {}
    for w in cand:
        bname = f"breadth_{w[:10]}_{slug}.json"
        b = ingest.load_raw(bname)
        if b is None:
            b = ingest.breadth_probe(w, cid)
            ingest.save_raw(bname, b)
        breadth_map[w] = b

    cls, mmeta = mm_filter.classify(wstats, volume, breadth_map, role_coverage=0.0)
    mm_set = {w for w, c in cls.items() if c["is_mm"]} & aggressors
    n_directional = len(aggressors - mm_set)
    result["n_mm"] = len(mm_set)
    result["n_directional"] = n_directional

    if n_directional < MIN_DIRECTIONAL:
        result["status"] = "thin"            # reported separately, NOT a null (A1.2)
        with open(rpath, "w") as f:
            json.dump(result, f)
        return result
    result["status"] = "ok"

    # attribution: interval primary + per-fill side by side (A1.3 dual reporting)
    iv = attribution.interval_attribute(fills, R, mm_set, n_per_window=N_WINDOW)
    pf = attribution.attribute(fills, R, mm_set)
    result["concentration_interval"] = attribution.concentration(iv["C"], n_directional)
    result["concentration_perfill"] = attribution.concentration(pf["C"], n_directional)
    result["interval_vs_crude_spearman"] = attribution.crosscheck(iv["C"], pf["crude"])["spearman"]

    # claims (single-market => within-market descriptive; corpus aggregates them in 2.7)
    result["claim2"] = claims.claim2(fills, R, mm_set, K=10)
    result["claim2_lenses"] = claims.claim2_lenses(fills, R, mm_set, K=10)
    result["claim3"] = claims.claim3(fills, R, mm_set)

    # compact demo payload: top contributors + downsampled price path
    wn = {f["proxy_wallet"]: f["wallet_name"] for f in fills}
    top = sorted(iv["C"].items(), key=lambda kv: kv[1], reverse=True)[:15]
    result["top_contributors"] = [{"wallet": w, "name": wn.get(w), "C": c} for w, c in top]
    pp = schema.price_path(fills)
    result["price_path"] = pp if len(pp) <= 400 else pp[:: len(pp) // 400 + 1]

    with open(rpath, "w") as f:
        json.dump(result, f)
    return result


def main() -> None:
    primary = json.load(open(os.path.join(
        os.path.dirname(__file__), "..", "data", "out", "corpus_primary.json")))["markets"]
    # smoke test: the smallest market per tier (small = fast, no truncation)
    by_tier = {}
    for m in sorted(primary, key=lambda x: x["volumeNum"]):
        by_tier.setdefault(m["tier"], []).append(m)
    sample = [by_tier[t][0] for t in ("T1", "T2", "T3") if t in by_tier]
    print("=== Step 2.4 smoke test (/trades-only 2-signal pipeline) ===")
    for m in sample:
        r = run_market(m, use_cache=False)
        print(f"\n  [{r['tier']}] {r['slug'][:54]}  vol ${r['volumeNum']:,.0f}")
        print(f"    fills {r['n_fills']}, aggressors {r['n_aggressors']}, MM {r.get('n_mm','-')}, "
              f"directional {r['n_directional']}, truncated {r['trades_truncated']}, R={r['R_yes']}")
        if r["status"] != "ok":
            print(f"    status: {r['status']} (below analyzability floor)")
            continue
        ci, cp = r["concentration_interval"], r["concentration_perfill"]
        print(f"    Gini interval {ci['gini']} | per-fill {cp['gini']} | "
              f"N_half {ci['N_half']} ({(ci['N_half_frac'] or 0)*100:.1f}%) | "
              f"iv-vs-crude rho {r['interval_vs_crude_spearman']}")
        print(f"    claim2 {r['claim2']['verdict']} | claim3 peak rho {r['claim3']['peak_rho']:.3f} "
              f"(f3 {r['claim3']['f3_pass']})")


if __name__ == "__main__":
    main()
