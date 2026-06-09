"""Phase-2 Step 2.6g — the corpus batch run.

Runs run_market over the full frozen corpus (primary event + secondary recurring), hybrid
de-truncation applied automatically. Mega-first (descending volume) so the heaviest/riskiest
subgraph pulls happen first, under watch. Phase-aware concurrency ramp (per the danger-zone
logic): the mega tail (>$50M) runs at LOW concurrency where load-timeout risk peaks; the light
tail runs higher. Resumable (run_market caches results -> a restart skips completed markets).

Failure categorization is load-bearing: a subgraph statement-timeout is a LOAD-timeout (recoverable
at lower concurrency, esp. for megas — NOT an A5 coverage gap) and is tagged 'timeout', kept
distinct from a genuine 'excluded' (recovered_ok False) or an 'error' (other bug). After the run,
ANY mega in timeout/error MUST be re-run alone at concurrency 1 before the batch is called done —
a mega load-timeout masquerading as a gap is the one way this batch could silently drop a
headline-anchoring market.

Run:
  caffeinate -i .venv/bin/python pipeline/run_corpus.py megas            # >$50M at concurrency 2
  caffeinate -i .venv/bin/python pipeline/run_corpus.py tail             # <$50M at concurrency 6
  caffeinate -i .venv/bin/python pipeline/run_corpus.py megas --workers 1   # re-run stuck megas
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import run_market as rm

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
MANIFEST = os.path.join(OUT, "corpus_run_manifest.json")
MEGA = 5e7            # >$50M -> heavy subgraph recovery -> low concurrency
N_MEGA, N_TAIL = 2, 6


def _corpus() -> list[dict]:
    prim = json.load(open(os.path.join(OUT, "corpus_primary.json")))["markets"]
    sec = json.load(open(os.path.join(OUT, "corpus_secondary.json")))["markets"]
    return sorted(prim + sec, key=lambda m: -m["volumeNum"])      # mega-first


def process(m: dict) -> dict:
    slug = m["slug"]
    t0 = time.time()
    base = {"slug": slug, "vol": m["volumeNum"], "tier": m["tier"],
            "cls": m.get("mkt_class"), "is_mega": m["volumeNum"] >= MEGA}
    try:
        r = rm.run_market(m, use_cache=True)
        det, ci = r.get("detruncation") or {}, r.get("concentration_interval") or {}
        return {**base, "secs": round(time.time() - t0, 1), "status": r.get("status"),
                "tape_source": r.get("tape_source"), "truncated": r.get("trades_truncated"),
                "n_fills": r.get("n_fills"), "n_directional": r.get("n_directional"),
                "gini": ci.get("gini"), "n_half_frac": ci.get("N_half_frac"),
                "recovery_ratio": det.get("recovery_ratio"), "gamma_flag": det.get("gamma_flag"),
                "excluded_reason": det.get("excluded_reason"),
                "trades_quantity": det.get("trades_quantity")}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # a load-timeout is recoverable at lower concurrency — NOT a coverage gap (shared predicate)
        import subgraph
        kind = "timeout" if subgraph.is_timeout(msg) else "error"
        return {**base, "secs": round(time.time() - t0, 1), "status": kind, "error": msg[:160]}


def _merge(rows: list[dict]) -> dict:
    man = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {"rows": {}}
    for r in rows:
        man["rows"][r["slug"]] = r
    all_rows = list(man["rows"].values())
    from collections import Counter
    excluded = [r for r in all_rows if r["status"] == "excluded"]
    corpus_vol = sum(r["vol"] for r in all_rows) or 1
    man["summary"] = {
        "n": len(all_rows), "by_status": dict(Counter(r["status"] for r in all_rows)),
        "by_source": dict(Counter(r.get("tape_source") for r in all_rows if r.get("tape_source"))),
        "n_truncated": sum(1 for r in all_rows if r.get("tape_source") == "subgraph"),
        "gamma_flagged": [r["slug"] for r in all_rows if r.get("gamma_flag")],
        # A5 coverage gap — the excluded extreme tail, quantified for honest disclosure
        "coverage_gap": {
            "n_excluded": len(excluded),
            "excluded_volume": sum(r["vol"] for r in excluded),
            "excluded_volume_share": sum(r["vol"] for r in excluded) / corpus_vol,
            "markets": sorted([{"slug": r["slug"], "vol": r["vol"],
                                "trades_quantity": r.get("trades_quantity"),
                                "reason": r.get("excluded_reason")} for r in excluded],
                              key=lambda x: -x["vol"])},
        "errored": [r["slug"] for r in all_rows if r["status"] == "error"],
        # non-excluded timeouts: transient blips / sub-giant markets to RETRY + eyeball (NOT gaps)
        "timeouts_to_review": [r["slug"] for r in all_rows if r["status"] == "timeout"],
        "mega_failures_to_review": [r["slug"] for r in all_rows
                                    if r.get("is_mega") and r["status"] in ("timeout", "error")]}
    json.dump(man, open(MANIFEST, "w"), indent=2)
    return man["summary"]


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else None
    corpus = _corpus()
    if phase == "megas":
        work, w = [m for m in corpus if m["volumeNum"] >= MEGA], workers or N_MEGA
    elif phase == "tail":
        work, w = [m for m in corpus if m["volumeNum"] < MEGA], workers or N_TAIL
    else:
        work, w = corpus, workers or N_TAIL
    print(f"=== corpus batch: phase '{phase}' | {len(work)} markets | concurrency {w} ===", flush=True)

    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=w) as ex:
        futs = {ex.submit(process, m): m for m in work}
        for f in as_completed(futs):
            r = f.result(); rows.append(r); done += 1
            tag = (r["status"] or "?")
            extra = (f" src={r.get('tape_source')} fills={r.get('n_fills')} gini={r.get('gini')}"
                     if tag in ("ok", "thin") else f" !! {r.get('error', '')[:60]}")
            print(f"  [{done}/{len(work)}] {tag:9} ${r['vol']:>13,.0f} {r['slug'][:42]}{extra}", flush=True)
            if done % 25 == 0:
                _merge(rows); rows = []        # checkpoint the manifest periodically

    summ = _merge(rows)
    cg = summ["coverage_gap"]
    print("\n=== batch summary ===")
    print(f"  total {summ['n']} | by_status {summ['by_status']} | recovered {summ['n_truncated']}")
    print(f"  A5 coverage gap (excluded giants): {cg['n_excluded']} markets, "
          f"{cg['excluded_volume_share']*100:.1f}% of corpus volume")
    print(f"  errored {len(summ['errored'])} | timeouts_to_review {len(summ['timeouts_to_review'])}"
          f" | gamma_flagged {len(summ['gamma_flagged'])}")
    if summ["mega_failures_to_review"]:
        print(f"  *** {len(summ['mega_failures_to_review'])} sub-giant mega timeouts — RETRY + eyeball "
              f"(transient blips, NOT coverage gaps): {summ['mega_failures_to_review'][:8]}")
    print("  -> data/out/corpus_run_manifest.json")


if __name__ == "__main__":
    main()
