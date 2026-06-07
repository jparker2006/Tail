# Pre-Registration & Falsification Criteria — Tail

**Written 2026-06-06, BEFORE any data has been analyzed.** This document is frozen. It
commits, in advance, to the definitions, methods, and numeric thresholds by which the Tail
thesis can be **falsified** — so that no threshold can be tuned after seeing the data.
Negative results are reported with equal prominence to positive ones. If the thesis is
wrong, we say so plainly.

---

## The thesis

> A prediction-market price is **not** the average of many minds. It is the **net
> directional position of a few large, aggressive wallets**, while the crowd is mostly
> liquidity and echo.

Decomposed into three claims:

- **Claim 1 — Concentration (the headline).** A tiny share of wallets drives most of the
  net price movement (price discovery) in a resolved market.
- **Claim 2 — The movers are right.** Those top movers have real edge against the eventual
  resolution. (Interesting either way — whether they are smart or merely rich.)
- **Claim 3 — The crowd echoes (hedged coda).** Small wallets trade in the same direction
  shortly *after* big wallets move. Reported as timing/association only — **no causal
  claim**.

---

## Frozen definitions (cannot change post-hoc)

- **Canonical frame.** Collapse both outcome tokens to **token-0 ("Yes") space**. Price
  `p ∈ [0,1]`. Resolution truth `R ∈ {0,1}` read from Gamma `outcomePrices` (winner = `"1"`).
  **Truth-signed price** `p* = p if R==1 else 1−p`; any rise in `p*` is convergence toward
  truth. Fill direction `d = +1 if (outcome_index==0)==(side=="BUY") else −1`;
  truth-signed direction `d_star = d if R==1 else −d`.
- **Market-maker (MM) filter — three signals.** A wallet is scored on:
  (A) **inventory flatness** `= |net_shares| / gross_shares` (MM-like if `< 0.15` above a
  volume floor); (B) **cross-market breadth** (many distinct markets + tiny share of volume
  in this market = MM); (C) **native role** from on-chain `OrdersMatched.takerOrderMaker`
  vs. `OrderFilled.maker` (low aggressor-share = MM), used only when role coverage `≥ 0.70`.
  A wallet is removed from the directional universe if **≥ 2 signals** fire MM-like (or a
  single unmistakable flatness + top-decile-volume signal). Over-removal is conservative for
  Claim 1 — it can only *lower* measured concentration.
- **Price-discovery attribution (primary).** Reconstruct the executed price path from the
  trade tape. Each fill's truth-signed price change `Δ*_t` is credited to the **aggressor**
  of that fill (resting makers get zero; when role is unknown, credit the trade's
  `proxy_wallet`). Wallet contribution `C_w = Σ Δ*_t` over its fills; wrong-way pushes are
  naturally negative. Conservation must hold: `Σ_w C_w = p*_end − p*_0`.
- **Crude cross-check.** Each wallet's net truth-signed notional. Concentration must not be a
  microstructure artifact: report Spearman rank correlation between primary `C_w` and crude.
- **Concentration metrics.** Gini coefficient + Lorenz curve over **positive** contributors
  (headline), plus `|C_w|` and net-flow variants as robustness. `N_half` = the fewest
  wallets reaching 50% of total forward (positive) discovery; and `N_half / n_directional`.
- **Realized edge (Claim 2).** Per-wallet hold-to-resolution PnL
  `= Σ_fills d_token · size · (payout − price)`, `payout ∈ {0,1}`.
- **Top-mover selection (Claim 2).** Resolution-blind: rank by **net aggressive directional
  size** (primary) / **gross aggressive volume** (robustness), never by `C_w`. See F2.
- **Echo lead-lag (Claim 3).** Bin the tape (5 min default). Cohorts: **big** = top-decile
  gross notional, **small** = bottom-50%. Lagged cross-correlation `ρ(τ)` of big-wallet net
  flow vs. subsequent small-wallet net flow; block-bootstrap null band; price-chasing
  confound probe `corr(SmallFlow_{b+τ}, Δprice_b)`.

---

## Falsification criteria (frozen thresholds)

The thesis (or a specific claim) is reported **FALSIFIED** for a market if:

