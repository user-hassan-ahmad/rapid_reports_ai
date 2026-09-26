"""D-01 before/after: Jev bundle latency with a client per request vs one shared
keep-alive client, interleaved in one run so network drift hits both arms alike.

Arms (same real bundle bodies from the triage fixtures, order alternating per round):
  fresh   a new client per call (the pre-D-01 behaviour, RR_JEV_FRESH_CLIENT=1)
  shared  the pooled client, already warm
  cold    close the pool, wait, then the first call on a new client (what the
          socket-open warm-up absorbs)
The very first call of the process (DNS included) is reported on its own.

Usage (from backend/):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.jev_latency_ab', run_name='__main__')" [--rounds 60] [--cold 20]

Never run by pytest. Writes docs/model-migration/jev-client-latency-<date>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, quantile

OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "triage_utterances.jsonl"


def summarise_arms(arms: dict[str, list[int]]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "n": len(v),
            "p50": quantile(v, 0.5),
            "p50_ci": list(bootstrap_quantile_ci(v, 0.5)),
            "p95": quantile(v, 0.95),
            "p95_ci": list(bootstrap_quantile_ci(v, 0.95)),
        }
        for name, v in arms.items()
    }


async def _call(state) -> int:
    from rapid_reports_ai.utterance_bundle import get_jev_bundle

    return (await get_jev_bundle().classify(state)).latency_ms


async def _fresh(state) -> int:
    os.environ["RR_JEV_FRESH_CLIENT"] = "1"
    try:
        return await _call(state)
    finally:
        os.environ.pop("RR_JEV_FRESH_CLIENT", None)


async def main() -> int:
    from rapid_reports_ai import jev_client
    from rapid_reports_ai.scripts.bundle_parity import triage_state

    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--cold", type=int, default=20)
    ap.add_argument("--cold-gap-s", type=float, default=3.0)
    args = ap.parse_args(sys.argv[1:])
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    os.environ.pop("RR_JEV_FRESH_CLIENT", None)
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    states = [triage_state(c) for c in cases]

    process_first = await _call(states[0])  # DNS + TCP + TLS + route, once per process
    arms: dict[str, list[int]] = {"fresh": [], "shared": [], "cold": []}
    errors = 0
    for i in range(args.rounds):
        st = states[i % len(states)]
        order = ("fresh", "shared") if i % 2 == 0 else ("shared", "fresh")
        for arm in order:
            try:
                arms[arm].append(await (_fresh(st) if arm == "fresh" else _call(st)))
            except Exception as e:
                errors += 1
                print(f"   {arm} error {type(e).__name__}", file=sys.stderr)
    for i in range(args.cold):
        await jev_client.aclose()
        await asyncio.sleep(args.cold_gap_s)
        try:
            arms["cold"].append(await _call(states[i % len(states)]))
        except Exception as e:
            errors += 1
            print(f"   cold error {type(e).__name__}", file=sys.stderr)
    await jev_client.aclose()

    s = summarise_arms(arms)
    print(f"== Jev bundle latency, fresh vs shared client  errors={errors}  process-first={process_first}ms")
    for name, v in s.items():
        print(f"   {name:<7} n={v['n']:<4} p50={v['p50']}ms {v['p50_ci']}  p95={v['p95']}ms {v['p95_ci']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"jev-client-latency-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "process_first_ms": process_first, "errors": errors, "arms": arms}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
