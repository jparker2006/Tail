"""Phase-1 driver — one market, end to end.

Wires ingest -> schema -> mm_filter -> attribution -> claims for a single market and writes
the result JSON to data/out/ plus a sanity chart. Built incrementally as each step is
validated. Nothing here runs yet.
"""