### F1 — Concentration is broad → kills Claim 1 (load-bearing)
After MM removal, **either**:
- headline positive-contributors **Gini `< 0.60`**, **OR**
- **`N_half / n_directional > 0.05`** (it takes more than 5% of directional wallets to reach
  half of discovery — the bar for the word "tiny"). The absolute `N_half` ("N wallets = half")
  is reported alongside as the headline number.
- **Robustness rider:** the conclusion must hold across MM flatness-threshold bands
  **{0.10, 0.15, 0.20}**. If concentration appears only at one knife-edge threshold, Claim 1
  is reported **not robust** even if one band passes.
- **F1 is load-bearing:** if F1 fires, the headline thesis is falsified for this market
  regardless of F2/F3.

### F2 — Movers aren't right → kills Claim 2
- **"Top movers" are selected resolution-blind, to avoid circularity:** rank wallets by
  **net directional position size** `|Σ signed_notional|` built via aggressive (taker) fills
  (primary), with **gross aggressive volume** as a robustness ranking. They are **not** ranked
  by truth-signed discovery contribution `C_w` — selecting on correctness and then testing
  correctness would be circular. (Claim 1's concentration ranking *does* use `C_w`; that is not
  circular because Claim 1 measures concentration *of* discovery, not accuracy.) When role is
  unavailable (Data-API-only fallback), "aggressive" degrades to all of the wallet's fills.
- Dies if the top-`K` movers (**K = 10**; also report K = 5, 20) **fail to beat Null B**
  (volume-matched random wallets) at the **95th percentile** on hold-to-resolution PnL.
- **Honesty rider:** if movers beat **Null A** (random direction) but fail **Null B**, report
  as **"rich, not smart"** — a partial falsification that is itself a finding.
- Nulls use **B = 10,000** bootstrap draws. Null A randomizes each fill's direction at the
  **market base rate**; Null B draws K wallets matched on gross-volume decile; Null C shuffles
  fill timestamps.

### F3 — No whale→crowd lead-lag → kills Claim 3
- Dies **unless** there is a positive lag `τ ∈ (0, 60 min]` where the big→small
  cross-correlation satisfies **both**: (i) `ρ_peak ≥ 0.15` in magnitude, **and** (ii)
  `ρ_peak` exceeds the **block-bootstrap null band (95th percentile)** — magnitude *and*
  statistical significance, not magnitude alone. Also dies if the peak occurs at a
  non-positive lag (crowd leads or is simultaneous, refuting "crowd echoes after").

---

## Frozen Phase-1 parameter choices (defaults; locked for the gut-check)

| Parameter | Frozen value |
|---|---|
| F1 Gini cutoff | **0.60** |
| F1 `N_half / n_directional` cutoff | **0.05** |
| F3 `\|ρ\|` cutoff | **0.15** |
| MM flatness threshold (+ robustness bands) | **0.15** (bands 0.10 / 0.15 / 0.20) |
| MM volume floor `MM_MIN_NOTIONAL` | `max($5k, 0.5% · volumeNum)` |
| Role-coverage threshold for using Signal C | **0.70** |
| Attribution regime | **per-fill** (primary); interval net-flow = cross-check |
| Claim-2 top-K | **10** (report 5, 20) |
| Claim-2 top-mover ranking | **net aggressive directional size** (primary); gross aggressive volume (robustness) — resolution-blind |
| F3 echo test | `\|ρ_peak\|` ≥ **0.15** **and** exceeds block-bootstrap 95th-pct band |
| Null bootstrap draws B | **10,000** |
| Null A base rate | **market base rate** (not coin) |
| Claim-3 bin width / max lag | **5 min** / **60 min** |
| Proxy identity | per-`proxyWallet` (headline); top-20 funding-cluster = sensitivity only |

---

## Reporting commitments

1. **Single-market caveat (Phase 1).** All significance statements in Phase 1 are
   *within-market descriptive only*. One market cannot establish a population-level edge;
   cross-market significance is Phase 2. Phase 1 is a gut-check on whether the machinery is
   worth scaling — not a proof.
2. **Multi-proxy caveat.** One person can run several proxy wallets (the 2024 election whale
   ran four). Per-proxy concentration is conservative; per-cluster concentration can only be
   higher. Both are reported.
3. **Negatives published.** If F1/F2/F3 fire, we report the falsification honestly and with
   equal prominence. We pre-commit to publishing the negative.
4. **No silent truncation.** If the trade tape is truncated by pagination, the market is
   flagged (`trades_truncated`) and not reported on as if complete.
