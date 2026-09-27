"""Score a tier-2 scratchpad audit on the labelled fixture (tests/fixtures/audit_cases.jsonl).

A planted issue is caught when a flag overlaps the statement it quotes; any flag on a clean
case is a false flag. Prints counts, per-case outcomes and latency.

    PYTHONPATH=src python -m rapid_reports_ai.scripts.audit_eval model|jev [--json out.json]

Plan: docs/superpowers/plans/2026-09-27-jev-scratchpad-audit.md
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "audit_cases.jsonl"


def load_cases(path: Path = FIXTURE) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def score_case(case: dict, flags: list[dict]) -> dict:
    """flags: [{start, end, kind}]. Pure; used by the tests too."""
    text = case["findings"]
    spans = [(text.find(i["quote"]), text.find(i["quote"]) + len(i["quote"])) for i in case["issues"]]
    caught = [any(f["start"] < e and f["end"] > s for f in flags) for s, e in spans]
    stray = [f for f in flags if not any(f["start"] < e and f["end"] > s for s, e in spans)]
    return {"id": case["id"], "issues": len(spans), "caught": sum(caught), "stray": len(stray),
            "clean": not spans}


async def _run(checker: str, case: dict) -> tuple[list[dict], int]:
    t0 = time.perf_counter()
    if checker == "model":
        from rapid_reports_ai.dictation_semantic import check_semantic
        flags = await check_semantic(case["scan_type"], case["clinical_history"], case["findings"])
    else:
        from rapid_reports_ai.jev_audit import jev_semantic
        flags = await jev_semantic(case["scan_type"], case["clinical_history"], case["findings"])
    ms = int((time.perf_counter() - t0) * 1000)
    return [{"start": f.start, "end": f.end, "kind": f.kind} for f in flags], ms


async def main(argv: list[str]) -> None:
    load_dotenv(".env")
    checker = argv[0]
    cases = load_cases()
    sem = asyncio.Semaphore(4)

    async def one(c):
        async with sem:
            return c, *(await _run(checker, c))

    rows = []
    for c, flags, ms in await asyncio.gather(*(one(c) for c in cases)):
        r = score_case(c, flags) | {"ms": ms, "flags": flags}
        rows.append(r)
    issues = [r for r in rows if not r["clean"]]
    clean = [r for r in rows if r["clean"]]
    ms = sorted(r["ms"] for r in rows)
    print(f"{checker}: caught {sum(r['caught'] for r in issues)}/{sum(r['issues'] for r in issues)} planted issues;"
          f" false flags on {sum(1 for r in clean if r['stray'])}/{len(clean)} clean cases;"
          f" stray flags on issue cases {sum(r['stray'] for r in issues)};"
          f" latency p50 {ms[len(ms) // 2]} ms, max {ms[-1]} ms")
    for r in rows:
        tag = ("CLEAN " if not r["stray"] else "FALSE ") if r["clean"] else ("CAUGHT" if r["caught"] else "MISSED")
        print(f"  {tag} {r['id']:22s} {r['ms']:6d} ms  flags={[f['kind'] for f in r['flags']]}")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
