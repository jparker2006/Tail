# Phase 2 Corpus Pre-Registration — Tail

**Written 2026-06-07, BEFORE any corpus market has been analyzed.** This document is
**frozen**. It extends — and does **not** modify — `FALSIFICATION.md` (the Phase-1
single-market freeze, which stands unchanged as the historical record). Where this document
is silent, the `FALSIFICATION.md` definitions, MM-filter parameters, null definitions, and
reporting commitments carry forward verbatim.

> **The three Phase-1 verdicts (Claim 1 *survives*, Claim 2 *not supported*, Claim 3 *not
> found*) are n = 1 DESCRIPTIVE ONLY and carry ZERO inferential weight here.** They are a
> gut-check that the machinery runs, nothing more. The corpus is what converts the
> within-market F1/F2/F3 into population-level tests. No writeup may state any of the three
> claims as established until the corpus speaks.

---

## 0. Scope freeze — V1 only

The corpus is **V1 markets only**: resolved binary markets traded on the V1 **CTF Exchange**
`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` / V1 **NegRisk Exchange**
`0xC5d563A36AE78145C45a50134d48A1215220f80a`, settled in **USDC.e (6 dp)** — the exact ground
on which the Phase-1 method was validated end-to-end.

- The cutoff for the **~April-2026 V1→V2/pUSD migration** is pinned **operationally, not by a
  hardcoded date**: any market with on-chain activity on the V2 exchange is **excluded**.
- V1 alone spans years through the 2024 cycle — thousands of resolved markets across every
  category — so the corpus has ample power without V2.
- **V2 is deferred to its own verified phase.** Its exchange contracts, event signatures, and
  pUSD decimals must be re-verified live before any V2 market is touched. That later phase
  doubles as a clean **post-migration replication check**. Pulling unverified V2 code paths
  into this corpus is exactly the incompatible-structure / unverified-path risk we are
  avoiding.

---

## 1. Attribution method freeze

### 1.1 Primary = interval net-flow (principled, not "cleaner")

