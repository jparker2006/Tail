"""One-market rescue test for the ~380k-leg free-tier-ceiling timeouts.

Runs run_market(use_cache=False) on a single timeout market with the lowered MAX_PAGES_PER_WINDOW
and reports whether the subgraph tape now paginates to completion (A6 is_complete) without a
persistent timeout. Slug via argv[1] (default southampton). Pure diagnostic; writes nothing durable.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, sys.path[0] or "pipeline")
import run_market as rm
import subgraph as sg

SLUG = sys.argv[1] if len(sys.argv) > 1 else "southampton-wins-the-premier-league"


def main() -> None:
    prim = json.load(open("data/out/corpus_primary.json"))["markets"]
    sec = json.load(open("data/out/corpus_secondary.json"))["markets"]
    m = {x["slug"]: x for x in prim + sec}.get(SLUG)
    if not m:
        print(f"MISSING from frame: {SLUG}"); return
    print(f"=== rescue test: {SLUG}  (MAX_PAGES_PER_WINDOW={sg.MAX_PAGES_PER_WINDOW}) ===", flush=True)
    t0 = time.time()
    r = rm.run_market(m, use_cache=False)
    dt = time.time() - t0
    det = r.get("detruncation") or {}
    ci = r.get("concentration_interval") or {}
    n_legs, tq = det.get("n_legs"), det.get("trades_quantity")
    print(f"\nstatus      : {r.get('status')}")
    print(f"tape_source : {r.get('tape_source')}")
    print(f"n_legs      : {n_legs}")
    print(f"trades_qty  : {tq}")
    if n_legs is not None and tq:
        print(f"is_complete : {sg.is_complete(n_legs, tq)}  (legs/tq = {n_legs/tq:.6f})")
    print(f"n_fills     : {r.get('n_fills')}")
    print(f"n_direction : {r.get('n_directional')}")
    print(f"gini        : {ci.get('gini')}")
    print(f"elapsed     : {dt/60:.1f} min")


if __name__ == "__main__":
    main()
