"""Canonical normalized trade schema (Phase 1, Step 1.4).

Collapses both outcome tokens into token-0 ("Yes") space and derives the fields the rest of
the pipeline consumes: p_yes, signed direction d, truth-signed d_star, role, proxy/cluster
identity. See FALSIFICATION.md for the frozen definitions.

Built incrementally. Nothing here runs yet.
"""
