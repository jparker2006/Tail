"""Step 2.7b — F1' robustness riders (CORPUS_PREREG §1.3-§1.5), event/headline corpus.

The F1' kill criterion (median Gini >= 0.60 AND median N_half/n <= 0.05) already SURVIVES under
both methods (step 2.7). This is the frozen robustness envelope around it, on the INTERVAL primary
(window-length and phase-offset have no meaning for per-fill, which has no window grid; per-fill is
the unchanged companion). Three sweeps, each recomputed from LOCAL caches only (no network):

  - flatness bands {0.10, 0.15, 0.20}  : re-classify the MM set at each flatness threshold (the only
                                          sweep that moves the MM set), at primary N=25, offset=0.
  - window length  N {10, 25, 50, 100} : interval_attribute at each N, primary flatness 0.15, offset 0.
  - phase offset   {0, N/4, N/2, 3N/4} : at N=25, primary flatness 0.15 (offsets floored to ints).

Per market we record the per-market F1 verdict (Gini>=0.60 AND N_half/n<=0.05, interval) at every
setting and whether it is INVARIANT across each rider. Corpus reports: the median Gini at every
setting (the kill criterion must clear 0.60 everywhere) and the fraction of markets whose per-market
F1 verdict is invariant / passes at every band. A per-market baseline guard asserts the recomputed
(flatness 0.15, N=25, offset 0) Gini reproduces the cached concentration_interval — proving the
recompute path is the same one that produced the closed corpus.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

import attribution
import ingest
import mm_filter
import run_market
import schema

MANIFEST = os.path.join("data", "out", "corpus_run_manifest.json")
PRIMARY = os.path.join("data", "out", "corpus_primary.json")
SECONDARY = os.path.join("data", "out", "corpus_secondary.json")
RESULTS = os.path.join(ingest.RAW_DIR, "results")
OUT = os.path.join("data", "out", "corpus_f1_riders.json")


def _markets_union():
    """slug -> metadata across both frames (event in primary, recurring in secondary)."""
    return {m["slug"]: m for m in _load(PRIMARY)["markets"] + _load(SECONDARY)["markets"]}


def _out_for(cls):
    return OUT if cls == "event" else OUT.replace(".json", f"_{cls}.json")

BANDS = (0.10, 0.15, 0.20)
WINDOWS = (10, 25, 50, 100)
N_PRIMARY = 25
FLAT_PRIMARY = 0.15
GINI_FLOOR, NHF_CEIL = 0.60, 0.05
OFFSETS = sorted({int(N_PRIMARY * k / 4) for k in range(4)})   # {0, N/4, N/2, 3N/4} floored


def _load(path):
    with open(path) as f:
        return json.load(f)


def _required(name):
    obj = ingest.load_raw(name)
    if obj is None:
        raise FileNotFoundError(f"missing required cache data/raw/{name}")
    return obj


def _tapes(slug, source):
    if source == "subgraph":
        c = _required(f"{slug}_subgraph.json")
        return c["taker"], c["full"]
    if source == "trades":
        return _required(f"{slug}_taker.json")["rows"], _required(f"{slug}_full.json")["rows"]
    raise ValueError(f"{slug}: unsupported tape_source={source!r}")


def _ingredients(market, result):
    """fills, R, wstats, breadth_map, aggressors, volume — everything to re-classify at any band."""
    taker_rows, full_rows = _tapes(market["slug"], result["tape_source"])
    mtruth = run_market._market_for_truth(market)
    fills, R = schema.normalize_fills(taker_rows, {}, mtruth)
    full_fills, _ = schema.normalize_fills(full_rows, {}, mtruth)
    aggressors = {f["proxy_wallet"] for f in fills}
    wstats = run_market.build_flatness_stats(full_fills)
    vol = float(market.get("volumeNum") or 0)
    floor = mm_filter.mm_min_notional(vol)
    breadth_map = {}
    for w, s in wstats.items():
        if s["gross_notional"] >= floor and w in aggressors:
            breadth_map[w] = _required(f"breadth_{w[:10]}_{market['slug']}.json")
    if len(fills) != result.get("n_fills"):
        raise RuntimeError(f"{market['slug']}: n_fills {len(fills)} != {result.get('n_fills')}")
    return fills, R, wstats, breadth_map, aggressors, vol


def _mm_set(wstats, vol, breadth_map, aggressors, flat):
    cls, _ = mm_filter.classify(wstats, vol, breadth_map, flatness_thresh=flat, role_coverage=0.0)
    return {w for w, c in cls.items() if c["is_mm"]} & aggressors


def _conc(fills, R, mm_set, aggressors, N, offset):
    ia = attribution.interval_attribute(fills, R, mm_set, n_per_window=N, offset=offset)
    return attribution.concentration(ia["C"], len(aggressors - mm_set))


def _verdict(conc):
    g, nhf = conc.get("gini"), conc.get("N_half_frac")
    if g is None or nhf is None:
        return None
    return bool(g >= GINI_FLOOR and nhf <= NHF_CEIL)


def main(cls="event"):
    rows = _load(MANIFEST)["rows"]
    markets = _markets_union()
    slugs = [s for s, r in rows.items() if r.get("status") == "ok" and r.get("cls") == cls]
    print(f"(class={cls})", flush=True)

    # accumulators: per setting -> list of (gini, verdict); per market -> invariance flags
    flat_g = {b: [] for b in BANDS}
    win_g = {n: [] for n in WINDOWS}
    off_g = {o: [] for o in OFFSETS}
    inv_flat = inv_win = inv_off = inv_all = pass_all_flat = 0
    n_eval = 0
    guard_fail = []
    t0 = time.time()
    print(f"=== F1' riders — event ok markets n={len(slugs)} ===", flush=True)
    for i, slug in enumerate(slugs, 1):
        market, result = markets.get(slug), _load(os.path.join(RESULTS, f"{slug}.json"))
        if market is None:
            raise KeyError(f"{slug}: not in corpus_primary.json")
        fills, R, wstats, breadth, aggr, vol = _ingredients(market, result)

        mm = {b: _mm_set(wstats, vol, breadth, aggr, b) for b in BANDS}
        # baseline reproduction guard (flatness 0.15, N=25, offset 0) vs cached concentration_interval
        base = _conc(fills, R, mm[FLAT_PRIMARY], aggr, N_PRIMARY, 0)
        cg = (result.get("concentration_interval") or {}).get("gini")
        if cg is not None and base.get("gini") is not None and abs(base["gini"] - cg) > 1e-6:
            guard_fail.append((slug, base["gini"], cg))

        vflat, vwin, voff = {}, {}, {}
        for b in BANDS:
            c = base if b == FLAT_PRIMARY else _conc(fills, R, mm[b], aggr, N_PRIMARY, 0)
            flat_g[b].append(c.get("gini")); vflat[b] = _verdict(c)
        for n in WINDOWS:
            c = base if n == N_PRIMARY else _conc(fills, R, mm[FLAT_PRIMARY], aggr, n, 0)
            win_g[n].append(c.get("gini")); vwin[n] = _verdict(c)
        for o in OFFSETS:
            c = base if o == 0 else _conc(fills, R, mm[FLAT_PRIMARY], aggr, N_PRIMARY, o)
            off_g[o].append(c.get("gini")); voff[o] = _verdict(c)

        n_eval += 1
        ff = [v for v in vflat.values() if v is not None]
        wf = [v for v in vwin.values() if v is not None]
        of = [v for v in voff.values() if v is not None]
        i_flat = len(set(ff)) <= 1
        i_win = len(set(wf)) <= 1
        i_off = len(set(of)) <= 1
        inv_flat += i_flat; inv_win += i_win; inv_off += i_off
        inv_all += (i_flat and i_win and i_off)
        pass_all_flat += all(ff) and len(ff) == len(BANDS)

        if i == 1 or i % 200 == 0 or i == len(slugs):
            print(f"  {i:4d}/{len(slugs)}  inv_all={inv_all}/{n_eval}  guard_fail={len(guard_fail)}  "
                  f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)

    def med(xs):
        a = np.array([x for x in xs if x is not None], float)
        return float(np.median(a)) if a.size else None

    out = {"label": cls, "n_ok": len(slugs), "n_eval": n_eval,
           "method": "interval (per-fill is the unchanged companion; no window grid)",
           "guard_fail_count": len(guard_fail), "guard_fail_sample": guard_fail[:5],
           "flatness_band_median_gini": {str(b): med(flat_g[b]) for b in BANDS},
           "window_length_median_gini": {str(n): med(win_g[n]) for n in WINDOWS},
           "phase_offset_median_gini": {str(o): med(off_g[o]) for o in OFFSETS},
           "offsets_used": OFFSETS,
           "frac_invariant_flatness": inv_flat / n_eval,
           "frac_invariant_window": inv_win / n_eval,
           "frac_invariant_offset": inv_off / n_eval,
           "frac_invariant_all_riders": inv_all / n_eval,
           "frac_pass_all_flatness_bands": pass_all_flat / n_eval}
    json.dump(out, open(_out_for(cls), "w"), indent=2)

    print(f"\n--- F1' RIDERS ({cls}, interval) ---")
    print(f"  baseline reproduction guard failures: {len(guard_fail)} / {n_eval}")
    print(f"  flatness {{0.10,0.15,0.20}} median Gini: "
          f"{[round(out['flatness_band_median_gini'][str(b)],4) for b in BANDS]}")
    print(f"  window   {{10,25,50,100}}  median Gini: "
          f"{[round(out['window_length_median_gini'][str(n)],4) for n in WINDOWS]}")
    print(f"  offset   {OFFSETS}  median Gini: "
          f"{[round(out['phase_offset_median_gini'][str(o)],4) for o in OFFSETS]}")
    print(f"  per-market F1-verdict invariant: flatness {out['frac_invariant_flatness']*100:.1f}%  "
          f"window {out['frac_invariant_window']*100:.1f}%  offset {out['frac_invariant_offset']*100:.1f}%")
    print(f"  invariant across ALL riders: {out['frac_invariant_all_riders']*100:.1f}%  | "
          f"pass at all 3 flatness bands: {out['frac_pass_all_flatness_bands']*100:.1f}%")
    print(f"\n-> {_out_for(cls)}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main(sys.argv[1] if len(sys.argv) > 1 else "event")
