"""Subgraph transport — the COMPLETE per-market aggressor tape (Phase-2 de-truncation).

The Data API `/trades` hard-caps at 4000 rows per (market, side) = 8000/market, returned
recency-first, so high-volume V1 markets come back truncated AND time-biased (e.g. nba-okc kept
only the closing 7% of its timeline). The Goldsky orderbook subgraph indexes the full V1 era
(earliest fill 2022-11-21 .. latest 2026-04-28, the V1->V2 migration cutoff that bounds our
corpus) with cursor pagination (id_gt, no offset cap), so it yields the COMPLETE tape.

The subgraph records `OrderFilled` per order: resting-maker legs (maker=LP, taker=aggressor)
plus the aggressor's own self-leg (maker=aggressor, taker=the Exchange contract). We map those
legs into the SAME canonical taker-oriented aggressor fills `/trades` gives, identifying the
aggressor exactly as `onchain.decode_receipt` does — the wallet whose own order leg has
taker == Exchange (== OrdersMatched.takerOrderMaker). The resulting tape is a drop-in,
de-truncated replacement, validated fill-for-fill against `/trades` on an un-truncated market
(bar 1) and against on-chain getLogs on the beyond-ceiling fills (bar 2) before it is trusted.

Reconciliation is on RAW INTEGER token amounts (6-dp micro-units), never decimal-scaled floats,
so float precision can't manufacture spurious mismatches.
"""
from __future__ import annotations

import time

import requests

# ob-0.0.1: covers the full V1 window. (The 'resync' instance is stale — stops 2026-01-05.)
SUBGRAPH_EP = ("https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw"
               "/subgraphs/orderbook-subgraph/0.0.1/gn")

# V1 settlement contracts on Polygon — the aggressor's self-leg names one of these as `taker`.
CTF_EXCHANGE_V1 = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"      # binary (negRisk=False)
NEGRISK_EXCHANGE_V1 = "0xc5d563a36ae78145c45a50134d48a1215220f80a"  # negRisk=True
EXCHANGES = {CTF_EXCHANGE_V1, NEGRISK_EXCHANGE_V1}

# A5 Gamma cross-check (loose secondary backstop). Calibrated from known-complete markets across
# both classes, admitting the worst-case definitional gap; see data/out/gamma_calibration.json.
# One-sided: flag (NOT auto-exclude) a recovered market whose on-chain collateral / Gamma volume
# falls below this — a possible gross subgraph omission for a getLogs spot-check.
GAMMA_TOL_LOW = 0.0069

_session = requests.Session()
_session.headers.update({"User-Agent": "tail-research/0.1 (prediction-market study)",
                         "Content-Type": "application/json"})


def _gq(query: str, variables: dict, max_retries: int = 6) -> dict:
    backoff = 1.0
    for _ in range(max_retries):
        try:
            r = _session.post(SUBGRAPH_EP, json={"query": query, "variables": variables},
                              timeout=60)
        except requests.RequestException:
            time.sleep(backoff); backoff = min(backoff * 2, 30); continue
        if r.status_code in (429, 502, 503, 504):
            time.sleep(backoff); backoff = min(backoff * 2, 30); continue
        j = r.json()
        if "errors" in j and not j.get("data"):
            msg = str(j["errors"])
            if "statement timeout" in msg or "canceling statement" in msg:
                # load-induced: back off HARDER (don't hammer a loaded shard), ≥3s, grow to 45s
                time.sleep(max(backoff, 3.0)); backoff = min(backoff * 2, 45); continue
            raise RuntimeError(f"subgraph error: {j['errors'][:1]}")
        return j["data"]
    raise RuntimeError("subgraph GET failed after retries")


_LEG_FIELDS = ("id transactionHash timestamp maker taker "
               "makerAssetId takerAssetId makerAmountFilled takerAmountFilled")


def fetch_market_legs(token_ids) -> list[dict]:
    """Every OrderFilled leg touching this market's tokens, complete (cursor-paged, no cap).

    A market token can sit on either side of a fill, so we union makerAssetId_in and
    takerAssetId_in and dedup by leg id.
    """
    tokens = [str(t) for t in token_ids]
    legs: dict[str, dict] = {}
    pages = 0
    for field in ("makerAssetId", "takerAssetId"):
        q = ("query($t:[String!],$last:ID!){ orderFilledEvents(first:1000, orderBy:id, "
             "where:{" + field + "_in:$t, id_gt:$last}){ " + _LEG_FIELDS + " } }")
        last = ""
        while True:
            rows = _gq(q, {"t": tokens, "last": last})["orderFilledEvents"]
            if not rows:
                break
            for r in rows:
                legs[r["id"]] = r
            last = rows[-1]["id"]
            pages += 1
            if pages % 50 == 0:        # heartbeat for big recoveries (mega-market visibility)
                print(f"    [subgraph] {len(legs):,} legs ({pages} pages, {tokens[0][:10]}…)",
                      flush=True)
            if len(rows) < 1000:
                break
    return list(legs.values())


