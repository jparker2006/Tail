"""Phase-2 — event-driven vs recurring-algorithmic classifier + ladder dedup.

Pre-registered, conservative, audit-revised (CORPUS_PREREG.md A2 + A3). The line is NOT
"templated vs not" (belief ladders AND nightly games are both templated). It is:
  - recurring-algorithmic = a high-frequency STREAM of many DISTINCT low-stakes outcomes
    (crypto up/down + price-threshold, per-game betting markets/lines, weather, tweet-count
    series, stock/commodity up/down);  ⇒ secondary comparison group.
  - event-driven = a belief about a notable real-world outcome, possibly expressed as templated
    SLICES of ONE underlying (FOMC by bps, a strike question across deadlines); ⇒ headline,
    with the slices DEDUPED to one representative per underlying (avoids pseudoreplication).

A market is `recurring` iff a stream signal fires; else `event`. Then event-driven LADDERS are
clustered (the old S5 template signal, repurposed from exclusion → clustering key) and all but
the most-liquid member of each cluster are flagged `ladder_dup` (kept out of the independent
sample). Conservative: a market is `event` only if no stream signal fires.
"""
from __future__ import annotations

import re
from collections import defaultdict

# ---- S1: per-game match / betting line (the nightly sports stream) ----------
_LEAGUES = (r"(nba|nfl|nhl|mlb|wnba|ncaab|ncaaf|cbb|cfb|epl|laliga|seriea|bundesliga|ligue1|"
            r"euroleague|ucl|uel|uef|mls|atp|wta|ufc|lol|cs2|csgo|val|valorant|dota2|dota|rl|"
            r"ow|cod|r6|sc2)")
_RE_SPORTS = re.compile(rf"^{_LEAGUES}-[a-z0-9]{{2,16}}-[a-z0-9]{{2,16}}-20\d\d-\d\d-\d\d")
_RE_MATCH = re.compile(r"^[a-z0-9]{2,6}-[a-z0-9]{2,16}-[a-z0-9]{2,16}-20\d\d-\d\d-\d\d")
_RE_VS = re.compile(r"-vs-.*-20\d\d-\d\d-\d\d")
_RE_LINE = re.compile(r"-(total|spread|moneyline|ml|btts|draw)-")    # over/under too generic

# ---- S2: asset up/down + price-threshold (crypto, stocks, commodities) ------
_RE_CRYPTO = re.compile(r"(updown|-up-down-)|-(5m|15m|30m|1h|4h|1d|hourly)-|"
                        r"^(btc|eth|sol|xrp|doge|bitcoin|ethereum|solana)-(up|down|updown)")
_RE_UPDOWN = re.compile(r"-up-or-down-")                       # any ticker: amzn/msft/btc...
_RE_COIN = re.compile(r"(bitcoin|ethereum|solana|cardano|dogecoin|polkadot|avalanche|litecoin|"
                      r"chainlink|ripple|\bbtc\b|\beth\b|\bsol\b|\bxrp\b|\bada\b|\bdoge\b|\bbnb\b)")
_RE_PRICEWORD = re.compile(r"(above|below|between|greater|less-than|reach|hit|exceed|surpass|"
                           r"dip-to|price-of|all-time-high|up-or-down)")
_RE_TICKER_THRESH = re.compile(r"^[a-z]{2,6}-(above|below|between|dip-to|reach|hit|over|under)-\d")

# ---- S3 weather, S6 tweet-count series --------------------------------------
_RE_WEATHER = re.compile(r"(temperature|-temp-|rainfall|snowfall|will-it-rain|highest-temp)")
_RE_TWEETS = re.compile(r"(of-tweets|tweet-\d|tweets-\d|tweet-count)")


def classify(m):
    """Return (cls, reasons). cls ∈ {'event','recurring'}; conservative (no signal ⇒ event)."""
    slug = (m.get("slug") or "").lower()
    reasons = []
    if (_RE_SPORTS.search(slug) or _RE_MATCH.search(slug) or _RE_VS.search(slug)
            or _RE_LINE.search(slug)):
        reasons.append("S1-sports")
    if (_RE_CRYPTO.search(slug) or _RE_UPDOWN.search(slug) or _RE_TICKER_THRESH.search(slug)
            or (_RE_COIN.search(slug) and _RE_PRICEWORD.search(slug))):
        reasons.append("S2-asset")
    if _RE_WEATHER.search(slug):
        reasons.append("S3-weather")
    if _RE_TWEETS.search(slug):
        reasons.append("S6-tweets")
    return ("recurring" if reasons else "event"), reasons


def ladder_key(slug: str) -> str:
    """Cluster key for event-driven ladders: mask SLICE numbers but keep the event's identity
    (month/year/words). FOMC-by-bps across one meeting collapse; distinct meetings/questions
    stay separate."""
    s = (slug or "").lower()
    s = re.sub(r"\d+pt\d+", "<N>", s)
    s = re.sub(r"\b(?!20\d\d\b)\d+\b", "<N>", s)      # mask ints except 4-digit years
    s = re.sub(r"(-<N>){2,}", "-<N>", s)              # collapse runs of masked ids
    return s


def dedupe_ladders(event_markets):
    """Mark all but the most-liquid member of each ladder cluster as `ladder_dup`.

    Mutates each dict: sets `ladder_key` and `ladder_dup` (bool). Returns (n_clusters_deduped,
    n_dups). Singleton clusters are untouched (ladder_dup=False)."""
    groups = defaultdict(list)
    for m in event_markets:
        k = ladder_key(m.get("slug"))
        m["ladder_key"] = k
        m["ladder_dup"] = False
        groups[k].append(m)
    n_clusters, n_dups = 0, 0
    for k, members in groups.items():
        if len(members) < 2:
            continue
        n_clusters += 1
        rep = max(members, key=lambda x: float(x.get("volumeNum") or 0))
        for m in members:
            if m is not rep:
                m["ladder_dup"] = True
                n_dups += 1
    return n_clusters, n_dups
