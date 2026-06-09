"""A6 premise confirmation (NOT go/no-go) — on-chain getLogs on the smallest short-lived anomalous
market (default nba-mem-min, CTF, ~6.4-day span). Confirms the on-chain OrderFilled count for the
market's tokens equals the PAGINATED subgraph legs (n_legs), NOT the indexer's tradesQuantity. That
establishes orderFilledEvents is the complete tape and tradesQuantity is the field that over-counts —
the whole basis of the A6 tolerance. If getLogs matches tradesQuantity instead, the subgraph MISSED
legs: STOP and report (the tape would be incomplete, not over-counted).
"""
import json
import sys

sys.path.insert(0, sys.path[0] or "pipeline")
import onchain
import subgraph

SLUG = sys.argv[1] if len(sys.argv) > 1 else "nba-mem-min-2025-12-17"
PAD = 2000  # block pad each side — token filter makes over-scanning harmless, guards edge legs


def block_at(ts_target: int, lo: int, hi: int) -> int:
    """Last block with timestamp <= ts_target (binary search via eth_getBlockByNumber)."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        b = onchain.rpc_call("eth_getBlockByNumber", [hex(mid), False], retry_on_null=True)
        if int(b["timestamp"], 16) <= ts_target:
            lo = mid
        else:
            hi = mid - 1
    return lo


def main() -> None:
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    m = next(x for x in prim + sec if x["slug"] == SLUG)
    tokens = [str(t) for t in m["clobTokenIds"]]
    exch = subgraph.NEGRISK_EXCHANGE_V1 if m.get("negRisk") else subgraph.CTF_EXCHANGE_V1
    cache = json.load(open(f"data/raw/{SLUG}_subgraph.json"))
    n_legs, tq = cache["meta"]["n_legs"], cache["meta"]["trades_quantity"]
    ts = [int(r["timestamp"]) for r in cache["full"]]
    tmin, tmax = min(ts), max(ts)

    latest = int(onchain.rpc_call("eth_blockNumber", []), 16)
    print(f"{SLUG}: negRisk={m.get('negRisk')} exch={exch[:10]}.. "
          f"ts {tmin}..{tmax} ({(tmax-tmin)/86400:.1f}d); locating blocks (latest={latest:,})…",
          flush=True)
    from_block = max(1, block_at(tmin, 1, latest) - PAD)
    to_block = block_at(tmax, 1, latest) + PAD
    span = to_block - from_block
    print(f"block range: {from_block:,}..{to_block:,} ({span:,} blocks)", flush=True)

    def prog(end, to, seen, kept):
        print(f"  getLogs {100*(end-from_block)/max(1,span):5.1f}%  scanned~{seen:,} kept={kept:,}",
              flush=True)

    legs = onchain.fetch_orderfilled_logs(exch, from_block, to_block, token_ids=tokens,
                                          chunk=1000, on_progress=prog)
    gl = len(legs)
    if gl == n_legs:
        verdict = "CONFIRMS recovered tape (orderFilledEvents complete; tradesQuantity over-counts)"
    elif gl == tq:
        verdict = "MATCHES tradesQuantity — STOP: subgraph MISSED legs, tape is INCOMPLETE"
    else:
        verdict = f"UNEXPECTED count {gl:,} (neither n_legs nor tq)"
    print(f"\n=== A6 getLogs confirmation: {SLUG} ===")
    print(f"  on-chain getLogs legs : {gl:,}")
    print(f"  subgraph paginated    : {n_legs:,}  (the recovered tape)")
    print(f"  tradesQuantity        : {tq:,}  (indexer counter)  gap={tq-n_legs}")
    print(f"  -> {verdict}", flush=True)
    json.dump({"slug": SLUG, "exchange": exch, "from_block": from_block, "to_block": to_block,
               "getlogs_legs": gl, "subgraph_n_legs": n_legs, "tradesQuantity": tq,
               "confirms_recovered": gl == n_legs, "matches_tradesquantity": gl == tq},
              open("data/out/a6_getlogs_confirmation.json", "w"), indent=2)
    print("  -> data/out/a6_getlogs_confirmation.json", flush=True)


if __name__ == "__main__":
    main()
