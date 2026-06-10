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

# Free-tier recovery ceiling (A5 documented-exclusion of the extreme tail). The Goldsky free shard
# goes unresponsive under sustained recovery of the very biggest markets (verified: ~80k legs
# recovers reliably; ~430k+ persistently times out mid-recovery). To exclude ONLY genuine giants
# (never a recoverable mid-size market on a transient blip), exclusion is gated by LEG COUNT:
#   > MONSTER_LEGS : skip recovery outright (the 3 election monsters, 2.5-5M legs).
#   > GIANT_LEGS   : attempt, but a persistent timeout -> A5 documented coverage gap.
#   <= GIANT_LEGS  : full retry effort; a timeout is a transient blip to retry, NOT an exclusion.
GIANT_LEGS = 400_000
MONSTER_LEGS = 1_000_000

# A6 (amendment, 2026-06-09) — RELATIVE completeness tolerance. The subgraph's own
# `orderbook.tradesQuantity` counter over-counts the paginated `orderFilledEvents` tape by a stable
# 0.01–0.03% on some markets. Verified an indexer-counting artifact, NOT missing data: it reproduces
# on the quiet shard AND the plain (un-windowed) path, and getLogs on the smallest short-lived
# anomalous market (nba-mem-min, CTF) matches the PAGINATED legs, not tradesQuantity — so
# orderFilledEvents is the complete tape and tradesQuantity is the field that over-counts. A recovered
# tape is complete if it recovers ≥ (1−eps) of tradesQuantity. eps is set an order of magnitude above
# the largest observed artifact (0.03%) and ~1000× below the ~100% shortfall of a genuinely incomplete
# tape. The admitted set is INVARIANT for any eps in [0.03%, 50%] — gaps are bimodal (0, or 0.01–0.03%,
# or ~100%), so there is nothing in between to tune into. Frozen as a calibration RULE, never to outcomes.
COMPLETENESS_EPSILON = 0.001


def is_complete(n_legs: int, trades_quantity: int) -> bool:
    """A6 completeness: a non-empty tape recovering ≥ (1−COMPLETENESS_EPSILON) of tradesQuantity.
    Replaces the original exact-equality gate; tolerates ONLY the verified indexer-counting artifact."""
    return n_legs > 0 and n_legs >= trades_quantity * (1 - COMPLETENESS_EPSILON)

_session = requests.Session()
_session.headers.update({"User-Agent": "tail-research/0.1 (prediction-market study)",
                         "Content-Type": "application/json"})


def is_timeout(msg: str) -> bool:
    """A load-induced subgraph timeout (recoverable at lower concurrency) — Goldsky emits several
    wordings ('Query timed out', 'statement timeout', 'canceling statement due to ...'). Shared by
    the retry logic AND run_corpus's failure categorization so a timeout never masquerades as a bug.
    """
    s = msg.lower()
    return "timed out" in s or "timeout" in s or "canceling statement" in s


