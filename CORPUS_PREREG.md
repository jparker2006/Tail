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
