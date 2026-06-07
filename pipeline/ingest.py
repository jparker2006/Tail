"""Data ingestion — Gamma + Data API pulls and the on-chain role join.

Responsibilities (Phase 1, Steps 1.1–1.3):
- Gamma API: resolve a market to conditionId, clobTokenIds, outcomes, outcomePrices
  (resolution truth), volumeNum, negRisk, time window.
- Data API: page /trades (on side x token to beat the ~10k offset+limit ceiling) and
  /holders; cache raw JSON under data/raw/. Throttle; handle 429.
- On-chain: eth_getLogs OrderFilled / OrdersMatched from the correct V1 Exchange contract
  (CTF vs NegRisk, routed by the negRisk flag) for the market's asset IDs, chunked ~2k
  blocks with backoff and free-RPC rotation; index by transactionHash for the role join.

Built incrementally, one step at a time. Nothing here runs yet.
"""
