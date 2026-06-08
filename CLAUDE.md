# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Tail** is a research study + essay + interactive demo testing one thesis about prediction markets:

> A prediction-market price is **not** the average of many minds. It is the **net directional position of a few large, aggressive wallets**, while the crowd is mostly liquidity and echo. **Concentration is the headline.**

Three claims, demo last: **Claim 1 — concentration (the headline)**, **Claim 2 — the movers are right**, **Claim 3 — the crowd echoes (non-causal coda)**. Deliverables: an arXiv-ready paper, a Swartz-voiced blog post, and a terminal-skinned Next.js demo that reads static `data/out/` JSON on Vercel.

## Working agreement (overrides default behavior)

Execute **strictly one step at a time**. After **every** step: (1) summarize what was done/found in a few lines, (2) ask a batched set of clarifying questions about the next step, (3) **stop and wait** — even when the next step seems obvious. Never bundle steps; never skip the pause. Commit after each validated step. This cadence is the point: check-ins are frequent by design.

## Hard constraints (non-negotiable, baked into the method)

- **Free only.** Public APIs (Polymarket Gamma + Data API, no auth), free Polygon RPC. No paid services, no hosted backend, no database.
- **Deterministic compute.** No LLM calls at runtime in the pipeline. Everything reproducible from cached raw data.
- **Falsification before analysis.** Criteria are written and frozen *before* data is touched. Negative results are reported with equal prominence. If the thesis is wrong, say so plainly. Thresholds are never tuned after seeing data — deviations become numbered, dated **amendments**, not edits.

## Project phases & where the live status lives

Four phases, demo last: **Phase 1** (one market, end to end — a cheap gut-check) is complete and validated; **Phase 2** (build + run the corpus) is in progress; **Phase 3** (paper + blog) and **Phase 4** (terminal-skinned demo on the precomputed JSON) follow.

The Phase-1 verdict is **n = 1, descriptive only, zero inferential weight** — the corpus is what converts the within-market F1/F2/F3 into population-level tests. **No writeup may state any claim as established until the corpus speaks.**

