"""Step 2.7 follow-up — recompute Claim-3 calibrated FPR from local caches only.

This refreshes `claim3` for ok EVENT markets after `claims.claim3()` gained `fpr_m`.
It deliberately refuses to fetch network data: tapes and breadth probes must already exist
under data/raw from the closed corpus run.

Run:
  .venv/bin/python pipeline/recompute_claim3_fpr.py
"""
from __future__ import annotations

import json
import os
import time

import claims
import ingest
import mm_filter
import run_market
import schema

MANIFEST = os.path.join("data", "out", "corpus_run_manifest.json")
PRIMARY = os.path.join("data", "out", "corpus_primary.json")
RESULTS = os.path.join(ingest.RAW_DIR, "results")
OUT = os.path.join("data", "out", "corpus_f3_calibration.json")


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_raw_required(name: str):
    obj = ingest.load_raw(name)
    if obj is None:
        raise FileNotFoundError(f"missing required cache data/raw/{name}")
    return obj


def cached_tapes(slug: str, source: str):
    if source == "subgraph":
        cached = load_raw_required(f"{slug}_subgraph.json")
        return cached["taker"], cached["full"]
    if source == "trades":
        taker = load_raw_required(f"{slug}_taker.json")["rows"]
        full = load_raw_required(f"{slug}_full.json")["rows"]
        return taker, full
    raise ValueError(f"{slug}: unsupported tape_source={source!r}")


def cached_mm_set(market: dict, result: dict) -> tuple[list[dict], int, set[str]]:
    slug = market["slug"]
    taker_rows, full_rows = cached_tapes(slug, result["tape_source"])
    mtruth = run_market._market_for_truth(market)
    fills, R = schema.normalize_fills(taker_rows, {}, mtruth)
    full_fills, _ = schema.normalize_fills(full_rows, {}, mtruth)

    aggressors = {f["proxy_wallet"] for f in fills}
    wstats = run_market.build_flatness_stats(full_fills)
    floor = mm_filter.mm_min_notional(float(market.get("volumeNum") or 0))
    cand = [w for w, s in wstats.items()
            if s["gross_notional"] >= floor and w in aggressors]
    breadth_map = {}
    for w in cand:
        bname = f"breadth_{w[:10]}_{slug}.json"
        breadth_map[w] = load_raw_required(bname)

    cls, _ = mm_filter.classify(
        wstats, float(market.get("volumeNum") or 0), breadth_map, role_coverage=0.0
    )
    mm_set = {w for w, c in cls.items() if c["is_mm"]} & aggressors

    # Guard that the reconstructed path is the same one used by the closed result cache.
    if len(fills) != result.get("n_fills"):
        raise RuntimeError(f"{slug}: n_fills changed {len(fills)} != {result.get('n_fills')}")
    if len(aggressors - mm_set) != result.get("n_directional"):
        raise RuntimeError(
            f"{slug}: n_directional changed {len(aggressors - mm_set)} "
            f"!= {result.get('n_directional')}"
        )
    return fills, R, mm_set


def main() -> None:
    manifest = load_json(MANIFEST)["rows"]
    markets = {m["slug"]: m for m in load_json(PRIMARY)["markets"]}
    slugs = [
        slug for slug, row in manifest.items()
        if row.get("status") == "ok" and row.get("cls") == "event"
    ]

    started = time.time()
    n_changed = 0
    n_pass = 0
    fprs = []
    excluded_claim3 = 0
    print(f"=== Claim-3 calibrated FPR recompute — event ok markets n={len(slugs)} ===")
    for i, slug in enumerate(slugs, start=1):
        market = markets.get(slug)
        if market is None:
            raise KeyError(f"{slug}: not found in corpus_primary.json")
        rpath = os.path.join(RESULTS, f"{slug}.json")
        result = load_json(rpath)
        fills, R, mm_set = cached_mm_set(market, result)
        c3 = claims.claim3(fills, R, mm_set)
        old = result.get("claim3", {})
        result["claim3"] = c3
        with open(rpath, "w") as f:
            json.dump(result, f)

        if old.get("fpr_m") != c3.get("fpr_m"):
            n_changed += 1
        if c3.get("peak_rho") is not None and c3.get("n_bins_active", 0) >= 48:
            fprs.append(c3["fpr_m"])
            n_pass += int(bool(c3.get("f3_pass")))
        else:
            excluded_claim3 += 1

        if i == 1 or i % 100 == 0 or i == len(slugs):
            elapsed = time.time() - started
            print(
                f"  {i:4d}/{len(slugs)}  pass={n_pass}  in_scope={len(fprs)}  "
                f"mean_fpr={(sum(fprs) / len(fprs) if fprs else 0.0):.4f}  "
                f"elapsed={elapsed/60:.1f}m",
                flush=True,
            )

    summary = {
        "label": "event/headline",
        "n_event_ok": len(slugs),
        "n_claim3_inscope": len(fprs),
        "n_claim3_excluded": excluded_claim3,
        "n_f3_pass": n_pass,
        "frac_f3_pass": n_pass / len(fprs) if fprs else None,
        "mean_calibrated_fpr": sum(fprs) / len(fprs) if fprs else None,
        "expected_passes_calibrated": sum(fprs),
        "n_result_claim3_changed": n_changed,
    }
    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
