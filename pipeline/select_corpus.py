"""Phase-2 Step 2.3a — full per-tier enumeration + classification (no outcomes).

Completes the candidate frame down to the $25k floor (the >$1M head is already cached), tags
V1-vs-V2 by the pinned migration cutoff (2026-04-28), and classifies every market event vs
recurring with template counts rebuilt over the FULL frame (A2.1 / A2.5 recall). Reports the
EXACT per-tier event-driven and recurring V1 populations that the frozen sample (A2.3/A2.4) will
be drawn from. Seeded sampling + list-freeze happen in 2.3b after review.

Run:  .venv/bin/python pipeline/select_corpus.py
"""
from __future__ import annotations

import json
import os

import ingest
import taxonomy as tx
from discover_corpus import enumerate_range_full

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
MIGRATION = "2026-04-28"        # pinned: CTF Exchange V2 / pUSD cutover (A2.2)
FLOOR = 25_000
TIERS = [("T1", 25_000, 100_000), ("T2", 100_000, 1_000_000),
         ("T3", 1_000_000, 10_000_000), ("T4", 10_000_000, float("inf"))]


def tier_of(v):
    for name, lo, hi in TIERS:
        if lo <= v < hi:
            return name
    return None


def is_v1(m):
    ed = m.get("endDate")
    return bool(ed) and ed < MIGRATION


def main() -> None:
    print("=== Step 2.3a — full enumeration + classification (no outcomes) ===")

    # head (>$1M) already enumerated and cached in 2.1
    head = ingest.load_raw("corpus_frame_head.json") or []
    print(f"  head (>$1M) cached: {len(head)}")

    # low tiers: full adaptive enumeration $25k–$1M (the new crawl)
    low = ingest.load_raw("corpus_frame_low.json")
    if low is None:
        print("  enumerating $25k–$1M (adaptive band-slice; one-time crawl)...")
        low = enumerate_range_full(FLOOR, 1_000_000)
        ingest.save_raw("corpus_frame_low.json", low)
    print(f"  low ($25k–$1M): {len(low)}")

    # combine + dedup by conditionId
    seen, frame = set(), []
    for m in head + low:
        cid = m.get("conditionId")
        if cid and cid not in seen:
            seen.add(cid)
            frame.append(m)
    print(f"  combined candidate frame: {len(frame)}")

    # classify with full-frame template counts (A2.1 S5 recall)
    tc = tx.build_template_counts(frame)
    for m in frame:
        cls, reasons, _ = tx.classify(m, tc)
        m["mkt_class"] = cls
        m["v1"] = is_v1(m)
        m["tier"] = tier_of(m["volumeNum"])

    # exact per-tier × class × era counts
    print("\n  per-tier populations (V1-era only; the sampling frame):")
    print(f"    {'tier':4} {'event':>8} {'recurring':>10} {'event-share':>12}")
    pop = {}
    for name, lo, hi in TIERS:
        e = sum(1 for m in frame if m["tier"] == name and m["v1"] and m["mkt_class"] == "event")
        r = sum(1 for m in frame if m["tier"] == name and m["v1"] and m["mkt_class"] == "recurring")
        pop[name] = {"event": e, "recurring": r}
        sh = 100 * e / max(e + r, 1)
        print(f"    {name:4} {e:>8} {r:>10} {sh:>11.0f}%")

    # V2 split (for disclosure)
    v2 = sum(1 for m in frame if not m["v1"])
    print(f"\n  V1 {sum(1 for m in frame if m['v1'])} | V2/post-migration {v2} "
          f"(endDate >= {MIGRATION}; excluded from corpus)")

    # planned draw vs availability (A2.3/A2.4)
    print("\n  planned draw vs availability:")
    for name, _, _ in TIERS:
        e, r = pop[name]["event"], pop[name]["recurring"]
        pe = min(500, e) if name != "T4" else e
        pr = min(250, r) if name != "T4" else r
        print(f"    {name}: event draw {pe} of {e} | recurring draw {pr} of {r}")

    summary = {"migration_cutoff": MIGRATION, "floor": FLOOR, "n_frame": len(frame),
               "per_tier_v1": pop, "n_v2_excluded": v2,
               "note": "Exact V1 sampling frame. No market selected yet, no outcome computed."}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "corpus_selection_frame.json"), "w") as f:
        json.dump(summary, f, indent=2)
    ingest.save_raw("corpus_frame_classified.json", frame)
    print(f"\n  classified frame -> data/raw/corpus_frame_classified.json")
    print(f"  summary          -> data/out/corpus_selection_frame.json")


if __name__ == "__main__":
    main()
