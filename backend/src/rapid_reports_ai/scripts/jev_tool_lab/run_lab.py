"""Run arms x runs over S1 items and append ArmResults as JSONL (spec §5 phase 2).

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.run_lab \
        --items test_cases/jev_tool_lab/s1_pilot.json --out-dir $LAB_OUT --runs 2 --d-runs 1 [--reuse old.jsonl ...]

A is run first in each run because B falls back to A's result for the same item and run (eval economy: the
fallback reuses A rather than calling Qwen again)."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
from typing import Dict, List, TextIO

from dotenv import load_dotenv

from .arms import ArmResult, arm_a, arm_b, arm_c, arm_cb, arm_d, arm_e1, arm_e2
from .scenarios import S1Item

CONCURRENCY = 4


def key(arm: str, item_id: str, run: int) -> str:
    return f"{arm}|{item_id}|{run}"


def load_reuse(paths: List[str]) -> Dict[str, ArmResult]:
    done: Dict[str, ArmResult] = {}
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = ArmResult.model_validate_json(line)
                if r.error is None:
                    done[key(r.arm, r.item_id, r.run)] = r
    return done


async def run_lab(items: List[S1Item], arms: List[str], runs: int, d_runs: int, out: TextIO,
                  reuse: Dict[str, ArmResult]) -> None:
    done = dict(reuse)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def go(arm: str, item: S1Item, r: int, make) -> ArmResult:
        k = key(arm, item.id, r)
        if k in done:
            return done[k]
        async with sem:
            res = await make()
        out.write(res.model_dump_json() + "\n")
        out.flush()
        done[k] = res
        return res

    for r in range(1, runs + 1):
        a: Dict[str, ArmResult] = {}
        if "A" in arms or "B" in arms:
            got = await asyncio.gather(*(go("A", it, r, lambda it=it: arm_a(it, run=r)) for it in items))
            a = {x.item_id: x for x in got}
        jobs = []
        for it in items:
            if "A0" in arms:
                jobs.append(go("A0", it, r, lambda it=it: arm_a(it, run=r, reasoning=False)))
            if "B" in arms:
                jobs.append(go("B", it, r, lambda it=it: arm_b(it, run=r, fallback=a[it.id])))
            if "C" in arms or "Cb" in arms:
                jobs.append(go("C", it, r, lambda it=it: arm_c(it, run=r)))
            if "D" in arms and r <= d_runs:
                jobs.append(go("D", it, r, lambda it=it: arm_d(it, run=r)))
            if "E1off" in arms:
                jobs.append(go("E1off", it, r, lambda it=it: arm_e1(it, run=r, reasoning=False)))
            if "E1on" in arms:
                jobs.append(go("E1on", it, r, lambda it=it: arm_e1(it, run=r, reasoning=True)))
            if "E2" in arms:
                jobs.append(go("E2", it, r, lambda it=it: arm_e2(it, run=r)))
        results = await asyncio.gather(*jobs)
        if "Cb" in arms:                              # C-blank control reuses C's plan for the same item and run
            c = {x.item_id: x for x in results if x.arm == "C"}
            await asyncio.gather(*(go("Cb", it, r, lambda it=it: arm_cb(it, run=r, c_result=c[it.id])) for it in items))


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--arms", default="A,A0,B,C,Cb,D")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--d-runs", type=int, default=1)
    ap.add_argument("--reuse", nargs="*", default=[])
    args = ap.parse_args()
    items = [S1Item(**x) for x in json.loads(Path(args.items).read_text())]
    out_path = Path(args.out_dir) / f"results_{os.getpid()}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The agent runner prints; silence stdout once for the whole run (a per-call redirect breaks under concurrency).
    with out_path.open("a") as out, contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(run_lab(items, args.arms.split(","), args.runs, args.d_runs, out, load_reuse(args.reuse)))
    print(out_path)


if __name__ == "__main__":
    main()
