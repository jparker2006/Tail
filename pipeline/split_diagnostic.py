"""Split-diagnostic for containment failures: mapping-gap vs source-undercount (cache-only).

For each market's MISSING /trades aggressor keys, ask where the leg went:
  - tx PRESENT in the subgraph's full (maker-inclusive) tape  -> the leg WAS recovered but our
    aggressor self-leg detection didn't map it -> MAPPING-LOGIC GAP (fixable in code, recovers the
    market). If the exact (tx,wallet) is present as a maker-rendered row, stronger still.
  - tx ABSENT from the full tape -> the subgraph never indexed that fill -> SOURCE UNDERCOUNT
    (needs getLogs confirmation or exclusion).
Per-market verdict = where the mass of missing keys lands.
"""
import json
import os

RAW = "data/raw"
FAILURES = [
    "will-trump-visit-china-by-may-15-835-774-595",
    "us-x-iran-ceasefire-extended-by-april-22-2026",
    "megaeth-market-cap-fdv-1pt5b-one-day-after-launch-371-844-879-681",
    "will-the-next-prime-minister-of-hungary-be-pter-marki-zay",
    "will-the-next-prime-minister-of-hungary-be-istvn-kollr",
    "will-roberto-snchez-palomino-finish-in-second-place-in-the-peru-presidential-election",
    "will-the-next-prime-minister-of-hungary-be-viktor-orbn",
    "will-rafael-lpez-aliaga-finish-in-second-place-in-the-peru-presidential-election",
    "us-escorts-commercial-ship-through-hormuz-by-april-30-894",
    "will-the-next-prime-minister-of-hungary-be-lszl-toroczkai",
    "will-jake-paul-win-his-boxing-match-against-anthony-joshua",
]


def _rows(o):
    return o["rows"] if isinstance(o, dict) and "rows" in o else o


def _key(r):
    return (str(r["transactionHash"]).lower(), str(r["proxyWallet"]).lower(),
            str(r["asset"]), str(r["side"]).upper())


def _resolve(slug):
    if os.path.exists(f"{RAW}/{slug}_subgraph.json"):
        return slug
    cands = [f[:-len("_subgraph.json")] for f in os.listdir(RAW)
             if f.endswith("_subgraph.json") and slug[:40] in f]
    return cands[0] if cands else None


def main() -> None:
    out = []
    for want in FAILURES:
        slug = _resolve(want)
        if not slug:
            print(f"  {want[:45]}: cache not found"); continue
        d = json.load(open(f"{RAW}/{slug}_subgraph.json"))
        tr = _rows(json.load(open(f"{RAW}/{slug}_taker.json")))
        K_tr = {_key(r) for r in tr}
        K_sg_taker = {_key(r) for r in d["taker"]}
        full = d["full"]
        full_tx = {str(r["transactionHash"]).lower() for r in full}
        full_keys = {_key(r) for r in full}

        missing = K_tr - K_sg_taker
        n = len(missing)
        tx_present = sum(1 for k in missing if k[0] in full_tx)       # leg's tx recovered
        key_in_full = sum(1 for k in missing if k in full_keys)       # exact fill present (mis-mapped)
        tx_absent = n - tx_present
        verdict = ("MAPPING GAP (legs recovered, unmapped)" if tx_present >= 0.8 * n
                   else "SOURCE UNDERCOUNT (legs absent)" if tx_absent >= 0.8 * n
                   else "MIXED")
        out.append({"slug": slug, "missing": n, "tx_present": tx_present,
                    "key_in_full": key_in_full, "tx_absent": tx_absent, "verdict": verdict})
        print(f"{slug[:46]:46} missing={n:>5} | tx_present={tx_present:>5} "
              f"(exact_in_full={key_in_full:>5}) | tx_absent={tx_absent:>5} -> {verdict}")
    json.dump(out, open("data/out/split_diagnostic.json", "w"), indent=2)
    print("\n-> data/out/split_diagnostic.json")
    mg = [r for r in out if "MAPPING" in r["verdict"]]
    su = [r for r in out if "SOURCE" in r["verdict"]]
    mx = [r for r in out if r["verdict"] == "MIXED"]
    print(f"summary: mapping-gap={len(mg)}  source-undercount={len(su)}  mixed={len(mx)}")


if __name__ == "__main__":
    main()
