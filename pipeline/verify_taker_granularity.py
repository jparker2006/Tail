"""One-step granularity check on the 3 taker-mapping anomalies.

The gate `n_taker >= n_trades_taker` pits the subgraph's AGGREGATED aggressor tape (one row per
(tx,wallet,token,side)) against the RAW, sometimes-truncated `/trades` row count — built to mismatch.
The correct comparison is on KEYS:
  - /trades COMPLETE   -> aggregated /trades keys == subgraph aggressor keys (EQUALITY).
  - /trades TRUNCATED  -> aggregated /trades keys (subset) ⊆ subgraph aggressor keys (CONTAINMENT);
                          the subgraph legitimately holds MORE (the truncated-away fills).
Read trades_truncated per market; apply the right relation. If all pass, the tapes are complete and
correctly mapped and the raw-row-count gate is the bug.
"""
import json
import os

RAW = "data/raw"
SLUGS = [
    "will-trump-visit-china-by-may-15-835-774-595",
    "megaeth-market-cap-fdv-1pt5b-one-day-after-launch-371-844-879-681",
    "us-escorts-commercial-ship-through-hormuz-by-april-30-894",
]


def _rows(obj):
    return obj["rows"] if isinstance(obj, dict) and "rows" in obj else obj


def _keys(rows):
    """Set of (tx, wallet, token, side), normalized."""
    out = set()
    for r in rows:
        out.add((str(r["transactionHash"]).lower(), str(r["proxyWallet"]).lower(),
                 str(r["asset"]), str(r["side"]).upper()))
    return out


def main() -> None:
    results, all_pass = [], True
    for slug in SLUGS:
        trades = _rows(json.load(open(f"{RAW}/{slug}_taker.json")))
        sg_taker = json.load(open(f"{RAW}/{slug}_subgraph.json"))["taker"]
        truncated = json.load(open(f"{RAW}/results/{slug}.json")).get("trades_truncated")

        K_tr, K_sg = _keys(trades), _keys(sg_taker)
        missing = K_tr - K_sg          # /trades keys NOT in subgraph (should be 0 either way)
        extra = K_sg - K_tr            # subgraph keys beyond /trades (the de-truncated fills)

        if truncated:
            relation = "CONTAINMENT (/trades ⊆ subgraph)"
            ok = (len(missing) == 0)   # subset; subgraph holds >= as many, typically more
        else:
            relation = "EQUALITY (/trades == subgraph)"
            ok = (len(missing) == 0 and len(extra) == 0)
        all_pass &= ok
        results.append({"slug": slug, "trades_truncated": truncated, "relation": relation,
                        "raw_trades_rows": len(trades), "trades_unique_keys": len(K_tr),
                        "subgraph_aggressor_keys": len(K_sg),
                        "trades_keys_missing_from_subgraph": len(missing),
                        "subgraph_extra_keys": len(extra), "pass": ok})
        print(f"=== {slug[:52]} ===")
        print(f"  trades_truncated={truncated}  -> {relation}")
        print(f"  raw /trades rows           : {len(trades):,}")
        print(f"  /trades UNIQUE keys        : {len(K_tr):,}   (vs raw count — the granularity collapse)")
        print(f"  subgraph aggressor keys    : {len(K_sg):,}")
        print(f"  /trades keys MISSING from subgraph : {len(missing)}   (must be 0)")
        print(f"  subgraph EXTRA keys (de-truncated) : {len(extra):,}")
        print(f"  -> {'PASS' if ok else 'FAIL'}\n")

    print(f"=== VERDICT: {'ALL PASS' if all_pass else 'NOT all pass'} ===")
    if all_pass:
        print("  Tapes complete + correctly mapped. The raw-/trades-row-count comparison is the bug;")
        print("  admit all 3 and stop using it as the aggressor-completeness reference.")
    json.dump({"all_pass": all_pass, "markets": results},
              open("data/out/taker_granularity_check.json", "w"), indent=2)
    print("  -> data/out/taker_granularity_check.json")


if __name__ == "__main__":
    main()
