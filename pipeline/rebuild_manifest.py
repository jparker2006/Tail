"""Rebuild the corpus manifest from the authoritative per-market RESULT caches (post A6+A7).

Reads each market's cached result (no re-running, no shard load) and rebuilds the manifest rows +
summary via run_corpus._merge. Markets with no result cache (the unresolved timeouts) keep their
existing manifest row. Closes out the coverage gap to the 11 genuine giants.
"""
import json
import os
import sys

sys.path.insert(0, sys.path[0] or "pipeline")
import run_corpus as rc

man = json.load(open(rc.MANIFEST))
existing = man.get("rows", {})
rows, preserved = [], 0
for m in rc._corpus():
    slug = m["slug"]
    rpath = os.path.join(rc.rm.RESULTS, f"{slug}.json")
    if os.path.exists(rpath):
        r = json.load(open(rpath))
        det, ci = r.get("detruncation") or {}, r.get("concentration_interval") or {}
        rows.append({"slug": slug, "vol": m["volumeNum"], "tier": m["tier"],
                     "cls": m.get("mkt_class"), "is_mega": m["volumeNum"] >= rc.MEGA,
                     "status": r.get("status"), "tape_source": r.get("tape_source"),
                     "truncated": r.get("trades_truncated"),
                     "n_fills": r.get("n_fills"), "n_directional": r.get("n_directional"),
                     "gini": ci.get("gini"), "n_half_frac": ci.get("N_half_frac"),
                     "recovery_ratio": det.get("recovery_ratio"), "gamma_flag": det.get("gamma_flag"),
                     "excluded_reason": det.get("excluded_reason"),
                     "trades_quantity": det.get("trades_quantity")})
    elif slug in existing:
        rows.append(existing[slug]); preserved += 1

s = rc._merge(rows)
print("by_status:", s["by_status"])
print("coverage_gap n_excluded:", s["coverage_gap"]["n_excluded"],
      "| excluded vol share:", round(s["coverage_gap"]["excluded_volume_share"], 4))
print("excluded markets:", [x["slug"][:40] for x in s["coverage_gap"]["markets"]])
print("timeouts_to_review:", len(s["timeouts_to_review"]), "| preserved (no cache):", preserved)
