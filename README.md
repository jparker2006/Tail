# Tail

Testing one thesis about prediction markets:

> A prediction-market price is **not** the average of many minds. It is the **net directional
> position of a few large, aggressive wallets**, while the crowd is mostly liquidity and echo.
> **Concentration is the headline.**

Three deliverables (demo last): an arXiv-ready **paper**, a blog post for *echo*, and a
terminal-skinned **demo** with real data-viz served as static JSON on Vercel.

## Status

**Phase 1 — one market, end to end** (a cheap gut-check before scaling). See
[`FALSIFICATION.md`](./FALSIFICATION.md) for the pre-registered criteria (frozen before any
analysis) and the plan for the full phased build.

## Constraints

- **Free only** — public APIs (Polymarket Gamma + Data API), free Polygon RPC. No paid
  services, no hosted backend, no database.
- **Deterministic** — no LLM calls at runtime in the pipeline.
- **Falsification first** — criteria written and frozen before any data is touched; negative
  results reported honestly.

## Layout

```
pipeline/   Python — pulls data, computes findings, emits JSON
data/raw/   cached raw API + on-chain responses (gitignored)
data/out/   computed JSON (the demo's dataset)
demo/       Next.js + React (Phase 4) — reads data/out JSON as static files
```

## Data sources

- **Gamma API** (`gamma-api.polymarket.com`, no auth) — market discovery, metadata,
  resolution (`outcomePrices`), `conditionId`, `clobTokenIds`, `negRisk`.
- **Data API** (`data-api.polymarket.com`, no auth) — `/trades` (wallet-level), `/holders`.
- **On-chain** (Polygon, free RPC) — `OrderFilled` / `OrdersMatched` from the CTF / NegRisk
  Exchange for native maker/taker role (the public Data API does **not** expose it), joined
  to off-chain trades by `transactionHash`.

## Running

Pipeline entrypoint (Phase 1): `python pipeline/run_market.py` _(built incrementally — see
the plan)._