def map_aggressor_fills(legs: list[dict], token_ids, exchange: str) -> list[dict]:
    """Map raw OrderFilled rows -> canonical taker-oriented aggressor fills.

    The aggressor's fill is read from its SELF-LEG — the OrderFilled whose taker is the Exchange
    contract and whose maker is the aggressor (== OrdersMatched.takerOrderMaker). The self-leg
    encodes the aggressor's own order directly (collateral-for-token or token-for-collateral),
    so it is correct under both ordinary maker matches AND the mint/merge mechanic, where the
    counterparty leg names the *complementary* token and would mis-attribute. (The leg where the
    aggressor is the `taker` is the counterparty/LP leg — NOT used; that was the bug bar 1
    caught.) We aggregate self-legs by (tx, wallet, token, side) to match /trades granularity,
    in raw 6-dp integer units. Mirrors onchain.decode_receipt.
    """
    tokens = {str(t) for t in token_ids}
    fills: dict[tuple, dict] = {}
    for leg in legs:
        if leg["taker"].lower() != exchange:       # keep only aggressor self-legs
            continue
        aggressor = leg["maker"].lower()
        m_asset, t_asset = str(leg["makerAssetId"]), str(leg["takerAssetId"])
        m_amt, t_amt = int(leg["makerAmountFilled"]), int(leg["takerAmountFilled"])
        if m_asset == "0" and t_asset in tokens:        # aggressor paid collateral -> BUY token
            token, side, shares, collat = t_asset, "BUY", t_amt, m_amt
        elif t_asset == "0" and m_asset in tokens:      # aggressor received collateral -> SELL
            token, side, shares, collat = m_asset, "SELL", m_amt, t_amt
        else:
            continue
        key = (leg["transactionHash"], aggressor, token, side)
        f = fills.setdefault(key, {"transactionHash": leg["transactionHash"],
                                   "proxyWallet": aggressor, "asset": token, "side": side,
                                   "shares_int": 0, "collateral_int": 0,
                                   "timestamp": int(leg["timestamp"])})
        f["shares_int"] += shares
        f["collateral_int"] += collat
    return list(fills.values())


def orderbook_aggregate(token_ids) -> dict:
    """The subgraph's OWN per-market aggregate (indexer-computed, independent of our pagination).

    Σ tradesQuantity over the market's tokens == the total OrderFilled leg count. Comparing it to
    the number of legs we paginated is an exact, free check that our pagination was complete — the
    silent-omission trigger for A5's exclude branch.
    """
    tokens = [str(t) for t in token_ids]
    q = ("query($ids:[ID!]){ orderbooks(where:{id_in:$ids}){ id tradesQuantity "
         "scaledCollateralVolume } }")
    obs = _gq(q, {"ids": tokens})["orderbooks"]
    return {"trades_quantity": sum(int(o["tradesQuantity"]) for o in obs),
            "scaled_collateral_volume": sum(float(o["scaledCollateralVolume"]) for o in obs),
            "n_orderbooks": len(obs),
            "per_token": {o["id"]: int(o["tradesQuantity"]) for o in obs}}


def fetch_market_legs_checked(token_ids) -> tuple[list[dict], dict]:
    """Complete legs + a completeness verdict vs the subgraph's own tradesQuantity aggregate.

    `complete` False => our pagination under-read the subgraph (NOT the subgraph missing data);
    such a market is flagged for re-pull / getLogs spot-check / the A5 exclude branch.
    """
    legs = fetch_market_legs(token_ids)
    agg = orderbook_aggregate(token_ids)
    meta = {"n_legs": len(legs), "trades_quantity": agg["trades_quantity"],
            "scaled_collateral_volume": agg["scaled_collateral_volume"],
            "complete": bool(len(legs) == agg["trades_quantity"])}
    return legs, meta


def market_tape(token_ids, exchange: str) -> list[dict]:
    """Convenience: complete canonical aggressor tape for a market (raw-integer fills)."""
    return map_aggressor_fills(fetch_market_legs(token_ids), token_ids, exchange)


def market_rows(token_ids, exchange: str, taker_only: bool, legs=None) -> list[dict]:
    """Complete tape as `/trades`-shaped rows — a drop-in for `ingest.pull_all_trades` on
    truncated markets (A5). `token_ids` MUST be canonical order [outcome-0, outcome-1].

    Each OrderFilled leg is rendered from its MAKER's perspective (maker gives makerAsset,
    receives takerAsset):
      taker_only=True  -> only the aggressor self-legs (taker == Exchange, maker == aggressor):
                          the aggressor tape (== map_aggressor_fills, validated bar 1/2).
      taker_only=False -> every leg: the maker-inclusive flatness substrate — self-legs give the
                          aggressor's fill, resting-maker legs give each LP's fill (one pull,
                          both views). Rows feed schema.normalize_fills unchanged.
    """
    idx = {str(t): i for i, t in enumerate(token_ids)}
    ex = exchange.lower()
    legs = legs if legs is not None else fetch_market_legs(token_ids)
    # aggregate legs to /trades granularity: one row per (tx, wallet, token, side)
    acc: dict[tuple, dict] = {}
    for leg in legs:
        if taker_only and leg["taker"].lower() != ex:
            continue
        wallet = leg["maker"].lower()
        m_asset, t_asset = str(leg["makerAssetId"]), str(leg["takerAssetId"])
        m_amt, t_amt = int(leg["makerAmountFilled"]), int(leg["takerAmountFilled"])
        if m_asset in idx and t_asset == "0":        # maker GAVE token -> SELL it
            token, side, shares, collat = m_asset, "SELL", m_amt, t_amt
        elif t_asset in idx and m_asset == "0":      # maker RECEIVED token -> BUY it
            token, side, shares, collat = t_asset, "BUY", t_amt, m_amt
        else:
            continue
        key = (leg["transactionHash"], wallet, token, side)
        a = acc.setdefault(key, {"shares": 0, "collat": 0, "ts": int(leg["timestamp"])})
        a["shares"] += shares
        a["collat"] += collat
        a["ts"] = min(a["ts"], int(leg["timestamp"]))
    return [{"proxyWallet": w, "asset": tok, "outcomeIndex": idx[tok], "side": side,
             "size": a["shares"] / 1e6, "price": (a["collat"] / a["shares"]) if a["shares"] else 0.0,
             "transactionHash": tx, "timestamp": a["ts"]}
            for (tx, w, tok, side), a in acc.items()]
