"""Split-diagnostic on the un-truncated containment failures (legs-present-but-unmapped vs absent).

/trades is WHOLE on these markets, so a missing aggressor key is a no-alibi defect. With the RAW legs
in hand we can pinpoint the mechanism. For each missing /trades key (tx,wallet,token,side) we locate
the legs in that tx and classify:
  - NO leg in tx                      -> SOURCE UNDERCOUNT (leg absent at the source).
  - wallet is maker, taker==Exchange,
    but BOTH assets are tokens (no "0") -> UNMAPPED: token-for-token self-leg (map_aggressor_fills
                                           drops these at its `else: continue`) — a FIXABLE mapping bug.
  - wallet is maker, taker!=Exchange   -> UNMAPPED: self-leg names a non-Exchange taker (router/adapter).
  - wallet is maker, taker==Exchange,
    collateral present                 -> SHOULD have mapped (token/side mismatch) — inspect.
Reports the dominant mechanism per market + the distinct non-Exchange taker addresses (the signature).
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, sys.path[0] or "pipeline")
import subgraph


def _rows(o):
    return o["rows"] if isinstance(o, dict) and "rows" in o else o


def _key(r):
    return (str(r["transactionHash"]).lower(), str(r["proxyWallet"]).lower(),
            str(r["asset"]), str(r["side"]).upper())


def main() -> None:
    integ = json.load(open("data/out/corpus_integrity_untruncated.json"))
    fails = [r for r in integ if r.get("missing")]
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    byslug = {m["slug"]: m for m in prim + sec}

    summary = []
    for fr in sorted(fails, key=lambda x: -x["missing"]):
        slug = fr["slug"]
        m = byslug[slug]
        tokens = [str(t) for t in m["clobTokenIds"]]
        tokset = set(tokens)
        exch = (subgraph.NEGRISK_EXCHANGE_V1 if m.get("negRisk") else subgraph.CTF_EXCHANGE_V1)
        legs = subgraph.fetch_market_legs(tokens)
        # index legs by tx
        by_tx = {}
        for lg in legs:
            by_tx.setdefault(str(lg["transactionHash"]).lower(), []).append(lg)

        tr = _rows(json.load(open(f"data/raw/{slug}_taker.json")))
        K_tr = {_key(r) for r in tr}
        K_sg = {_key(r) for r in subgraph.map_aggressor_fills(legs, tokens, exch)}
        missing = K_tr - K_sg

        cls = Counter()
        nonexch_takers = Counter()
        for (tx, w, tok, side) in missing:
            lgs = by_tx.get(tx)
            if not lgs:
                cls["tx_absent (source undercount)"] += 1
                continue
            w_maker = [lg for lg in lgs if str(lg["maker"]).lower() == w]
            if not w_maker:
                cls["tx_present, wallet not a maker leg"] += 1
                continue
            tagged = False
            for lg in w_maker:
                tk = str(lg["taker"]).lower()
                ma, ta = str(lg["makerAssetId"]), str(lg["takerAssetId"])
                if tk == exch and ma != "0" and ta != "0":
                    cls["UNMAPPED: token-for-token self-leg (FIXABLE)"] += 1; tagged = True; break
                if tk != exch:
                    cls["UNMAPPED: self-leg taker != Exchange (FIXABLE)"] += 1
                    nonexch_takers[tk] += 1; tagged = True; break
                if tk == exch and (ma == "0" or ta == "0"):
                    cls["self-leg present w/ collateral (should map — inspect)"] += 1; tagged = True; break
            if not tagged:
                cls["other"] += 1
        dom = cls.most_common(1)[0][0] if cls else "n/a"
        summary.append({"slug": slug, "missing": len(missing), "breakdown": dict(cls),
                        "dominant": dom, "nonexch_takers": dict(nonexch_takers.most_common(5))})
        print(f"=== {slug[:50]} (missing {len(missing)}) ===")
        for k, v in cls.most_common():
            print(f"    {v:>4}  {k}")
        if nonexch_takers:
            print(f"    non-Exchange taker addrs: {dict(nonexch_takers.most_common(5))}")
        print()

    json.dump(summary, open("data/out/split_diagnostic_untruncated.json", "w"), indent=2)
    print("-> data/out/split_diagnostic_untruncated.json")


if __name__ == "__main__":
    main()
