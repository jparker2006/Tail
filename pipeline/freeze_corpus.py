"""Phase-2 Step 2.3b — seeded selection freeze (no outcomes).

Draws and FREEZES, from the exact V1 classified frame (2.3a), with seed 20260607:
  - primary  : event-driven headline corpus (500/500/500 + take-all T4)            [A2.3]
  - secondary: recurring comparison corpus (250/250/250 + take-all T4)             [A2.4]
  - validation: 40 markets (T1 12/T2 12/T3 10/T4 6; ~60% event/40% recurring;
                negRisk + non-negRisk balanced) for the on-chain 2-vs-3-signal check [A1.2]
  - audit    : 150 event + 150 recurring (tier-stratified) to hand-adjudicate
               classifier false-inclusion AND false-exclusion                       [A2.5]

Lists are written to data/out (tracked) = the analysis + demo corpus. No outcome computed.

Run:  .venv/bin/python pipeline/freeze_corpus.py
"""
from __future__ import annotations

import json
import os
import random

import ingest

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "out"))
SEED = 20260607
TIERS = ["T1", "T2", "T3", "T4"]
PRIMARY_N = {"T1": 500, "T2": 500, "T3": 500, "T4": None}     # None = take-all
SECONDARY_N = {"T1": 250, "T2": 250, "T3": 250, "T4": None}
VAL_ALLOC = {"T1": 12, "T2": 12, "T3": 10, "T4": 6}
AUDIT_EVENT = {"T1": 38, "T2": 38, "T3": 37, "T4": 37}
AUDIT_RECUR = {"T1": 38, "T2": 38, "T3": 37, "T4": 37}

FIELDS = ("slug", "question", "conditionId", "clobTokenIds", "volumeNum", "tier",
          "negRisk", "mkt_class", "ladder_key", "resolved_index", "endDate")


def slim(m):
    return {k: m.get(k) for k in FIELDS}


def take(rng, pool, k):
    if k is None or k >= len(pool):
        return list(pool)
    return rng.sample(pool, k)


def balanced_by_negrisk(rng, pool, k):
    """Draw k from pool, balancing negRisk True/False where both are available."""
    if k >= len(pool):
        return list(pool)
    neg = [m for m in pool if m.get("negRisk")]
    non = [m for m in pool if not m.get("negRisk")]
    rng.shuffle(neg); rng.shuffle(non)
    out, i = [], 0
    while len(out) < k and (neg or non):
        src = (neg if (i % 2 == 0 and neg) or not non else non)
        if src:
            out.append(src.pop())
        i += 1
    return out[:k]


def main() -> None:
    frame = ingest.load_raw("corpus_frame_classified.json")
    v1 = [m for m in frame if m.get("v1")]
    pools = {}
    for t in TIERS:
        # event eligibility excludes ladder duplicates (A3); recurring is the stream group
        pools[(t, "event")] = [m for m in v1 if m["tier"] == t and m["mkt_class"] == "event"
                               and not m.get("ladder_dup")]
        pools[(t, "recurring")] = [m for m in v1 if m["tier"] == t and m["mkt_class"] == "recurring"]
    rng = random.Random(SEED)

    primary, secondary = [], []
    for t in TIERS:
        primary += [slim(m) for m in take(rng, pools[(t, "event")], PRIMARY_N[t])]
        secondary += [slim(m) for m in take(rng, pools[(t, "recurring")], SECONDARY_N[t])]

    # validation subset (from the union of selected corpus markets, tier-stratified)
    sel_by = {(t, c): [] for t in TIERS for c in ("event", "recurring")}
    for m in primary:
        sel_by[(m["tier"], "event")].append(m)
    for m in secondary:
        sel_by[(m["tier"], "recurring")].append(m)
    validation = []
    for t in TIERS:
        ev_k = round(0.6 * VAL_ALLOC[t]); rec_k = VAL_ALLOC[t] - ev_k
        validation += balanced_by_negrisk(rng, list(sel_by[(t, "event")]), ev_k)
        validation += balanced_by_negrisk(rng, list(sel_by[(t, "recurring")]), rec_k)

    # NOTE: audit_sample.json is the FROZEN independent test set drawn + hand-adjudicated in
    # 2.3b/2.3c (it had to be drawn from the pre-revision classification to catch its errors).
    # It is intentionally NOT regenerated here.
    os.makedirs(OUT, exist_ok=True)
    for name, lst in [("corpus_primary", primary), ("corpus_secondary", secondary),
                      ("validation_subset", validation)]:
        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            json.dump({"seed": SEED, "n": len(lst), "markets": lst}, f, indent=2)
    audit = json.load(open(os.path.join(OUT, "audit_sample.json")))["markets"]

    def by_tier(lst):
        return {t: sum(1 for m in lst if m["tier"] == t) for t in TIERS}
    print(f"=== Step 2.3b — selection freeze (seed {SEED}) ===")
    print(f"  primary   (event)     : {len(primary):>4}  {by_tier(primary)}")
    print(f"  secondary (recurring) : {len(secondary):>4}  {by_tier(secondary)}")
    nneg = sum(1 for m in validation if m.get('negRisk'))
    nev = sum(1 for m in validation if m['mkt_class'] == 'event')
    print(f"  validation subset     : {len(validation):>4}  {by_tier(validation)}  "
          f"(event {nev}/{len(validation)}, negRisk {nneg}/{len(validation)})")
    print(f"  audit sample          : {len(audit):>4}  "
          f"(event {sum(1 for m in audit if m['audit_pool']=='event')}, "
          f"recurring {sum(1 for m in audit if m['audit_pool']=='recurring')})")
    print("  frozen -> data/out/{corpus_primary,corpus_secondary,validation_subset,audit_sample}.json")


if __name__ == "__main__":
    main()
