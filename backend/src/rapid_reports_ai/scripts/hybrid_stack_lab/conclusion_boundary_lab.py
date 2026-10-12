"""Conclusion boundary: once the radiologist has begun a conclusion, is a later sentence part of it
or a return to describing the images? A Jev choice question, scored on conclusion_boundary.json.

Replaces the hybrid stack's code rule (a link may not reach back across a Conclusion sentence),
which forced a real finding dictated after a mid-read summary into Conclusion (c04).

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_lab.conclusion_boundary_lab
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from rapid_reports_ai.jev_client import JEV_MODEL, jev_post  # noqa: E402

HERE = Path(__file__).parent

BOUNDARY_QUESTION = {
    "type": "choice",
    "instructions": ("The radiologist has already begun their conclusion in the dictation. Decide what the "
                     "SENTENCE does."),
    "criteria": {
        "summary": ("It belongs to the conclusion: it summarises, restates or interprets findings already "
                    "given, states a diagnosis, differential, staging or response, or makes a recommendation "
                    "or communication note."),
        "images": ("It returns to describing the images: it reports an observation, measurement or detail "
                   "that the dictation has not already given, as a finding."),
    },
}


def boundary_state(before: list[str], sentence: str) -> str:
    return "DICTATION SO FAR:\n" + " ".join(before) + "\n\nSENTENCE:\n" + sentence


async def ask_boundary(before: list[str], sentence: str) -> tuple[str, float]:
    """(choice, confidence) from Jev; raises on failure (callers fail open)."""
    r = await jev_post({"model": JEV_MODEL, "state": boundary_state(before, sentence),
                        "questions": {"boundary": BOUNDARY_QUESTION}},
                       os.environ["OPENROUTER_API_KEY"], 10.0)
    r.raise_for_status()
    a = r.json()["answers"]["boundary"]
    return a["choice"], float(a.get("confidence") or 0.0)


async def main(argv: list[str]) -> None:
    items = json.loads((HERE / "conclusion_boundary.json").read_text())["items"]
    sem = asyncio.Semaphore(8)

    async def one(it):
        async with sem:
            try:
                return it, *(await ask_boundary(it["before"], it["sentence"]))
            except Exception as e:
                return it, f"error {type(e).__name__}", 0.0
    res = await asyncio.gather(*(one(it) for it in items))
    wrong = [(it, c, p) for it, c, p in res if c != it["gold"]]
    for src in ("lab", "synthetic"):
        rows = [(it, c, p) for it, c, p in res if it["source"] == src]
        ok = sum(1 for it, c, _ in rows if c == it["gold"])
        print(f"{src}: {ok}/{len(rows)}")
    for g in ("summary", "images"):
        rows = [(it, c, p) for it, c, p in res if it["gold"] == g]
        print(f"gold {g}: {sum(1 for it, c, _ in rows if c == g)}/{len(rows)}")
    confs = sorted(p for _, c, p in res)
    print(f"confidence min {confs[0]:.2f} p10 {confs[len(confs) // 10]:.2f}")
    for it, c, p in wrong:
        print(f"  ✗ {it['id']}: gold {it['gold']} got {c} ({p:.2f}) | {it['sentence'][:90]}")
    for it, c, p in sorted(res, key=lambda x: x[2])[:6]:
        print(f"  low {p:.2f} {c:8} {it['id']}: {it['sentence'][:80]}")
    out = Path(os.environ.get("LAB_OUT", ".")) / f"boundary_{os.getpid()}.json"
    out.write_text(json.dumps([{**it, "choice": c, "confidence": p} for it, c, p in res], indent=1))
    print("saved", out)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
