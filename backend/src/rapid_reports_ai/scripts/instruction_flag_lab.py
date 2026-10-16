"""Instruction-flag lab (design docs/superpowers/specs/2026-10-15-instruction-flag-design.md): the stack command
question with the `instruction` option, on a synthetic fixture (instructions vs report sentences that look like
instructions) and, for regressions, on the 96-item command fixture.

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.instruction_flag_lab fixture <fixture.json> <out.json>
    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.instruction_flag_lab command <out.json> [off]

Each item is asked as the bundle route asks it: the stack command question (with the named-target question when the
option is on) and the bundle triage, in parallel; a final code decides (bare "scratch that", filler only) is never
asked. "Held" is the route's decision: decide_command, then settle_instruction with the bundle route and triage action
(Q10/Q11/Q15, Hassan 2026-10-16).

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

from rapid_reports_ai.fast_append import code_route, route_bundle  # noqa: E402
from rapid_reports_ai.hybrid_stack.jev_stack import (  # noqa: E402
    ask_command, decide_command, held_score, polish_handles, settle_instruction)
from rapid_reports_ai.utterance_bundle import BundleState, get_jev_bundle  # noqa: E402

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


async def _ask(it: dict, instruction: bool) -> dict:
    if code_route(it["utterance"], it["scratchpad"]) is not None:   # decided by code: the stack question is never asked
        r = route_bundle(RuntimeError("not asked"), it["utterance"], preceding=it["scratchpad"])
        return {"command": None, "confidence": 0.0, "code_route": r.route, "route": r.route, "triage": None}
    bundle = get_jev_bundle()
    parsed, dec = await asyncio.gather(
        ask_command(it["scratchpad"], it["utterance"], it["regions"], it["chips"], instruction=instruction),
        bundle.classify(BundleState(scan_type=it.get("scan_type", ""), committed="", active=it["scratchpad"],
                                    open_line="", latest_utterance=it["utterance"]), word_sense=False))
    r = route_bundle(dec, it["utterance"], preceding=it["scratchpad"])
    return {**parsed, "route": r.route, "triage": dec.triage.action,
            "polish_handled": polish_handles(dec.triage.action, it["utterance"])}


async def run(items: list[dict], instruction: bool) -> list[dict]:
    res = await _gather(lambda it: _ask(it, instruction), items)
    return [{"item": it, "answer": r} for it, r in zip(items, res)]


def _supported(r: dict) -> str | None:
    """A supported command the scratchpad carries out (accept, a delete naming a region), whatever the bar."""
    d = decide_command(r, instruction_min=9.0) if "instruction" in r else decide_command(r)
    if d["action"] == "delete":
        return "delete:region" if d["region"] else None   # a region-less stack delete is not acted on by the scratchpad
    return None if d["action"] == "dictate" else d["action"]


def _held(r: dict, t: float) -> bool:
    """The route's decision: held by decide_command and still held after settle_instruction."""
    if "instruction" not in r or r.get("code_route"):
        return False
    d = decide_command(r, instruction_min=t)
    if d["action"] != "instruction":
        return False
    return (settle_instruction(dict(d), r.get("route") or "polish", bool(r.get("polish_handled")))
            or {})["action"] == "instruction"


def _why_not(r: dict, t: float) -> str:
    """Why an instruction is not held at bar t (Q10 named gate, Q11/Q15 polish-handled, route, bar)."""
    if r.get("code_route"):
        return f"code:{r['code_route']}"
    if "instruction" not in r:
        return "not asked"
    d = decide_command(r, instruction_min=t)
    if d["action"] == "instruction":
        if r.get("polish_handled"):
            return f"polish-handled:{r['triage']}"
        return f"route:{r.get('route')}"
    if d["action"] != "dictate" and (d["action"] != "delete" or d["region"]):
        return f"supported:{d['action']}"
    unnamed = float(r.get("instruction") or 0) + float(r.get("p_delete") or 0)
    if unnamed >= t and held_score(r) < t:
        return "Q10:names nothing"
    return "below bar"


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
    from collections import defaultdict
    t = 0.85
    why = defaultdict(list)
    for x in ins:
        if not _held(x["answer"], t):
            why[_why_not(x["answer"], t)].append(f"{x['item']['id']}[{x['item']['category']}]")
    print(f"  instructions not held at {t}, by reason:")
    for k, v in sorted(why.items()):
        print(f"    {k:<32} {len(v):>2}  {v}")
    print("  triage actions, instructions:", dict(Counter(x["answer"].get("triage") for x in ins)))
    print("  routes, instructions:", dict(Counter(x["answer"].get("route") for x in ins)))
    print("  report sentences by held score (P instruction + P delete when named), highest first:")
    for x in sorted(con, key=lambda x: -_score(x["answer"]))[:8]:
        a = x["answer"]
        print(f"    {_score(a):.2f} {str(a['command']):<17} {x['item']['id']} {x['item']['utterance']}")
    print("  instructions below 0.8 (or taken as a command):")
    for x in sorted(ins, key=lambda x: _score(x["answer"])):
        a = x["answer"]
        if _score(a) < 0.8 or _supported(a):
            print(f"    {_score(a):.2f} {str(a['command']):<17} conf {a['confidence']:.2f} "
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
        print(f"  bar {t:.2f}: held {len(held)} " + str(Counter(x["item"]["gold_command"] for x in held))
              + (f"  {[x['item']['utterance'] for x in held]}" if t == 0.85 else ""))
    print("  deletes at 0.85:")
    for x in ok:
        if x["item"]["gold_command"] == "delete":
            a = x["answer"]
            print(f"    held={_held(a, 0.85)!s:<5} {_why_not(a, 0.85) if not _held(a, 0.85) else '':<26} "
                  f"named {float(a.get('p_named') or 0):.2f} {x['item']['utterance']}")
    for x in sorted(ok, key=lambda x: -_score(x["answer"]))[:6]:
        a = x["answer"]
        print(f"    {_score(a):.2f} {str(a['command']):<17} gold {x['item']['gold_command']:<17} "
              f"{x['item']['utterance']}")


def score(paths: list[str]) -> None:
    for p in paths:
        data = json.loads(Path(p).read_text())
        for x in data["rows"]:   # rows saved before polish_handles: derived from the saved triage action
            a = x["answer"]
            if "triage" in a and "polish_handled" not in a:
                a["polish_handled"] = polish_handles(a["triage"], x["item"]["utterance"])
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