def _gq(query: str, variables: dict, max_retries: int = 8) -> dict:
    backoff = 1.0
    last = "unknown"          # remember WHY we kept retrying, so the final raise reflects the cause
    for _ in range(max_retries):
        try:
            r = _session.post(SUBGRAPH_EP, json={"query": query, "variables": variables},
                              timeout=60)
        except requests.RequestException as e:
            last = f"network error: {e}"
            time.sleep(backoff); backoff = min(backoff * 2, 30); continue
        if r.status_code in (429, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(backoff); backoff = min(backoff * 2, 30); continue
        j = r.json()
        if "errors" in j and not j.get("data"):
            msg = str(j["errors"])
            if is_timeout(msg):
                # load-induced: back off HARDER (don't hammer a loaded shard), ≥3s, grow to 45s
                last = msg[:90]
                time.sleep(max(backoff, 3.0)); backoff = min(backoff * 2, 45); continue
            raise RuntimeError(f"subgraph error: {j['errors'][:1]}")
        return j["data"]
    # surface the cause so is_timeout() (giant gate + run_corpus categorization) sees it
    raise RuntimeError(f"subgraph GET failed after retries: {last}")


_LEG_FIELDS = ("id transactionHash timestamp maker taker "
               "makerAssetId takerAssetId makerAmountFilled takerAmountFilled")


# Plain id_gt pagination DEGRADES on huge markets: the makerAssetId filter + id_gt scan grows as
# the cursor skips across sparse history (Trump-2024 = 5.1M legs, 0.4s→6s/page → timeout). Bounding
# each query to a timestamp WINDOW keeps the scan flat (~0.3s/page even deep into a dense window).
# But fill density is wildly non-uniform (months sparse, then millions in a day), so FIXED windows
# either over-window the sparse stretch or let a dense one go deep. So we ADAPTIVELY BISECT: a
# window is paginated up to MAX_PAGES_PER_WINDOW; if it hits the cap it's too dense and is split in
# time and re-processed, until every leaf window finishes shallow. Small markets skip all of this.
WINDOW_THRESHOLD = 30_000     # below this, plain (unwindowed) pagination is fine
MAX_PAGES_PER_WINDOW = 20     # a window needing more pages is too dense -> bisect by time
# (lowered 60->20 for the ~380k-leg free-tier-ceiling markets: shallower id-cursors per window keep
#  each page query light enough to clear the free Goldsky shard's per-query timeout. Operational
#  pagination tactic only — changes NO result, NO completeness/claim threshold.)


# Window-bound discovery uses orderBy:timestamp, which needs an (asset, timestamp) composite index.
# Goldsky indexes makerAssetId but NOT takerAssetId: on ~190k-row tokens, orderBy:timestamp
# where:{takerAssetId:$tok} times out even at first:1 on a fresh shard (verified — the SECOND wall
# behind the ~380k-leg timeouts, after cursor depth). So bounds are ALWAYS taken from the indexed
# field and reused for both passes — they only need to CONTAIN the legs (bisection adapts density;
# dedup makes an over-wide window harmless), and is_complete is the real completeness gate. Padded
# generously so a token's taker-side edge legs (a buy slightly outside the maker-side span) are kept.
TIME_PAD = 7 * 24 * 3600       # 7 days each side


def _field_time_range(field: str, tokens: list[str]):
    # single-token equality + orderBy:timestamp; raises (via _gq) if `field` lacks the composite index.
    q = ("query($a:String!){ orderFilledEvents(first:1, orderBy:timestamp, orderDirection:%s, "
         "where:{" + field + ":$a}){ timestamp } }")
    tmins, tmaxs = [], []
    for tok in tokens:
        lo = _gq(q % "asc", {"a": tok})["orderFilledEvents"]
        hi = _gq(q % "desc", {"a": tok})["orderFilledEvents"]
        if lo:
            tmins.append(int(lo[0]["timestamp"]))
        if hi:
            tmaxs.append(int(hi[0]["timestamp"]))
    if not tmins:
        return None, None
    return min(tmins), max(tmaxs)


def _indexed_time_range(tokens: list[str]):
    """[tmin, tmax] (padded) containing every leg, via whichever asset field carries the
    (asset, timestamp) index. makerAssetId first (the indexed one); fall back to takerAssetId only
    if maker has no legs/index. Returns (None, None) only if neither field yields a range."""
    for field in ("makerAssetId", "takerAssetId"):
        try:
            tmin, tmax = _field_time_range(field, tokens)
        except RuntimeError:                       # this field's orderBy:timestamp is index-less
            continue
        if tmin is not None:
            return tmin - TIME_PAD, tmax + TIME_PAD
    return None, None


def _fetch_window(field: str, tokens: list[str], legs: dict, t0, t1, pages: list,
                  maxpages: int | None) -> bool:
    """Paginate [t0,t1) by id_gt (or the whole field if t0 is None). Returns True if the window was
    exhausted, False if it must be BISECTED — either it hit `maxpages` (too dense to page shallow) OR
    a page query persistently TIMED OUT at this width. The timeout case is a DETERMINISTIC dense-
    window wall, not a transient blip: a hyper-dense stretch (e.g. everton's window at ~261k legs)
    times out at the exact same point every run, so retrying is futile — narrowing the window by time
    is the only fix, making each page cover fewer legs until it is light enough to serve. Bisect-on-
    timeout applies ONLY on the windowed path (maxpages set, so the caller CAN split); on the plain
    path a timeout still raises. Legs already added stay (dedup by id), so re-processing sub-windows
    only adds redundant fetches, never drops a leg."""
    win = "" if t0 is None else ", timestamp_gte:$t0, timestamp_lt:$t1"
    decl = "" if t0 is None else ", $t0:BigInt!, $t1:BigInt!"
    q = ("query($t:[String!], $l:ID!" + decl + "){ orderFilledEvents(first:1000, orderBy:id, "
         "where:{" + field + "_in:$t" + win + ", id_gt:$l}){ " + _LEG_FIELDS + " } }")
    last, local = "", 0
    while True:
        v = {"t": tokens, "l": last}
        if t0 is not None:
            v["t0"], v["t1"] = t0, t1
        try:
            rows = _gq(q, v)["orderFilledEvents"]
        except RuntimeError as e:
            if maxpages is not None and is_timeout(str(e)):
                return False          # too dense to serve at this width — caller bisects by time
            raise
        if not rows:
            return True
        for r in rows:
            legs[r["id"]] = r
        last = rows[-1]["id"]
        pages[0] += 1
        local += 1
        if pages[0] % 50 == 0:        # heartbeat for big recoveries (mega-market visibility)
            print(f"    [subgraph] {len(legs):,} legs ({pages[0]} pages)", flush=True)
        if len(rows) < 1000:
            return True
        if maxpages is not None and local >= maxpages:
            return False              # too dense — caller splits this window by time


def fetch_market_legs(token_ids, total_legs: int | None = None) -> list[dict]:
    """Every OrderFilled leg touching this market's tokens, complete (cursor-paged, no cap).

    Unions makerAssetId_in / takerAssetId_in (a token can sit on either side) and dedups by leg id.
    Large markets recover via ADAPTIVE timestamp-window bisection so every query stays shallow
    regardless of density.
    """
    tokens = [str(t) for t in token_ids]
    if total_legs is None:
        total_legs = orderbook_aggregate(token_ids)["trades_quantity"]
    legs: dict[str, dict] = {}
    pages = [0]
    if total_legs < WINDOW_THRESHOLD:                    # small market: plain, uncapped pagination
        for field in ("makerAssetId", "takerAssetId"):
            _fetch_window(field, tokens, legs, None, None, pages, None)
        return list(legs.values())
    # window bounds taken ONCE from the indexed field, reused for both passes (takerAssetId's
    # orderBy:timestamp is index-less at scale). Pagination below is orderBy:id (always indexed).
    tmin, tmax = _indexed_time_range(tokens)
    if tmin is None:                                     # neither field yields a range: plain fallback
        for field in ("makerAssetId", "takerAssetId"):
            _fetch_window(field, tokens, legs, None, None, pages, None)
        return list(legs.values())
    for field in ("makerAssetId", "takerAssetId"):
        stack = [(tmin, tmax + 1)]                       # adaptive: bisect any window that caps out
        while stack:
            a, b = stack.pop()
            if _fetch_window(field, tokens, legs, a, b, pages, MAX_PAGES_PER_WINDOW) or b - a <= 1:
                continue
            mid = (a + b) // 2
            stack.append((mid, b))
            stack.append((a, mid))                       # process earlier half first (LIFO)
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
    agg = orderbook_aggregate(token_ids)
    legs = fetch_market_legs(token_ids, total_legs=agg["trades_quantity"])  # reuse count for windowing
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
