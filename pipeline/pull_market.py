"""Phase-1 Step 1.2 — pull & cache the raw trade tape for the chosen market.

Pulls Gamma metadata, the full /trades tape (split by side to beat the offset ceiling), a
takerOnly=false sample for comparison, and /holders. Caches raw JSON under data/raw/ and
prints a characterization so we can confirm the tape is complete and sane before normalizing.

Run:  .venv/bin/python pipeline/pull_market.py
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import ingest

SLUG = "biden-drops-out-in-july"
CONDITION_ID = "0xb124766234e1f19bc156a0edfb492f8c4cc3fa25303e722ad52780b66a3b70df"


def human(ts) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def characterize(trades: list[dict], m: dict) -> None:
    n = len(trades)
    wallets = {t.get("proxyWallet") for t in trades if t.get("proxyWallet")}
    ts = [int(t["timestamp"]) for t in trades if t.get("timestamp") is not None]
    prices = [float(t["price"]) for t in trades if t.get("price") is not None]
    sides = Counter(t.get("side") for t in trades)
    by_outcome = Counter(t.get("outcomeIndex") for t in trades)
    by_asset = Counter(t.get("asset") for t in trades)
    notional = sum(float(t.get("price", 0)) * float(t.get("size", 0)) for t in trades)
    days = {datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in ts}

    # First/last price by time (executed path endpoints).
    by_time = sorted(trades, key=lambda t: int(t.get("timestamp", 0)))
    first_p = float(by_time[0]["price"]) if by_time else None
    last_p = float(by_time[-1]["price"]) if by_time else None

    print("\n=== TAPE CHARACTERIZATION ===")
    print(f"  market           : {m.get('question')}  ({SLUG})")
    print(f"  conditionId      : {m.get('conditionId')}")
    print(f"  outcomes         : {m.get('outcomes')}  prices {m.get('outcomePrices')}  "
          f"-> winner idx {m.get('resolved_outcome_index')}")
    print(f"  total fills       : {n}")
    print(f"  distinct wallets  : {len(wallets)}")
    print(f"  time span         : {human(min(ts))}  ->  {human(max(ts))}  ({len(days)} days)")
    print(f"  side counts       : {dict(sides)}")
    print(f"  outcomeIndex split: {dict(by_outcome)}")
    print(f"  asset (token) split: {dict(by_asset)}")
    print(f"  price range       : [{min(prices):.4f}, {max(prices):.4f}]")
    print(f"  first/last by time: {first_p:.4f}  ->  {last_p:.4f}")
    print(f"  gross notional    : ${notional:,.0f}")


def main() -> None:
    print(f"Fetching Gamma metadata for {SLUG} ...")
    # /markets defaults to active-only; this market is resolved, so pass closed=true.
    mkts = ingest.gamma_markets(condition_ids=CONDITION_ID, closed="true")
    if not mkts:
        raise SystemExit(f"market {CONDITION_ID} not found on Gamma")
    raw_market = mkts[0]
    m = ingest.parse_market(raw_market)
    ingest.save_raw(f"{SLUG}_market.json", raw_market)
    cid = m["conditionId"]
    print(f"  conditionId = {cid}")
    print(f"  clobTokenIds = {m['clobTokenIds']}")

    print("\nPulling full taker tape (split by side) ...")
    taker, meta = ingest.pull_all_trades(cid, taker_only=True)
    ingest.save_raw(f"{SLUG}_trades_taker.json", taker)
    print(f"  taker tape: {meta}")

    print("\nPulling full takerOnly=false tape (includes maker-side rows) ...")
    full, full_meta = ingest.pull_all_trades(cid, taker_only=False)
    ingest.save_raw(f"{SLUG}_trades_all.json", full)
    print(f"  full tape: {full_meta}")
    # Is the taker tape a subset of the full tape? (key = tx + asset + wallet)
    key = lambda t: (t.get("transactionHash"), t.get("asset"), t.get("proxyWallet"))
    taker_keys = {key(t) for t in taker}
    full_keys = {key(t) for t in full}
    inboth = len(taker_keys & full_keys)
    print(f"  taker rows: {len(taker_keys)} | full rows: {len(full_keys)} | "
          f"taker∩full: {inboth} ({100*inboth/max(len(taker_keys),1):.1f}% of taker in full)")
    print(f"  rows in full but NOT in taker (candidate maker-side rows): "
          f"{len(full_keys - taker_keys)}")

    print("\nPulling holders ...")
    holders = ingest.data_holders(cid)
    ingest.save_raw(f"{SLUG}_holders.json", holders)
    print(f"  holders objects: {len(holders)} "
          f"(per-token holder counts: {[len(h.get('holders', [])) for h in holders]})")

    characterize(taker, m)

    if meta["truncated"]:
        print("\n  !! WARNING: a side hit the offset ceiling still returning full pages -> "
              "tape may be TRUNCATED. Finer splitting or on-chain backfill needed.")
    else:
        print("\n  OK: every side paged out to a short final page -> tape is COMPLETE "
              "within the Data API.")


if __name__ == "__main__":
    main()
