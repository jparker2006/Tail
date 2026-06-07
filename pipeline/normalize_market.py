"""Phase-1 Step 1.4 — normalize the tape into the canonical schema.

Fetches/caches raw receipts, decodes native maker/taker, collapses to token-0 space, derives
d / d_star / p_yes, builds per-wallet aggregates (taker vs maker), and caches the normalized
artifacts. Prints sanity checks before we filter MMs and attribute discovery.

Run:  .venv/bin/python pipeline/normalize_market.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import ingest
import onchain
import schema

SLUG = "biden-drops-out-in-july"
EXCHANGE = onchain.CTF_EXCHANGE_V1


def human(ts) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    tape = ingest.load_raw(f"{SLUG}_trades_taker.json")
    market = ingest.parse_market(ingest.load_raw(f"{SLUG}_market.json"))
    token_ids = market["clobTokenIds"]

    print(f"Decoding {len(tape)} fills (fetching raw receipts if not cached) ...")
    decoded = onchain.build_join(tape, token_ids, EXCHANGE, SLUG)

    fills, R = schema.normalize_fills(tape, decoded, market)
    wstats = schema.wallet_stats(fills)
    path = schema.price_path(fills)

    ingest.save_raw(f"{SLUG}_normalized_fills.json", fills)
    ingest.save_raw(f"{SLUG}_wallet_stats.json", wstats)
    ingest.save_raw(f"{SLUG}_price_path.json", path)

    # ---- sanity ----
    p0, pend = path[0][1], path[-1][1]
    n_takers = sum(1 for w in wstats.values() if w["n_taker"] > 0)
    n_makers = sum(1 for w in wstats.values() if w["n_maker"] > 0)
    n_pure_lp = sum(1 for w in wstats.values() if w["n_taker"] == 0 and w["n_maker"] > 0)
    role_known = sum(1 for f in fills if decoded.get(f["tx_hash"], {}).get("ok"))

    print("\n=== NORMALIZATION SANITY ===")
    print(f"  R_yes (token-0 truth)      : {R}   (winner = {market['outcomes'][market['resolved_outcome_index']]})")
    print(f"  fills normalized           : {len(fills)}   role-known {role_known}/{len(fills)}")
    print(f"  price path p0 -> p_end     : {p0:.3f} -> {pend:.3f}   "
          f"(truth-signed travel toward 1 = {(pend if R==1 else 1-pend) - (p0 if R==1 else 1-p0):+.3f})")
    print(f"  wallets: takers {n_takers} | makers {n_makers} | pure-LP (never aggress) {n_pure_lp}")

    print("\n  spot-check first 4 fills (oi, side -> p_yes, d, d_star):")
    for f in fills[:4]:
        print(f"    ts={human(f['ts'])} oi={f['outcome_index']} {f['raw_side']:>4} "
              f"raw_p={f['raw_price']:.3f} -> p_yes={f['p_yes']:.3f} d={f['d']:+d} "
              f"d_star={f['d_star']:+d} size={f['size']:.1f}")

    print("\n  top 6 wallets by gross_notional (flatness, aggressor_share):")
    top = sorted(wstats.items(), key=lambda kv: kv[1]["gross_notional"], reverse=True)[:6]
    print(f"    {'wallet':>14} {'gross$':>12} {'flatness':>9} {'aggr_sh':>8} {'nTake':>6} {'nMake':>6}  name")
    for addr, w in top:
        fl = f"{w['flatness']:.3f}" if w["flatness"] is not None else "  -  "
        ag = f"{w['aggressor_share']:.3f}" if w["aggressor_share"] is not None else "  -  "
        print(f"    {addr[:12]+'..':>14} {w['gross_notional']:>12,.0f} {fl:>9} {ag:>8} "
              f"{w['n_taker']:>6} {w['n_maker']:>6}  {w['name'] or ''}")


if __name__ == "__main__":
    main()
