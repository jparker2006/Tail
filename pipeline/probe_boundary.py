"""Discriminate H1 (index asymmetry) vs H2 (sustained load) for the 380k-leg timeout.

On a FRESH shard (no prior pagination load), time the min/max-timestamp boundary probe for each
asset field independently. If takerAssetId times out fresh too -> H1 (the orderBy:timestamp sort is
index-less at this scale, deterministic). If both return fast -> H2 (the field-2 death was load).
Limited retries + short timeout so it returns quickly either way.
"""
from __future__ import annotations

import json
import sys
import time

import requests

sys.path.insert(0, sys.path[0] or "pipeline")
import subgraph as sg

SLUG = sys.argv[1] if len(sys.argv) > 1 else "southampton-wins-the-premier-league"


def boundary_one(field: str, tok: str, direction: str):
    """One first:1 orderBy:timestamp probe, short timeout, 2 tries — time it or report timeout."""
    q = ("query($a:String!){ orderFilledEvents(first:1, orderBy:timestamp, orderDirection:%s, "
         "where:{" + field + ":$a}){ timestamp } }") % direction
    t0 = time.time()
    for _ in range(2):
        try:
            r = sg._session.post(sg.SUBGRAPH_EP, json={"query": q, "variables": {"a": tok}},
                                 timeout=45)
            j = r.json()
            if "errors" in j and not j.get("data"):
                msg = str(j["errors"])
                if sg.is_timeout(msg):
                    return ("TIMEOUT", time.time() - t0)
                return (f"ERR {msg[:60]}", time.time() - t0)
            ev = j["data"]["orderFilledEvents"]
            return (ev[0]["timestamp"] if ev else "empty", time.time() - t0)
        except requests.RequestException as e:
            last = f"net {e}"
    return (last, time.time() - t0)


def main() -> None:
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    m = {x["slug"]: x for x in prim + sec}.get(SLUG)
    toks = m["clobTokenIds"] if isinstance(m["clobTokenIds"], list) else json.loads(m["clobTokenIds"])
    agg = sg.orderbook_aggregate(toks)
    print(f"=== boundary probe (fresh shard): {SLUG}  tq={agg['trades_quantity']:,} ===", flush=True)
    print(f"per_token legs: {agg['per_token']}", flush=True)
    # taker FIRST (the field that died), to test on a fresh shard
    for field in ("takerAssetId", "makerAssetId"):
        for tok in toks:
            for d in ("asc", "desc"):
                res, dt = boundary_one(field, str(tok), d)
                print(f"  {field:14} {str(tok)[:14]}.. {d:4} -> {str(res)[:40]:40} ({dt:.1f}s)",
                      flush=True)


if __name__ == "__main__":
    main()
