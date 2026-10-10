"""Replay dumped prod reports through `engine.run_review` with the dictated gate in shadow, writing one jsonl row per
gate clause. Prod text never enters the repo: point --dumps at a scratchpad directory of dumps
({"rep": {"id", "inp", "report_content", "cr"}}, as the live-audit dump scripts write) and --out at the scratchpad.

    cd backend && PYTHONPATH=src RR_DICTATED_GATE=shadow .venv/bin/python scripts/review_labs/dictated_gate_replay.py \
        --dumps <dir> [<dir> ...] --out <file.jsonl>
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path


async def one(path: Path, fh) -> None:
    from rapid_reports_ai.review_engine import engine
    d = json.loads(path.read_text())
    rep = d["rep"]
    cr = json.loads(rep["cr"] or "{}") if isinstance(rep["cr"], str) else rep["cr"]
    cand = cr[0] if isinstance(cr, list) and cr else cr  # dumps hold candidate_reports, a list; the review reads one
    inp_ = engine.input_from_parts(rep["id"], "quick", json.loads(rep["inp"] or "{}"), cand, None)
    if inp_ is None:
        print(f"{path}: no candidate, skipped")
        return
    inp_.artifacts.report = rep["report_content"]
    t = time.monotonic()
    res = await engine.run_review(inp_, "00000000-0000-0000-0000-0000000000ee")
    ms = int((time.monotonic() - t) * 1000)
    log = res.run.get("dictated_gate") or {}
    key = f"{path.parent.name}-{path.stem}"
    for c in log.get("clauses", []):
        s, e = c.get("start"), c.get("end")
        fh.write(json.dumps({"report": key, **c, "text": rep["report_content"][s:e] if s is not None else None,
                             "ms": ms, "jev_ms": res.run["timings_ms"].get("jev_ms")}) + "\n")
    t0 = log.get("today") or log  # live mode nests today's-path counts under "today"
    print(f"{key}: mode={log.get('mode')} clauses={len(log.get('clauses', []))} today_counts={t0.get('counts')} "
          f"plain_today={t0.get('added_plain_today')} ms={ms} "
          f"errors={sorted(res.run['errors'])}")


async def main(dirs, out):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    assert os.environ.get("RR_DICTATED_GATE") in ("shadow", "live"), "run with RR_DICTATED_GATE=shadow or live"
    with open(out, "w") as fh:
        for d in dirs:
            for p in sorted(Path(d).glob("*.json")):
                if p.stem in ("cases", "ids"):
                    continue
                await one(p, fh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dumps", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    asyncio.run(main(a.dumps, a.out))