**Step-level current status is deliberately NOT tracked in this file** (it's volatile). It lives in the auto-loaded memory index (`MEMORY.md` → `phase2-progress.md`) and the git log (one commit per validated step). Read those to learn what's done and what's next; keep CLAUDE.md for durable guidance only.

## The two frozen pre-registration documents — READ BEFORE CHANGING METHOD

- **`FALSIFICATION.md`** — the Phase-1 single-market freeze. Defines the canonical frame (token-0 space, truth-signed price `p*`), the MM filter, attribution, and the **F1/F2/F3** falsification thresholds. Stands unchanged as the historical record.
- **`CORPUS_PREREG.md`** — the Phase-2 corpus freeze. *Extends* (does not modify) `FALSIFICATION.md`; where it is silent, the Phase-1 definitions carry forward verbatim. Contains the scope freeze (V1-only) and amendments **A1–A4**. Every method change since Phase 1 lives here as a numbered amendment with its rationale. **When in doubt about why something is the way it is, the answer is almost always an amendment in this file.** Do not silently change a frozen parameter — add an amendment.

Frozen falsification thresholds (do not change without an amendment): **F1** Gini `≥ 0.60` AND `N_half/n_directional ≤ 0.05` (load-bearing; must survive flatness bands 0.10/0.15/0.20). **F2** top-K movers must beat **Null B** (volume-matched random wallets — the "smart vs. rich" test). **F3** echo peak `|ρ| ≥ 0.15` at a positive lag AND above the block-bootstrap 95th-pct band.

## Architecture

JSON is the only interface between halves: `pipeline/` (Python) produces JSON; `demo/` (Phase 4, not yet built) consumes `data/out/` JSON as static files. There is no shared runtime, no API layer.

**Two layers inside `pipeline/`:**

1. **Reusable core modules** (the library — the validated machinery):
   - `ingest.py` — Gamma + Data API pulls, throttle/backoff/429, `/trades` pagination (pages BUY/SELL to beat the ~10k offset ceiling), `/holders`, `breadth_probe` (MM signal B), raw-JSON cache under `data/raw/`.
   - `onchain.py` — the role-join. Fetches Polygon receipts, decodes `OrderFilled`/`OrdersMatched`, recovers the real aggressor and resting makers (see gotchas), caches decoded results to JSONL (resumable). Generic over CTF vs NegRisk exchange.
   - `schema.py` — canonical per-fill record in token-0 space (`p_yes`, signed `d`, truth-signed `d_star`), per-wallet aggregates. Works with or without the on-chain decode (`decoded_by_tx={}` → role unknown).
   - `mm_filter.py` — three-signal MM classifier (A flatness, B breadth, C on-chain role). Signal C only fires when role coverage `≥ 0.70`; otherwise 2-signal mode (`role_coverage=0.0`). Over-removal is conservative for Claim 1.
   - `attribution.py` — price-path reconstruction, **interval net-flow** attribution (Phase-2 primary) + **per-fill** (robustness companion), Gini/Lorenz/`N_half`, conservation residual, crude-vs-primary Spearman.
   - `claims.py` — Claim 2 (resolution-blind top-mover selection, hold-to-resolution PnL, Nulls A/B/C, bootstrap) and Claim 3 (lead-lag echo).
   - `taxonomy.py` — Phase-2 event-driven vs recurring-algorithmic classifier + ladder dedup. The crux: recurring = a high-frequency **stream of many distinct** low-stakes outcomes; event = a belief about one notable outcome, possibly templated **slices of one** underlying (deduped to one representative per cluster). A market is `recurring` only if a stream signal fires; else `event`.

2. **Step drivers** (thin scripts that orchestrate the core for one step; each prints a summary and writes JSON):
   - **Phase-1, one market** (`*_market.py`, in order): `discover_market` (1.1) → `pull_market` (1.2) → `verify_onchain` (1.3) → `normalize_market` (1.4) → `mm_filter_market` (1.5) → `attribute_market` (1.6) → `claim2_market` (1.7) → `finalize_market` (1.8).
   - **Phase-2, the corpus**: `discover_corpus` → `select_corpus` (enumerate + classify + ladder-dedup) → `freeze_corpus` (seeded draw → primary/secondary/validation/audit sets) → `audit_classifier` (hand-adjudicated n=300 ground truth) → `run_market.py` (the **parameterized reusable per-market pipeline**, 2.4 — this is the Phase-1 machinery generalized, `/trades`-only 2-signal path) → `validate_onchain.py` (2.5 — NegRisk decoder gate + 2-signal-vs-3-signal comparison on the validation subset, applies the A4 escalation gate).

**Data flow:** Gamma (discovery/resolution truth) + Data API `/trades` (the tape) → normalize to token-0 fills → MM filter removes plumbing → attribution credits truth-signed price moves to aggressors → concentration/claims → JSON in `data/out/`. On-chain role (`onchain.py`) is layered in only for the validation subset and any market whose tape exceeds the `/trades` ceiling (`trades_truncated`).

## Commands

Use the venv interpreter directly (Python 3.14): **`.venv/bin/python pipeline/<script>.py`**. Most scripts take a mode arg, e.g.:

```bash
.venv/bin/python pipeline/run_market.py            # smoke test: smallest market per tier
.venv/bin/python pipeline/validate_onchain.py decoder   # NegRisk decoder gate (2.5a)
.venv/bin/python pipeline/validate_onchain.py compare   # full 2-vs-3 signal validation (2.5c)
.venv/bin/python pipeline/audit_classifier.py      # classifier audit vs hand ground truth
```

There is no test suite, linter, or build for the pipeline — each step **validates itself** by printing diagnostics (conservation residual, MM sanity, robustness bands, role coverage) and is sanity-checked at the pause before committing. The "test" of a change is re-running the relevant step driver and reading its summary.

`pip install -r pipeline/requirements.txt` into `.venv` (deps: requests, eth-abi/eth-utils/pycryptodome for raw JSON-RPC log decoding — deliberately **no** web3.py, numpy, scipy, matplotlib).

## Caching & data

- `data/raw/` is **gitignored** (re-pullable). Tapes, receipts, breadth probes cache here keyed by slug; runs are resumable. On-chain decodes cache to JSONL.
- `data/out/` **is tracked** — it's the computed dataset and the demo's eventual input. Treat its JSON as durable artifacts (corpus frames, frozen sample sets, audit/validation results). `audit_sample.json` is a **preserved independent test set** — do not regenerate it on re-freeze.

## Conventions

- **Commits** — one per validated step, message `step <N.N><letter>: <short description>` (e.g. `step 2.5a: NegRisk decoder validation (gate)`). Freezes and amendments get their own commit (e.g. `freeze Phase 2 corpus pre-registration`). Commit only after the step's diagnostics are reviewed at the pause.
- **Amendments, not edits** — a frozen parameter changes only via a numbered, dated amendment appended to `CORPUS_PREREG.md` (A1, A2, …) with its rationale, never an in-place edit to a frozen threshold. The amendment trail *is* the methodological audit log.
- **`thin`, not null** — a market left with fewer than `MIN_DIRECTIONAL` (30) surviving directional wallets is reported `status: "thin"` and held out of the claim statistics; it is **not** counted as a falsification. A ghost town can't test "a few wallets set the price," so it doesn't get a vote either way.
- **Cache naming** (`data/raw/`) — tapes `<slug>_taker.json` / `<slug>_full.json`; breadth probes `breadth_<wallet10>_<slug>.json`; per-market results `results/<slug>.json`; on-chain decodes as resumable JSONL. A re-run reads cache; delete the file to force a fresh pull.

## Hard-won facts (verified live; expensive to rediscover)

- **The Data API `/trades` does not expose maker/taker role** — only `side` (BUY/SELL = direction). Native role lives on-chain (`OrderFilled`/`OrdersMatched`), joined by `transactionHash`. This is the pivot the whole method is built around.
- **`OrderFilled.taker` is usually the Exchange contract, not the real aggressor** — use **`OrdersMatched.takerOrderMaker`**. The per-leg `OrderFilled.maker`s are the resting LPs.
- **Gamma**: offset ceiling ~10k (422 past it); `clobTokenIds`/`outcomes`/`outcomePrices` are JSON-encoded strings; winner = the outcome priced `"1"`; no collateral-token field (USDC.e vs pUSD is not in metadata); `enableOrderBook==True` discriminates CLOB-era markets.
- **V1 vs V2**: V1 = CTF Exchange `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e` + NegRisk Exchange `0xc5d563a36ae78145c45a50134d48a1215220f80a`, USDC.e (6 dp). The ~April-2026 V1→V2/pUSD migration cutoff is enforced **operationally** (exclude any market with V2 on-chain activity), not by a hardcoded date. **The corpus is V1-only; V2 is a deferred, separately-verified phase.**
- **Archive RPCs**: only `polygon.drpc.org` and `polygon.gateway.tenderly.co` reliably retain old receipts; rotate with retry-on-null.
- macOS has no `timeout` command; `nohup` detaches background jobs from the harness's completion signal (use a monitor instead).
