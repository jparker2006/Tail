"""Price-discovery attribution and concentration metrics (Phase 1, Step 1.6).

Reconstructs the executed price path, attributes each truth-signed increment to the
aggressor (per-fill primary method), computes per-wallet contribution C_w with the
conservation check, the crude net-notional cross-check, and the concentration backbone:
Gini, Lorenz, top-N share, N_half. See FALSIFICATION.md for frozen definitions.

Built incrementally. Nothing here runs yet.
"""
