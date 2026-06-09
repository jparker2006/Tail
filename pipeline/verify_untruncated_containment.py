"""Corpus integrity — UN-TRUNCATED arm (containment where /trades is WHOLE).

For markets the pipeline served from /trades directly (not truncated), /trades is the COMPLETE
reference. Pull the subgraph tape, map aggressor fills, and require every /trades aggressor key
(tx,wallet,token,side) to be present in the subgraph set. Because /trades is whole here, this is a
STRONG check: any missing key is a real mapping gap or source undercount, with no truncation alibi.
Validates the de-truncation mapping machinery at corpus scale (bar-1 was n=2).

Resumable (skips slugs already in the output), error-tolerant (records timeouts/errors), concurrency
-limited to spare the free shard. Output: data/out/corpus_integrity_untruncated.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, sys.path[0] or "pipeline")
import subgraph

OUT = "data/out/corpus_integrity_untruncated.json"
RAW = "data/raw"


def _rows(o):
    return o["rows"] if isinstance(o, dict) and "rows" in o else o


def _keys(rs):
    return {(str(r["transactionHash"]).lower(), str(r["proxyWallet"]).lower(),
             str(r["asset"]), str(r["side"]).upper()) for r in rs}


def _check(m: dict) -> dict:
    slug = m["slug"]
    tpath = f"{RAW}/{slug}_taker.json"
    base = {"slug": slug, "vol": m.get("volumeNum")}
    if not os.path.exists(tpath):
        return {**base, "status": "no_trades_cache"}
    try:
        tokens = [str(t) for t in m["clobTokenIds"]]
        exch = subgraph.NEGRISK_EXCHANGE_V1 if m.get("negRisk") else subgraph.CTF_EXCHANGE_V1
        legs = subgraph.fetch_market_legs(tokens)
        K_sg = _keys(subgraph.map_aggressor_fills(legs, tokens, exch))
        K_tr = _keys(_rows(json.load(open(tpath))))
        missing = len(K_tr - K_sg)
        return {**base, "status": "ok", "trades_keys": len(K_tr), "sg_keys": len(K_sg),
                "missing": missing, "missing_frac": round(missing / max(1, len(K_tr)), 4)}
    except Exception as e:  # noqa: BLE001
        kind = "timeout" if subgraph.is_timeout(str(e)) else "error"
        return {**base, "status": kind, "error": str(e)[:120]}


def main() -> None:
    man = json.load(open("data/out/corpus_run_manifest.json"))
    ut = [r["slug"] for r in man["rows"].values()
          if r.get("tape_source") == "trades" and r["status"] == "ok"]
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    byslug = {m["slug"]: m for m in prim + sec}

    done = {}
    if os.path.exists(OUT):
        done = {r["slug"]: r for r in json.load(open(OUT))}
    work = [byslug[s] for s in ut if s in byslug and s not in done]
    print(f"=== un-truncated containment: {len(work)} to check "
          f"({len(done)} cached) @ concurrency 6 ===", flush=True)

    results = list(done.values())
    t0, n = time.time(), 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_check, m): m for m in work}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            n += 1
            if r.get("missing"):
                print(f"  FAIL {r['slug'][:48]:48} missing={r['missing']}/{r['trades_keys']} "
                      f"({r['missing_frac']*100:.1f}%)", flush=True)
            if n % 100 == 0:
                json.dump(results, open(OUT, "w"), indent=2)
                print(f"  ... {n}/{len(work)} ({round((time.time()-t0)/60,1)}m)", flush=True)
    json.dump(results, open(OUT, "w"), indent=2)

    fails = [r for r in results if r.get("missing")]
    errs = [r for r in results if r.get("status") in ("timeout", "error")]
    clean = [r for r in results if r.get("status") == "ok" and not r.get("missing")]
    print(f"\n=== DONE: {len(results)} markets ===")
    print(f"  clean containment : {len(clean)}")
    print(f"  FAILURES (missing>0): {len(fails)}")
    print(f"  pull errors/timeouts: {len(errs)}")
    for r in sorted(fails, key=lambda x: -x["missing"])[:25]:
        print(f"    {r['slug'][:50]:50} missing={r['missing']:>5}/{r['trades_keys']:>5} "
              f"({r['missing_frac']*100:.1f}%)")
    print(f"  -> {OUT}")


if __name__ == "__main__":
    main()
