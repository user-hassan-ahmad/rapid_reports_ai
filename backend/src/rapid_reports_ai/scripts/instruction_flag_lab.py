"""Instruction-flag lab (design docs/superpowers/specs/2026-10-15-instruction-flag-design.md): the stack command
question with the `instruction` option, on a synthetic fixture (instructions vs report sentences that look like
instructions) and, for regressions, on the 96-item command fixture.

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.instruction_flag_lab fixture <fixture.json> <out.json>
    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.instruction_flag_lab command <out.json> [off]

Raw answers are written to <out.json>; `score` re-reads one or more of them without calling Jev:

    ... instruction_flag_lab score <out.json> [<out2.json> ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from rapid_reports_ai.hybrid_stack.jev_stack import ask_command, decide_command, held_score  # noqa: E402

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hybrid_stack"
BARS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)


async def _gather(fn, items, n=6):
    sem = asyncio.Semaphore(n)

    async def one(it):
        async with sem:
            err = ""
            for attempt in range(3):
                try:
                    return await fn(it)
                except Exception as e:  # retry transport hiccups, then record
                    err = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(1 + attempt)
            return {"error": err}
    return await asyncio.gather(*(one(it) for it in items))


async def run(items: list[dict], instruction: bool) -> list[dict]:
    res = await _gather(lambda it: ask_command(it["scratchpad"], it["utterance"], it["regions"], it["chips"],
                                               instruction=instruction), items)
    return [{"item": it, "answer": r} for it, r in zip(items, res)]


def _supported(r: dict) -> str | None:
    """A supported command the scratchpad carries out (accept, a delete naming a region), whatever the bar."""
    d = decide_command(r, instruction_min=9.0) if "instruction" in r else decide_command(r)
    if d["action"] == "delete":
        return "delete:region" if d["region"] else None   # a region-less stack delete is not acted on by the scratchpad
    return None if d["action"] == "dictate" else d["action"]


def _held(r: dict, t: float) -> bool:
    return "instruction" in r and decide_command(r, instruction_min=t)["action"] == "instruction"


def _score(r: dict) -> float:
    return held_score(r) if "p_delete" in r else float(r.get("instruction") or 0.0)


def score_fixture(rows: list[dict]) -> None:
    ok = [x for x in rows if "error" not in x["answer"]]
    ins = [x for x in ok if x["item"]["gold"] == "instruction"]
    con = [x for x in ok if x["item"]["gold"] == "content"]
    print(f"answered {len(ok)}/{len(rows)}: {len(ins)} instructions, {len(con)} report sentences")
    print("  choice, instructions:", dict(Counter(x["answer"]["command"] for x in ins)))
    print("  choice, report sentences:", dict(Counter(x["answer"]["command"] for x in con)))
    print("  bar  | report wrongly held | instructions held | + taken as a supported command | left as dictation")
    for t in BARS:
        held = lambda x: _held(x["answer"], t)
        wrong = [x for x in con if held(x)]
        caught = [x for x in ins if held(x)]
        sup = Counter(_supported(x["answer"]) for x in ins if _supported(x["answer"]))
        left = len(ins) - len(caught) - sum(sup.values())
        print(f"  {t:.2f} | {len(wrong)}/{len(con)} | {len(caught)}/{len(ins)} | {dict(sup)} | {left}"
              + (f"   wrong: {[x['item']['id'] for x in wrong]}" if wrong else ""))
    print("  report sentences by held score (P instruction + P delete), highest first:")
    for x in sorted(con, key=lambda x: -_score(x["answer"]))[:8]:
        a = x["answer"]
        print(f"    {_score(a):.2f} {a['command']:<17} {x['item']['id']} {x['item']['utterance']}")
    print("  instructions below 0.8 (or taken as a command):")
    for x in sorted(ins, key=lambda x: _score(x["answer"])):
        a = x["answer"]
        if _score(a) < 0.8 or _supported(a):
            print(f"    {_score(a):.2f} {a['command']:<17} conf {a['confidence']:.2f} "
                  f"{x['item']['id']} [{x['item']['category']}] {x['item']['utterance']}")


def score_command(rows: list[dict]) -> None:
    ok = [x for x in rows if "error" not in x["answer"]]
    print(f"command fixture: answered {len(ok)}/{len(rows)}")
    print("  confusion (gold -> got):", dict(Counter((x["item"]["gold_command"], x["answer"]["command"]) for x in ok)))
    acted = Counter((x["item"]["gold_command"], _supported(x["answer"])) for x in ok if _supported(x["answer"]))
    print("  supported actions taken (gold, action):", dict(acted))
    if not any("instruction" in x["answer"] for x in ok):
        return
    for t in BARS:
        held = [x for x in ok if _held(x["answer"], t)]
        print(f"  bar {t:.2f}: held {len(held)} " + str(Counter(x["item"]["gold_command"] for x in held)))
    for x in sorted(ok, key=lambda x: -_score(x["answer"]))[:6]:
        a = x["answer"]
        print(f"    {_score(a):.2f} {a['command']:<17} gold {x['item']['gold_command']:<17} "
              f"{x['item']['utterance']}")


def score(paths: list[str]) -> None:
    for p in paths:
        data = json.loads(Path(p).read_text())
        print(f"== {p} ({data['arm']})")
        (score_fixture if data["arm"].startswith("fixture") else score_command)(data["rows"])


async def main(argv: list[str]) -> None:
    mode = argv[0]
    if mode == "score":
        return score(argv[1:])
    if mode == "fixture":
        items, out, arm, ins = json.loads(Path(argv[1]).read_text()), argv[2], "fixture:on", True
    else:
        ins = not (len(argv) > 2 and argv[2] == "off")
        items, out, arm = json.loads((FIX / "command_fixture.json").read_text()), argv[1], f"command:{'on' if ins else 'off'}"
    rows = await run(items, ins)
    Path(out).write_text(json.dumps({"arm": arm, "rows": rows}, indent=1))
    score([out])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
