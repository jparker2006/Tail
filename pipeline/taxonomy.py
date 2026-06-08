"""Phase-2 Step 2.2 — event-driven vs recurring-algorithmic market classifier.

Pre-registered, transparent, and CONSERVATIVE: a market is labelled `event` (eligible for the
headline corpus) only if NO recurrence signal fires; anything ambiguous is labelled
`recurring` and kept OUT of the event-driven headline (it still feeds the labelled secondary
comparison group, stratified by the same volume tiers). See CORPUS_PREREG.md amendment A2.

Recurrence signals (any one ⇒ recurring):
  S1 sports per-game line  — slug like `<league>-<team>-<team>-YYYY-MM-DD...` or a
     `-total-/-spread-/-moneyline-/-ml-` betting-line token.
  S2 crypto intraday       — `updown`, `-5m-/-15m-/-1h-/-4h-` cadence tokens, or
     `<coin>-up/down/updown...`.
  S3 weather               — temperature / rainfall / snowfall series.
  S4 intraday duration     — createdAt→endDate < 24h (clearly an intraday instrument).
  S5 recurring template    — normalized-slug template (dates/numbers/timestamps masked) that
     recurs ≥ TEMPLATE_MIN times in the classified frame (a templated series).

Boundaries (TEMPLATE_MIN, the 24h duration cut) are reported with sensitivity, not tuned to
a result. Single-signal "gray-zone" markets are surfaced for review.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

TEMPLATE_MIN = 20
INTRADAY_H = 24.0

_LEAGUES = (r"(nba|nfl|nhl|mlb|wnba|ncaab|ncaaf|epl|laliga|seriea|bundesliga|ligue1|ucl|uel|"
            r"mls|atp|wta|ufc|lol|cs2|csgo|val|valorant|dota2|dota|rl|ow|cod|r6|sc2)")
_RE_SPORTS = re.compile(rf"^{_LEAGUES}-[a-z0-9]{{2,16}}-[a-z0-9]{{2,16}}-20\d\d-\d\d-\d\d")
# generic per-match structure (any league/esport): <prefix>-<team>-<team>-YYYY-MM-DD,
# plus "<a>-vs-<b>-...-YYYY-MM-DD" head-to-head slugs (tennis/esports long names)
_RE_MATCH = re.compile(r"^[a-z0-9]{2,6}-[a-z0-9]{2,16}-[a-z0-9]{2,16}-20\d\d-\d\d-\d\d")
_RE_VS = re.compile(r"-vs-.*-20\d\d-\d\d-\d\d")
_RE_LINE = re.compile(r"-(total|spread|moneyline|ml|h2h|over|under)-")
_RE_CRYPTO = re.compile(r"(updown|-up-down-)|-(5m|15m|30m|1h|4h|1d|hourly)-|"
                        r"^(btc|eth|sol|xrp|doge|bitcoin|ethereum|solana)-(up|down|updown)")
# crypto price-threshold series (coin name + a price/threshold word ⇒ templated recurring)
_RE_COIN = re.compile(r"(bitcoin|ethereum|solana|cardano|dogecoin|polkadot|avalanche|litecoin|"
                      r"chainlink|ripple|\bbtc\b|\beth\b|\bsol\b|\bxrp\b|\bada\b|\bdoge\b|\bbnb\b)")
_RE_PRICEWORD = re.compile(r"(above|below|between|greater|less-than|reach|hit|exceed|surpass|"
                           r"dip-to|price-of|all-time-high|up-or-down)")
_RE_WEATHER = re.compile(r"(temperature|-temp-|rainfall|snowfall|will-it-rain|highest-temp)")


def _parse(t):
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def duration_hours(m):
    a, b = _parse(m.get("createdAt") or m.get("startDate")), _parse(m.get("endDate"))
    return (b - a).total_seconds() / 3600.0 if (a and b) else None


def template(slug: str) -> str:
    s = slug or ""
    s = re.sub(r"\b20\d\d\b", "<Y>", s)
    s = re.sub(r"\b(january|february|march|april|may|june|july|august|september|october|"
               r"november|december)\b", "<MON>", s)
    s = re.sub(r"\b\d{9,}\b", "<TS>", s)
    s = re.sub(r"\d+pt\d+", "<N>", s)
    s = re.sub(r"\b\d+(\.\d+)?\b", "<N>", s)
    s = re.sub(r"(<N>-){2,}", "<N>-", s)
    return s


def build_template_counts(frame) -> Counter:
    return Counter(template(m.get("slug") or "") for m in frame)


def classify(m, tmpl_counts, template_min=TEMPLATE_MIN, intraday_h=INTRADAY_H):
    """Return (cls, reasons, template). cls ∈ {'event','recurring'}; conservative."""
    slug = (m.get("slug") or "").lower()
    reasons = []
    if (_RE_SPORTS.search(slug) or _RE_MATCH.search(slug) or _RE_VS.search(slug)
            or _RE_LINE.search(slug)):
        reasons.append("S1-sports-line")
    if _RE_CRYPTO.search(slug) or (_RE_COIN.search(slug) and _RE_PRICEWORD.search(slug)):
        reasons.append("S2-crypto-price")
    if _RE_WEATHER.search(slug):
        reasons.append("S3-weather")
    dur = duration_hours(m)
    if dur is not None and 0 <= dur < intraday_h:
        reasons.append("S4-intraday")
    t = template(slug)
    c = tmpl_counts.get(t, 0)
    if c >= template_min:
        reasons.append(f"S5-template(x{c})")
    return ("recurring" if reasons else "event"), reasons, t


def classify_frame(frame, **kw):
    tc = build_template_counts(frame)
    return [(m, *classify(m, tc, **kw)) for m in frame], tc
