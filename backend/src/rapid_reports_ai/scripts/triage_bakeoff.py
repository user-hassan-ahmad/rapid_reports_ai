"""Run the fixture set through both triage candidates, live, and print/save a summary.

Usage (from backend/, keys in .env):
    set -a; . ./.env; set +a
    .venv/bin/python -m rapid_reports_ai.scripts.triage_bakeoff [--only jev|qwen] [--concurrency 4]

Never run by pytest. Writes docs/model-migration/triage-bakeoff-<date>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from rapid_reports_ai.dictation_triage import TriageState, get_triager
from rapid_reports_ai.scripts.triage_summary import Record, format_summary, summarise

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "triage_utterances.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


async def run_case(case: dict, candidates: list[str], sem: asyncio.Semaphore) -> list[Record]:
    state = TriageState(case["committed"], case["active"], case["utterance"], case.get("scan_type", ""))
    out: list[Record] = []
    async with sem:
        for cand in candidates:  # sequential per case so the two latencies are not contended
            try:
                d = await get_triager(cand).classify(state)
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=d.action,
                    confidence=d.confidence, latency_ms=d.latency_ms, cost_usd=d.cost_usd, hard=case["hard"],
                    error=None, is_correction=d.is_correction, expected_is_correction=case["expected_is_correction"],
                    needs_committed_edit=d.needs_committed_edit,
                    expected_needs_committed_edit=case["expected_needs_committed_edit"],
                ))
            except Exception as e:
                out.append(Record(
                    id=case["id"], candidate=cand, expected_action=case["expected_action"], action=None,
                    confidence=None, latency_ms=0, cost_usd=None, hard=case["hard"], error=type(e).__name__,
                    is_correction=None, expected_is_correction=None, needs_committed_edit=None,
                    expected_needs_committed_edit=None,
                ))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["jev", "qwen"])
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    missing = [k for k in ("OPENROUTER_API_KEY", "CEREBRAS_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2

    candidates = [args.only] if args.only else ["jev", "qwen"]
    cases = load_cases()
    sem = asyncio.Semaphore(args.concurrency)
    nested = await asyncio.gather(*(run_case(c, candidates, sem) for c in cases))
    records = [r for rs in nested for r in rs]

    summary = summarise(records)
    print(format_summary(summary))
    wrong = [r for r in records if r.error is None and r.action != r.expected_action]
    if wrong:
        print("\n-- disagreements --")
        for r in wrong:
            print(f"   {r.candidate:<4} {r.id:<14} expected={r.expected_action:<26} got={r.action} conf={r.confidence}")
    errors = [r for r in records if r.error]
    if errors:
        print("\n-- errors --")
        for r in errors:
            print(f"   {r.candidate:<4} {r.id:<14} {r.error}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"triage-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": summary, "records": [r.__dict__ for r in records]}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
