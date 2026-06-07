"""Data ingestion — Gamma + Data API pulls and the on-chain role join.

Responsibilities (Phase 1, Steps 1.1–1.3):
- Gamma API: resolve a market to conditionId, clobTokenIds, outcomes, outcomePrices
  (resolution truth), volumeNum, negRisk, time window.
- Data API: page /trades (on side x token to beat the ~10k offset+limit ceiling) and
  /holders; cache raw JSON under data/raw/. Throttle; handle 429.
- On-chain: eth_getLogs OrderFilled / OrdersMatched from the correct V1 Exchange contract
  (CTF vs NegRisk, routed by the negRisk flag) for the market's asset IDs, chunked ~2k
  blocks with backoff and free-RPC rotation; index by transactionHash for the role join.

Built incrementally, one step at a time. Step 1.1 (this commit): Gamma discovery + a light
Data API probe for liquidity assessment. Pagination/caching/on-chain land in later steps.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"

_session = requests.Session()
_session.headers.update({"User-Agent": "tail-research/0.1 (prediction-market study)"})

# Rate limits are undocumented on Gamma/Data; throttle politely and back off on 429.
_THROTTLE_S = 0.25


def _get(url: str, params: dict | None = None, max_retries: int = 6) -> Any:
    backoff = 1.0
    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            r = _session.get(url, params=params, timeout=30)
        except requests.RequestException as e:  # transient network
            last_exc = e
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", backoff))
            time.sleep(wait)
            backoff = min(backoff * 2, 30)
            continue
        r.raise_for_status()
        time.sleep(_THROTTLE_S)
        return r.json()
    if last_exc:
        raise last_exc
    raise RuntimeError(f"GET failed after {max_retries} retries: {url} {params}")


# ---- Gamma (market discovery / metadata / resolution) ----------------------

def gamma_events(**params: Any) -> list[dict]:
    """GET /events with filters (e.g. slug=..., closed=true). Returns a list."""
    out = _get(f"{GAMMA}/events", params=params)
    return out if isinstance(out, list) else [out]


def gamma_markets(**params: Any) -> list[dict]:
    """GET /markets with filters (e.g. slug=..., condition_ids=..., closed=true)."""
    out = _get(f"{GAMMA}/markets", params=params)
    return out if isinstance(out, list) else [out]


def gamma_search(q: str, limit_per_type: int = 25) -> dict:
    """GET /public-search — full-text across events/markets/profiles."""
    return _get(f"{GAMMA}/public-search", params={"q": q, "limit_per_type": limit_per_type})


def _jload(s: Any, default: Any) -> Any:
    """Gamma encodes some fields (outcomes, outcomePrices, clobTokenIds) as JSON strings."""
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return default
    return s if s is not None else default


def parse_market(m: dict) -> dict:
    """Normalize a Gamma market object down to the fields Phase 1 cares about."""
    outcomes = _jload(m.get("outcomes"), [])
    prices = _jload(m.get("outcomePrices"), [])
    clob = _jload(m.get("clobTokenIds"), [])
    resolved_idx = None
    for i, p in enumerate(prices):
        try:
            if abs(float(p) - 1.0) < 1e-9:
                resolved_idx = i
        except (TypeError, ValueError):
            pass
    return {
        "question": m.get("question"),
        "slug": m.get("slug"),
        "conditionId": m.get("conditionId"),
        "clobTokenIds": clob,
        "outcomes": outcomes,
        "outcomePrices": prices,
        "resolved_outcome_index": resolved_idx,  # which side paid 1 (the winner), or None
        "volumeNum": m.get("volumeNum") or m.get("volume"),
        "liquidityNum": m.get("liquidityNum") or m.get("liquidity"),
        "negRisk": m.get("negRisk"),
        "closed": m.get("closed"),
        "umaResolutionStatus": m.get("umaResolutionStatus"),
        "startDate": m.get("startDate"),
        "endDate": m.get("endDate"),
        "createdAt": m.get("createdAt"),
    }


# ---- Data API (light probes for Step 1.1; full pulls in Step 1.2) -----------

def data_trades_page(condition_id: str, limit: int = 10000, offset: int = 0,
                     side: str | None = None, taker_only: bool = True) -> list[dict]:
    params: dict[str, Any] = {"market": condition_id, "limit": limit, "offset": offset,
                              "takerOnly": str(taker_only).lower()}
    if side:
        params["side"] = side
    out = _get(f"{DATA}/trades", params=params)
    return out if isinstance(out, list) else []


def data_holders(condition_id: str, limit: int = 1000) -> list[dict]:
    out = _get(f"{DATA}/holders", params={"market": condition_id, "limit": limit})
    return out if isinstance(out, list) else [out]


def probe_liquidity(condition_id: str) -> dict:
    """Cheap Step-1.1 assessment: one trades page (count + distinct wallets + capped flag)
    and holder counts per outcome token. NOT the full pull — that's Step 1.2."""
    trades = data_trades_page(condition_id, limit=10000, taker_only=True)
    wallets = {t.get("proxyWallet") for t in trades}
    ts = [t.get("timestamp") for t in trades if t.get("timestamp") is not None]
    holders = data_holders(condition_id)
    holder_counts = {h.get("token"): len(h.get("holders", [])) for h in holders}
    return {
        "trades_page_n": len(trades),
        "trades_capped": len(trades) >= 10000,  # may be more behind the offset ceiling
        "distinct_wallets_in_page": len([w for w in wallets if w]),
        "ts_min": min(ts) if ts else None,
        "ts_max": max(ts) if ts else None,
        "holder_counts_by_token": holder_counts,
    }