The **primary** discovery-attribution method is **interval net-flow** (group fills into
per-`N` blocks; split each block's truth-signed price move `Δ*` among the non-MM aggressors
whose net flow pushed in the move's direction, pro-rata by net flow).

**Principled reason, frozen:** in a CLOB, price moves with **net directional pressure**.
Arb/MM bots round-trip within short windows — buy the bid, sell the ask, rebalance inventory —
so their *gross* participation is large but their *net* flow over any short interval is ≈ 0.
The per-fill print method credits whichever wallet's fill happened to print at each price
tick, so a bot that buys low and sells high is credited for **both** ticks despite having
moved price nowhere net. Interval net-flow nets out that within-interval round-tripping, so
flat bots absorb ≈ no credit. This is a structural argument about how CLOB price formation
works — **not** a post-hoc preference for a number that looked cleaner.

> *Provenance:* the Phase-1 freeze table named per-fill the primary and interval the
> cross-check. The **pre-registered** primary-vs-crude Spearman flag (ρ < 0.6) fired on the
> per-fill method, exposing it as microstructure-contaminated (≈ 80% of credit to flat
> arb-bots, ≈ 50% wrong-way). The switch to interval was triggered *by* a pre-registered
> diagnostic and is recorded in git history. This document formalizes interval as the
> principled primary going forward.

### 1.2 Conservation is a consistency check, NOT validation

The identity **Σ (interval credits) = total truth-signed travel** holds *by construction* —
once every interval's move is attributed to net flow, the credits sum to the move. In a CLOB
this is close to an **accounting identity** (net directional flow is what moves price), so it
is recorded only as "**no credit leaked**" — a consistency check. It is **not** evidence that
the per-wallet split is correct, and no writeup may present "explains 100% of the move" as
validation. Validation of the per-wallet split rests on §1.3–§1.5 instead.

### 1.3 Dual reporting — per-fill AND interval, side by side

For **every** corpus market, concentration (Gini, `N_half`, `N_half / n_directional`, top-N
shares) is computed under **both** the interval and per-fill methods and reported **side by
side**.

- The corpus headline uses the **interval** primary.
- Markets where the two methods **disagree on the per-market F1 verdict** are flagged and
  counted; that disagreement fraction is a reported corpus statistic.
- **If concentration holds only under interval (not per-fill), the §1.1 principled rationale
  leads the writeup** — we do not bury the method dependence.

### 1.4 Window-length robustness (carried from Phase 1)

Concentration recomputed at interval window length **N ∈ {10, 25, 50, 100}** fills; the F1
verdict must survive across them. Frozen primary **N = 25**.

### 1.5 Boundary sensitivity (NEW) — phase-offset sweep

Distinct from window *length*: a bot round-trip that **straddles** a window boundary does not
net out within either adjacent window and is miscredited as directional. Test by a
**deterministic phase-offset sweep** at fixed `N`: start the window grid at offsets
**{0, N/4, N/2, 3N/4}** fills and recompute concentration at each. No RNG, no seed.

- **Requirement:** the per-market F1 verdict must be **invariant across all four offsets**.
- The sweep is **always reported** as robustness, pass or fail.
- **Pre-committed escalation:** the single-grid interval method (§1.1) **stays the primary**.
  *If and only if* the F1 verdict is **not** invariant across the offsets do we escalate to an
  **offset-averaged** interval method — and that escalated method must itself be re-validated
  (primary-vs-crude Spearman, dual reporting) **before** any headline rests on it. We do
  **not** switch to offset-averaging pre-emptively, because that would replace the validated
  method with an unvalidated one and re-open the "headline rests on an unvalidated method"
  problem we closed in Phase 1.

---

## 2. Claim-3 active-window freeze — co-active span + floor

Echo is only **definable** where both cohorts trade concurrently, so the window must match the
construct: the **co-active span**, not an overall-activity window.

- **Resolution (frozen):** 5-min bins (`bin_s = 300`), max lag **L = 12 bins (60 min)**.
  Cohorts: **big** = top-decile gross notional, **small** = bottom-50% (per
  `FALSIFICATION.md`).
- **Active window = co-active span:** the contiguous span from the first to the last bin in
  which **both** the big and small cohorts each have ≥ 1 fill.
- **Minimum co-active bins `M` (frozen on principle):** **`M = 4·L = 48`**. Rationale: the
  longest lag tested should not exceed ¼ of the series (standard ACF/Box-Jenkins guidance);
  `M = 4L` places the max lag at exactly ¼ of the active window and leaves `M − L = 36`
  overlapping bin-pairs at the longest lag.
- **Exclusion, not nullification:** a market with **fewer than `M` co-active bins** is
  **EXCLUDED** from the Claim-3 test and reported as **"insufficient activity to measure
  echo."** It is **never** counted as evidence against echo — you do not get to call a market
  a null for echo if echo could not be measured there in the first place. Excluded markets are
  reported in a separate denominator.
- **Sensitivity (reported):** `M ∈ {48, 72, 96}` and bin width.
- **Non-causal framing retained** verbatim from `FALSIFICATION.md`: association/timing only;
  common-signal and shared-identity confounds acknowledged; price-chasing confound probe
  reported.

---

## 3. Corpus-level falsification (population upgrades of F1/F2/F3)

The Phase-1 F1/F2/F3 are *per-market* tests. At the corpus level they become distributional /
proportion tests. The market-selection universe and the analyzability floors of §5 apply.

### F1′ — Concentration across the corpus (load-bearing)
- Report the **distribution** of Gini and `N_half / n_directional` across the corpus, under
  **both** attribution methods (§1.3). Headline = **median + IQR**, plus the population
  sentence: *"in the median resolved market, **N** wallets accounted for half of all price
  discovery."*
- **Corpus-level falsification:** Claim 1 dies if **median Gini < 0.60** OR **median
  `N_half / n_directional` > 0.05** — and this must hold under **both** methods. Report the
  fraction of markets where the two methods disagree on the per-market F1 verdict, and the
  fraction passing the MM flatness-band robustness rider {0.10, 0.15, 0.20}.

### F2′ — Movers' edge across the corpus
- Per market: top-`K` movers (K = 10; report 5, 20), selected **resolution-blind** by net
  aggressive directional size (gross volume as robustness), tested vs **Null B**
  (volume-matched random wallets) at the 95th pct, B = 10,000.
- **Corpus statistic:** the **fraction of markets** where movers beat Null B, tested against
  the **5%-by-chance** baseline (binomial). "**Smart**" only if significantly above chance
  under **Null B**; "**rich, not smart**" if significantly above **Null A** but not Null B;
  otherwise **no edge**. The 5% baseline is correct here: beating Null B at the 95th pct is
  genuinely a 5% event by construction.
- **Descriptive add (not a kill gate):** also report the **fraction of markets where the top
  movers significantly UNDERPERFORM Null B** — observed top-K PnL **below the 5th percentile**
  of the Null-B distribution (the symmetric lower tail). "Movers are systematically *wrong*"
  (anti-wisdom) is itself a finding — Phase 1 hinted at it (two whales shorted Yes and lost) —
  and is pre-registered now so it stays credible if it appears. It does **not** alter the F2′
  kill criterion (which is failure to *beat* Null B at the 95th pct).
- **Pre-committed:** no market cherry-picking; the test runs on the full in-scope corpus.

### F3′ — Echo across the corpus
- Among **in-scope** Claim-3 markets only (co-active span ≥ `M`): report the **distribution**
  of positive-lag peak ρ vs each market's own circular-shift null band.
- **Corpus statistic:** the **fraction** of in-scope markets with peak ρ ≥ 0.15 **AND** above
  own null p95 **AND** at a positive lag.
- **Baseline (calibrated, NOT a flat 5%):** this fraction is benchmarked against the **combined
  test's actual per-market false-positive rate** — the rate at which a *no-echo* market clears
  **both** the magnitude gate (`|ρ| ≥ 0.15`) **and** the block-bootstrap band **by chance**.
  That rate is estimated per market from its own circular-shift null distribution as
  `FPR_m = P_null( peak ρ ≥ max(0.15, null_p95) )` and averaged across in-scope markets to form
  the expected-by-chance fraction; the observed fraction is tested against it (binomial /
  Poisson-binomial). Because the magnitude gate makes the joint test **stricter** than the band
  alone, benchmarking F3′ against a flat 5% would **miscalibrate it and bias toward declaring
  "no echo."** (F2′ keeps its flat 5% — there the proportion is 5% by construction; here it is
  not.)
- Markets excluded for thinness (§2) are reported in a **separate denominator** and **never**
  as nulls.

---

## 4. Deferred / carried caveats

- **Proxy clustering deferred.** Headline concentration is **per-`proxyWallet`**. Clustering
  proxies under common funding can only **raise** concentration, so the per-proxy headline is
  **conservative** (biases the finding *against* the thesis). Top-20 funding-cluster sensitivity
  remains a later add, as in `FALSIFICATION.md`.
- **All MM-filter parameters, the role-coverage threshold (0.70), the null definitions
  (A/B/C), B = 10,000, and all reporting commitments** carry forward from `FALSIFICATION.md`
  unchanged.

---

## 5. Corpus selection — rule frozen now, thresholds frozen at discovery

The *rule form* is frozen here; the numeric activity/representativeness thresholds are set
**empirically at the discovery checkpoint (Step 2.1) and frozen BEFORE any concentration is
computed**, because a volume/trader floor cannot be picked responsibly without first seeing
the distribution of market sizes. To prevent gaming, the *rule* — not just the result — is
pre-committed:

- **Universe:** all V1 resolved binary markets discoverable via Gamma (§0 scope).
- **Stratification:** balanced across categories (politics / sports / crypto / news / …);
  the category set and balancing rule are logged at discovery.
- **Hard analyzability floor (frozen now, on principle):** a market enters Claim-1 analysis
  only if it has **`n_directional` ≥ 30** non-MM aggressors. Below that, Gini / `N_half` over
  positive contributors are statistically unstable. (Claim-3's separate floor is `M = 48`
  co-active bins, §2.)
- **Representativeness floor (rule frozen now; thresholds at discovery):** to prevent "a few
  wallets set the price" from being **trivially** true in ghost towns, require minimum
  **distinct non-MM aggressors** and minimum **`volumeNum`**, set by a **pre-committed
  percentile rule** on the discovered distribution (e.g. exclude the bottom tercile by
  distinct-trader count). The percentile and resulting thresholds are **logged and frozen at
  Step 2.1, before any outcome is computed, and never adjusted post-hoc.**
- **No silent truncation** (carried): any market whose tape is pagination-truncated is flagged
  `trades_truncated` and excluded from headline metrics, not reported as complete.

---

## Reporting commitments (in addition to FALSIFICATION.md)

1. **Descriptive → inferential boundary.** Phase-1 verdicts are descriptive; only the corpus
   F1′/F2′/F3′ carry inferential weight. The writeups state this explicitly and do not let any
   single-market result harden into the narrative.
2. **Method dependence surfaced.** Per-fill and interval are always reported side by side;
   if the headline holds only under interval, the principled rationale leads (§1.3).
3. **Exclusions are not nulls.** Markets excluded for thinness (Claim 1: `n_directional < 30`;
   Claim 3: co-active bins `< M`) are reported in separate denominators, never as evidence
   against a claim.
4. **Negatives published** with equal prominence; the corpus result is pre-committed to
   publication whichever way it falls.

---

## Amendments

### A1 — 2026-06-07, post-discovery, pre-analysis (no outcome computed)

Step-2.1 discovery (read-only Gamma characterization) produced findings that revise four
frozen items. Each amendment uses **only market metadata** (volume / dates / structure flags),
is made **before any market outcome is computed**, and is recorded here and in git so nothing
is swapped silently.

**A1.1 — §0 scope gains an explicit lower bound (CLOB filter).** The V1 universe is bounded
*below* by the pre-2022 AMM/FPMM era as well as above by V2. A market enters the corpus only
if **`enableOrderBook == True`** — the empirical CLOB discriminator (present/True on order-book
markets, absent on the 2020-era AMM markets). The V2 upper bound is unchanged (on-chain
V2-exchange-activity exclusion).

**A1.2 — Role at scale: broad 2-signal corpus + on-chain validation subset.** Full per-market
on-chain role joins do not scale on free archive RPC, and the maker-inclusive /trades tape
truncates on the high-volume head. Therefore:
- The corpus headline runs on the **2-signal MM filter** (flatness + breadth) over the
  maker-inclusive Data-API /trades tape.
- A **stratified validation subset of 30–50 markets** — spanning the volume tiers, topical
  categories, **and** negRisk / non-negRisk — gets the **full 3-signal on-chain role join** to
  validate the 2-signal filter.
- **Validation criterion = the downstream verdict, not the labels:** the 2-signal filter is
  accepted iff it agrees with the 3-signal join on the per-market **Gini / N_half (F1) verdict**
  across the subset — not merely on which wallets are tagged MM.
- **Pre-committed escalation:** if they materially disagree on that downstream verdict, expand
  the on-chain set toward the tiered head before trusting the broad corpus.
- On-chain is also reserved for any mega-market whose /trades tape exceeds the pagination
  ceiling.

**A1.3 — negRisk included; NegRisk-Exchange decoder validated first.** negRisk markets (~40% of
the head, incl. the marquee 2024 election markets) stay in the corpus for representativeness.
The V1 **NegRisk-Exchange on-chain decoder is validated on the validation subset BEFORE** any
negRisk market's role is used. **Pre-committed fallback:** if it does not validate, negRisk
markets are **segregated as a separate caveated tier (or dropped)** — never trusted on an
unvalidated path.

**A1.4 — §5 floor: absolute floor + volume tiers, superseding the percentile rule.** Discovery
showed a *uniformly liquid* candidate universe (the top ~6000 CLOB∧binary∧resolved markets are
all > $1.3M volume), which makes a percentile cut on a junk-inclusive universe uninterpretable.
The §5 representativeness floor is amended to an **absolute volume floor** plus **volume-tier
strata**, with the floor and tier boundaries set from the **actual discovered volume
distribution** (each tier sized for adequate power), reported and frozen at the discovery
checkpoint **before any outcome is computed**. The hard analyzability floor (`n_directional ≥
30`) is unchanged. This remains legitimate pre-registration because the choice uses **only the
volume distribution**, is fixed **before any outcome**, and lands in git. *(Supersedes the
percentile-rule clause in §5; that clause is retained above as the original frozen text for
provenance. The numeric floor + tier boundaries are appended here once the full enumeration is
reviewed and approved.)*

### A2 — 2026-06-07, post-classification, pre-analysis (no outcome computed)

Step-2.2 built and calibrated the event-driven vs recurring-algorithmic classifier
(`pipeline/taxonomy.py`) on the cached V1 head frame. This freezes the taxonomy, the tier
structure, the per-tier sample sizes, and the audit protocol. Metadata only; no outcome
computed.

**A2.1 — Taxonomy classifier (pre-registered, conservative).** A market is `event` (eligible
for the headline corpus) **only if NO recurrence signal fires**; anything ambiguous ⇒
`recurring` (kept OUT of the headline, fed to the labelled secondary group). Signals — any one
⇒ recurring:
- **S1** per-match / betting-line — `^<league>-<team>-<team>-YYYY-MM-DD`, a generic
  `<prefix>-<team>-<team>-YYYY-MM-DD`, an `…-vs-…-YYYY-MM-DD` head-to-head, or a
  `-total-/-spread-/-moneyline-/-ml-/over/under-` line token;
- **S2** crypto — intraday cadence (`updown`, `-5m/15m/1h/4h/1d-`, `<coin>-up/down`) or a
  price-threshold series (coin name **and** a price/threshold word);
- **S3** weather series (temperature / rainfall / snowfall);
- **S4** intraday duration (createdAt→endDate < 24h);
- **S5** recurring template — normalized-slug template (years/months/numbers/timestamps masked)
  recurring **≥ 20×** in the classified frame.

Template counts are **rebuilt over the full per-tier enumerated frame at selection** (maximising
S5 recall, especially in the low tiers). Documented gray zone: macro-event families (FOMC
bps-threshold variants split by template frequency). Boundary sensitivity reported
(`template_min ∈ {10,20,40}` × `intraday ∈ {24,72}h`; T4 event-driven held 433–502). We do
**not** add further ad-hoc patterns — that would over-fit the rule to already-seen examples.

**A2.2 — Tiers + V1 filter (frozen).** Four volume tiers, **$25k absolute floor** (trader-safe:
discovery spot-check found ≥76 distinct takers even at ~$30k): **T1 $25k–$100k, T2 $100k–$1M,
T3 $1M–$10M, T4 > $10M.** V1-era filter = `endDate < migration cutoff` (conservative proxy); the
exact cutoff is pinned and V2-exchange exclusion verified on the on-chain validation subset
(A1.2).

**A2.3 — Primary (event-driven) sample (frozen).** Post-filter V1 event-driven population: T1
~1,650, T2 ~2,700, T3 2,220, T4 460. Draw **T1 = 500, T2 = 500, T3 = 500** (uniform random
within tier, fixed seed) and **T4 = take-all (~460)** ⇒ ≈ **1,960** event markets.
**Expansion rule (rule-based, NOT optional stopping):** after a tier is processed, if its F2′ or
F3′ per-tier proportion statistic has a 95% CI half-width **> 0.05**, that tier is expanded
**once** to **N = 1,000** by drawing the next markets from the **same frozen frame in the same
seeded order**. T4 cannot expand (take-all); its weaker mega-tier precision is **disclosed, not
patched**.

**A2.4 — Secondary (recurring) sample (frozen).** Same four tiers, **250 per tier** (uniform
random, fixed seed); T4 recurring population is only **66 ⇒ take-all ~66** (the mega-tier
event-vs-recurring contrast is inherently weaker there — disclosed). ≈ **1,000** recurring
markets. Used **only** for the **within-tier** event-vs-recurring concentration contrast
(isolating type-effect from volume-effect); never pooled into the headline.

**A2.5 — Bidirectional classifier audit (pre-registered).** A random sample drawn from **both**
the event-labelled and recurring-labelled populations is ground-truth adjudicated **once**, to
measure **both** error directions:
- **false-inclusion** (recurring mislabelled `event` — headline contamination), and
- **false-exclusion** (a genuine one-off event market — e.g. a single marquee fight or knockout
  match **outcome** — mislabelled `recurring` — a representativeness skew away from one-off
  sports toward elections/geopolitics).

Both rates are reported, and the classifier must demonstrably **separate one-off match/fight
outcomes from recurring per-game series templates**. The headline F1′ is reported **both** on
the auto-classified event corpus **and** with audit-flagged residuals removed by a
**deterministic rule frozen in git** (never case-by-case eyeballing); robustness across both is
the contamination test. **Pre-committed escalation:** if the audit shows material conflation of
one-off match outcomes with recurring series, the per-match signal is replaced by a principled
**cardinality rule** (team-masked template cardinality) and re-validated before use.

### A3 — 2026-06-07, post-audit classifier revision + corpus re-freeze (no outcomes)

Step-2.3c's bidirectional audit (n=300, hand-adjudicated; `data/out/audit_results.json`) found
the A2.1 classifier had **7% false-inclusion** (stock/commodity up/down + tweet-count series that
S2/S5 missed) and **16% false-exclusion, 59% of it in T4** — the S5 generic-template signal was
dumping FOMC-by-bps + strikes-by-date **belief** markets into "recurring." Adjudication surfaced
two boundaries, ruled:

**B1 — belief-ladders are event-driven, then deduped.** FOMC-by-bps, strikes-by-date, inflation-
by-N are belief markets, not algorithmic streams ⇒ event. But they are **pseudoreplicates** (the
same macro/geopolitical traders span the whole ladder; one FOMC meeting ≈ 13 correlated markets)
and F1′/F2′/F3′ assume market independence, so each ladder collapses to one representative.

**B2 — bare per-game match outcomes are recurring.** A nightly regular-season game (`nba-X-Y-date`,
no line token) is a high-frequency systematic stream ⇒ recurring; notable one-offs (a numbered UFC
card, a knockout tie) remain event (the audit confirmed marquee matches were absent from the
false-exclusions).

**Unifying principle (what S5 was too blunt to see):** *templated SLICES of a small number of
notable events* (→ event, dedup the slices) vs *a high-frequency STREAM of many distinct low-stakes
outcomes* (→ recurring). Both are templated; slices-of-one ≠ stream-of-many.

**Classifier revision (`pipeline/taxonomy.py`):**
- `recurring` iff a STREAM signal fires: **S1** per-game/lines, **S2** asset up/down + price-
  threshold (now ANY ticker — crypto, stocks, commodities), **S3** weather, **S6** tweet-count
  series (new). Else `event`.
- **Dropped S4** (intraday-duration — misfired on one-off same-day speeches) and **S5's exclusion
  role**. **Removed** the `over|under` line tokens (too generic — hit "win-by-over-N" margin
  slugs); added `euroleague`.
- **S5 repurposed → ladder dedup:** event markets cluster by template stem (slice numbers masked,
  the event's month/year kept); all but the most-liquid member of each cluster are flagged
  `ladder_dup` and excluded from the independent event sample.

**Validation:** revised classifier agrees with the hand-adjudicated ground truth on **298/300
(99%)** — false-inclusion **1.5%** (2 residual edge cases: a tennis match with no date token, a
`will-`-prefixed commodity), false-exclusion **0%**. A2.5's residual-removal robustness check is
satisfied structurally: the ladder dedup IS the deterministic removal, false-exclusion is nil, and
the ~1.5% residual contamination is reported as a known bound.

**Re-freeze (same seed 20260607):** primary (event) **1,961** (T1/T2/T3 = 500, T4 take-all 461);
secondary (recurring) **794** (250/250/250, T4 take-all **44** — thinner mega-tier contrast post-
revision, disclosed); validation 40. **`audit_sample` is preserved** as the frozen independent test
set (it had to be drawn from the pre-revision classification to catch its errors). Ladder dedup
flagged **3,794** duplicates across **1,197** clusters in the V1 event population.

### A4 — 2026-06-07, validation-gate operationalization (pre-run freeze)

Operationalizes the A1.2 escalation trigger for Step 2.5 (2-signal `/trades` vs 3-signal
on-chain MM filter on the 40-market validation subset), frozen **before** the run. Agreement is
judged on each market's **downstream F1 verdict** (survives vs falsified: Gini ≥ 0.60 AND
N_half/n ≤ 0.05), not on MM labels. **Escalate (T4-first) if ANY of:**
- the per-market F1 verdict flips between the 2- and 3-signal filters on **> 15%** of the 40, OR
- the **median |ΔGini|** across the 40 exceeds **0.05**, OR
- **any single one of the 6 T4 markets** flips its F1 verdict (zero-tolerance: the ~449-market
  mega corpus rides entirely on the cheap filter with no other on-chain coverage).

The global 15% / 0.05 thresholds tolerate low-tier boundary jitter (the downstream-verdict
criterion already strips MM-label noise); the T4 single-flip trigger covers the blind spot where
2 of 6 flips is 33% of the tier yet only 5% of the global 40. Escalation self-adjudicates:
expand T4 on-chain — if the larger sample agrees, the flip was boundary noise (filter confirmed);
if it also diverges, a corrupted mega tier was caught before the headline. NegRisk-decoder
validation (A1.3) gates the negRisk markets within the subset.

### A5 — 2026-06-08, truncation handling: de-truncation via the orderbook subgraph (pre-integration freeze)

**Context (verified).** `/trades` enforces a hard `offset ≤ 3000` with a 1000-row page cap → max
reach **4000 rows = 8000/market** per `(market, side)`, returned **recency-first**. High-volume V1
markets therefore return **truncated and time-biased** (nba-okc-den retained only the closing ~7%
of its timeline; the missing fills are the early price discovery). No free-API workaround exists —
`/trades` exposes no working token or timestamp filter (both verified ignored), and the
"side × token 4-way" lever assumed in earlier planning **does not exist**. ~25% of the
volume-stratified validation subset (≈all of T4) is truncated.

**This supersedes the partial-tape provisions.** The earlier "analyze the available tape, carry
`trades_truncated`, report with/without" path is **withdrawn**: a recency slice measures a
market's closing frenzy, not the market, and the bias varies per market with no correction.
Handling is now **binary per market**:

1. **Recover.** A `trades_truncated` market is **de-truncated to a COMPLETE tape** and analyzed
   normally — no partial-tape analysis is ever reported. Source: the **Goldsky orderbook
   subgraph** (`orderbook-subgraph/0.0.1`), which indexes the full V1 era (earliest fill
   2022-11-21 → 2026-04-28 migration cutoff = the corpus boundary) with cursor pagination and
   **no offset cap**. Its per-order `OrderFilled` legs map to canonical taker-oriented aggressor
   fills via the aggressor **self-leg** (`taker == Exchange == OrdersMatched.takerOrderMaker`),
   correct under the mint/merge mechanic. The aggressor tape *and* the maker-inclusive flatness
   substrate come from **one pull, not two**: the full legs **are** the substrate, and the
   aggressor collapse is a view over those same legs.

2. **Completeness-gate, then exclude.** Every recovered tape is gated before it is trusted:
   - **Pagination-exact (primary, tolerance-free):** the paginated leg count must equal the
     subgraph's own `Σ tradesQuantity` aggregate (indexer-computed) — catches an incomplete read
     *on our side* exactly (validated on nba: 17252 == 17252).
   - **Volume cross-check (loose secondary):** recovered collateral volume vs Gamma `volumeNum`
     at a loose tolerance — a coarse backstop for a gross *subgraph* indexing omission the
     aggregate alone can't catch (a dropped fill lowers `tradesQuantity` too). **The tolerance is
     not a free parameter: it is calibrated once, before the batch, from the Gamma-vs-recovered
     discrepancy observed on the known-complete (un-truncated, exact-count-verified) markets — set
     to admit that benign definitional gap while still flagging a gross omission — and reported
     as-derived, never tuned to corpus F1/F2/F3 outcomes.**
   - A market failing either is escalated to a per-market **getLogs spot-check**; one still
     uncompletable is **excluded** as a **coverage gap**, headline reported **with and without**
     it. Given full-V1, uncapped, count-independent pagination, this branch is **expected empty**.

**Trust gated by two pre-registered bars — both PASSED before any corpus market is de-truncated**
(`pipeline/verify_subgraph.py`, `data/out/subgraph_validation.json`):
- **Bar 1** — mapped subgraph fills match the trusted un-truncated `/trades` tape **exactly**, on
  **both** exchange paths: CTF (biden 2716/2716) and NegRisk (atlanta-braves 6946/6946).
- **Bar 2** — truncated nba (CTF): on-chain `getLogs` certifies beyond-ceiling with no ambiguity —
  (2a) getLogs vs `/trades` overlap exact (4947/4947), (2b) subgraph vs now-trusted getLogs on the
  full aggressor tape exact (7382/7382, incl. 2435 beyond-ceiling), (2c) **raw legs** reconcile
  exactly (17252/17252), validating the **maker-leg flatness substrate**, not just the aggressor
  collapse. 1.49× de-truncation. `getLogs` (exchange-wide `OrderFilled` sweep, token-filtered
  inline) is the bounded independent verifier / gap-filler — never the bulk source.

**Disclosed residual (negRisk beyond-ceiling).** Bar 2's getLogs certification is **CTF-only**
(nba). NegRisk completeness *past the ceiling* is therefore not *directly* getLogs-certified; it
rests on bar 1's exact at/below-ceiling negRisk match (atlanta-braves) + the subgraph's
exchange-agnostic, uncapped, count-independent pagination + the per-market completeness gate
above. A narrow, stated residual — not a silent assumption.

**Reconciliation discipline.** All comparisons are on **mapped canonical aggressor fills** (not
raw dual-leg rows — a raw compare mis-counts ~2× by construction) and **raw 6-dp integer token
amounts** (not decimal-scaled floats). Aggregates (n_fills, Gini, F1) match by construction once
fills do.

**Corpus impact.** A5 changes only how truncated members' tapes are *sourced*, not corpus
composition: the frozen primary/secondary draws are preserved; truncated members are recovered in
place (expected: all of them).
