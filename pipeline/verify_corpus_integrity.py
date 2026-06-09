"""Corpus-wide tape-integrity pass — truncated arm (cache-only, no shard load).

For every market with a recovered subgraph tape (n_legs>0), two complementary checks:
  (1) KEY-CONTAINMENT  — every /trades aggressor key (tx,wallet,token,side) must be in the subgraph
      aggressor tape. On truncated markets /trades is itself a (recency-biased) SAMPLE, so this is a
      NECESSARY-but-partial check: a sampled key that's missing proves a mapping gap / source
      undercount; passing does not prove completeness (the un-sampled region is untested).
  (2) GAMMA volume cross-check — recovered on-chain collateral / Gamma volume (`scv_over_gamma`)
      vs GAMMA_TOL_LOW. The external backstop for undercounts the truncated /trades can't expose.

A market is clean iff containment holds AND gamma is not flagged. Flagged markets feed the
split-diagnostic (legs-present-but-unmapped = fixable mapping gap; legs-absent = source undercount).
The un-truncated arm (containment where /trades is whole, needs fresh pulls) runs separately.
"""
import glob
import json
import os
import sys

sys.path.insert(0, sys.path[0] or "pipeline")
import subgraph

RAW = "data/raw"
SUFFIX = "_subgraph.json"


def _rows(o):
    return o["rows"] if isinstance(o, dict) and "rows" in o else o


def _keys(rs):
    return {(str(r["transactionHash"]).lower(), str(r["proxyWallet"]).lower(),
             str(r["asset"]), str(r["side"]).upper()) for r in rs}


def main() -> None:
    files = sorted(glob.glob(f"{RAW}/*{SUFFIX}"))
    checked = 0
    contain_fail, gamma_fail, no_trades = [], [], 0
    for f in files:
        slug = os.path.basename(f)[: -len(SUFFIX)]
        d = json.load(open(f))
        meta = d.get("meta", {})
        if not meta.get("n_legs"):                       # giants (n_legs=0) — nothing recovered
            continue
        tpath = f"{RAW}/{slug}_taker.json"
        if not os.path.exists(tpath):
            no_trades += 1
            continue
        checked += 1
        K_tr = _keys(_rows(json.load(open(tpath))))
        K_sg = _keys(d["taker"])
        missing = len(K_tr - K_sg)
        scv = meta.get("scv_over_gamma")
        if missing > 0:
            contain_fail.append({"slug": slug, "trades_keys": len(K_tr), "sg_keys": len(K_sg),
                                 "missing": missing, "missing_frac": round(missing / max(1, len(K_tr)), 4),
                                 "scv_over_gamma": scv})
        if scv is not None and scv < subgraph.GAMMA_TOL_LOW:
            gamma_fail.append({"slug": slug, "scv_over_gamma": scv})

    print(f"=== corpus integrity — TRUNCATED arm (cache-only) ===")
    print(f"  markets with recovered tape checked : {checked}  (skipped {no_trades} w/o /trades cache)")
    print(f"  CONTAINMENT failures (missing>0)    : {len(contain_fail)}")
    print(f"  GAMMA failures (scv/vol < {subgraph.GAMMA_TOL_LOW}) : {len(gamma_fail)}")
    if contain_fail:
        print("\n  containment failures (sorted by missing):")
        for r in sorted(contain_fail, key=lambda x: -x["missing"]):
            print(f"    {r['slug'][:50]:50} missing={r['missing']:>6} / {r['trades_keys']:>6} "
                  f"({r['missing_frac']*100:.1f}%)  sg_keys={r['sg_keys']}  scv/vol={r['scv_over_gamma']}")
    if gamma_fail:
        print("\n  gamma failures:")
        for r in gamma_fail:
            print(f"    {r['slug'][:50]:50} scv/vol={r['scv_over_gamma']}")
    json.dump({"checked": checked, "containment_failures": contain_fail, "gamma_failures": gamma_fail},
              open("data/out/corpus_integrity_truncated.json", "w"), indent=2)
    print("\n  -> data/out/corpus_integrity_truncated.json")


if __name__ == "__main__":
    main()
