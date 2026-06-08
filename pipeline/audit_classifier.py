"""Phase-2 Step 2.3c — bidirectional classifier audit (hand-adjudicated ground truth).

I (the researcher) ground-truthed all 300 audit slugs by CONTENT: a market is recurring iff it
is a systematically-generated algorithmic/HFT instrument (crypto up/down + price-threshold,
per-game betting LINES, weather, tweet-count series, stock/commodity up/down); event-driven iff
the crowd forms a belief about a distinct real-world outcome (elections, geopolitics, policy,
championships/tournament outcomes, one-off matches/fights, culture, company events).

Ground truth is recorded as overrides vs the classifier label (everything else agrees). Two
definitional boundaries are flagged for adjudication (they drove the judgment calls):
  B1 belief-ladders (FOMC-bps, strikes-by-date, inflation-by-N): templated but belief-driven.
  B2 per-game match OUTCOMES (bare league-team-team-date, no line token): match outcome vs
     systematic nightly stream.

Run:  .venv/bin/python pipeline/audit_classifier.py
"""
from __future__ import annotations

import json
import os
import re

import ingest

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))

# classifier said EVENT, ground truth = RECURRING (false-inclusion / contamination)
FALSE_INCL = [
    "amzn-up-or-down-on-february-6", "andrew-tate-of-tweets", "msft-up-or-down-on-december-8",
    "arb-above-1pt25-on-april-7", "elon-tweet-180194-times", "euroleague-baskonia-munchen",
    "ng-dip-to-2-50-by-april-20", "elon-tweet-900-or-more-times-feb-21",
    "elon-tweet-250-274-times-oct-4", "elon-tweet-255-or-more-times-august-1",
]
# classifier said RECURRING, ground truth = EVENT (false-exclusion / wrongly excluded)
FALSE_EXCL = [
    "will-obama-say-democracy-3-or-more-times", "will-monthly-inflation-increase-by-0pt4",
    "will-melania-say-career-during-ai-talk", "democrats-win-popular-vote-by-over-7",
    "will-south-korea-presidential-election-winner-get-over-50",
    "fed-decreases-interest-rates-by-50-bps-after-july-2025",
    "fed-decreases-interest-rates-by-50-bps-after-september-2025",
    "fed-decreases-interest-rates-by-75-bps-after-december-2024",
    "fed-decreases-interest-rates-by-50-bps-after-march-2025",
    "fed-decreases-interest-rates-by-75-bps-after-november-2024",
    "fed-decreases-interest-rates-by-25-bps-after-july-2025",
    "fed-decreases-interest-rates-by-25-bps-after-january-2025",
    "fed-decreases-interest-rates-by-75-bps-after-january-2025",
    "fed-decreases-interest-rates-by-25-bps-after-june-2025",
    "fed-decreases-interest-rates-by-50-bps-after-january-2026",
    "fed-decreases-interest-rates-by-25-bps-after-may-2025",
    "fed-decreases-interest-rates-by-50-bps-after-may-2025",
    "fed-decreases-interest-rates-by-50-bps-after-september-2024",
    "us-strikes-iran-by-february-9-2026", "us-strikes-iran-by-february-10-2026",
    "us-strikes-iran-by-february-23-2026", "us-strikes-iran-by-january-23-2026",
    "us-strikes-iran-by-february-20-2026", "thailand-strikes-cambodia-by-friday",
]

# boundary tags (for reporting how big each definitional lever is)
B1 = re.compile(r"(fed-(decreases|increases|change)-interest-rates|-bps-after-|"
                r"strikes?-[a-z]+-by-|us-forces-enter|monthly-inflation)")
_LINE = re.compile(r"-(total|spread|moneyline|ml|btts|draw|over|under)-")
B2 = re.compile(r"^[a-z0-9]{2,6}-[a-z0-9]{2,16}-[a-z0-9]{2,16}-20\d\d-\d\d-\d\d")


def truth_of(slug, classifier_label):
    if any(k in slug for k in FALSE_INCL):
        return "recurring"
    if any(k in slug for k in FALSE_EXCL):
        return "event"
    return classifier_label


def main() -> None:
    audit = ingest.load_raw("../data/out/audit_sample.json") or \
        json.load(open(os.path.join(OUT, "audit_sample.json")))
    markets = audit["markets"]
    rows, b1n, b2n = [], 0, 0
    for m in markets:
        slug, pool = m["slug"], m["audit_pool"]            # pool == classifier label
        truth = truth_of(slug, pool)
        rows.append({"slug": slug, "tier": m["tier"], "classifier": pool, "truth": truth,
                     "agree": truth == pool})
        if B1.search(slug):
            b1n += 1
        if B2.search(slug) and not _LINE.search(slug):
            b2n += 1

    def rate(pool, err_truth, tier=None):
        sub = [r for r in rows if r["classifier"] == pool and (tier is None or r["tier"] == tier)]
        bad = [r for r in sub if r["truth"] == err_truth]
        return len(bad), len(sub)

    print("=== Step 2.3c — classifier audit (hand-adjudicated, n=300) ===\n")
    print("  FALSE-INCLUSION (classifier=event, truth=recurring → headline contamination):")
    for t in ("T1", "T2", "T3", "T4", None):
        b, n = rate("event", "recurring", t)
        print(f"    {t or 'ALL':4}: {b}/{n}  ({100*b/max(n,1):.0f}%)")
    print("\n  FALSE-EXCLUSION (classifier=recurring, truth=event → wrongly excluded belief mkts):")
    for t in ("T1", "T2", "T3", "T4", None):
        b, n = rate("recurring", "event", t)
        print(f"    {t or 'ALL':4}: {b}/{n}  ({100*b/max(n,1):.0f}%)")

    fe = [r for r in rows if r["classifier"] == "recurring" and r["truth"] == "event"]
    fomc = sum(1 for r in fe if "bps-after" in r["slug"] or "interest-rates" in r["slug"])
    strikes = sum(1 for r in fe if "strikes" in r["slug"] or "forces-enter" in r["slug"])
    print(f"\n  false-exclusion composition: FOMC-bps {fomc}, strikes-by-date {strikes}, "
          f"other macro/election {len(fe)-fomc-strikes}")
    print(f"\n  definitional-boundary prevalence in the audit sample:")
    print(f"    B1 belief-ladders (FOMC/strikes/inflation patterns): {b1n}/300")
    print(f"    B2 bare per-game match outcomes (no line token)     : {b2n}/300")

    with open(os.path.join(OUT, "audit_results.json"), "w") as f:
        json.dump({"n": len(rows),
                   "false_inclusion": rate("event", "recurring"),
                   "false_exclusion": rate("recurring", "event"),
                   "rows": rows}, f, indent=2)
    print("\n  full labels -> data/out/audit_results.json")


if __name__ == "__main__":
    main()
