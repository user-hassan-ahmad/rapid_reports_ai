"""Scratchpad v2 labs (spec 2026-10-11 §10): the Jev command classifier and the chip "already stated?"
question on blind fixtures (tests/fixtures/hybrid_stack/{command,chip}_fixture.json).

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.scratchpad_v2_labs [command|chip ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from rapid_reports_ai.hybrid_stack.jev_stack import ask_checks, ask_command, ask_stated  # noqa: E402

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hybrid_stack"


async def _gather(fn, items, n=6):
    sem = asyncio.Semaphore(n)

    async def one(it):
        async with sem:
            for attempt in range(3):
                try:
                    return await fn(it)
                except Exception as e:  # retry transport hiccups, then record
                    err = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(1 + attempt)
            return {"error": err}
    return await asyncio.gather(*(one(it) for it in items))


async def command_lab() -> None:
    items = json.loads((FIX / "command_fixture.json").read_text())
    res = await _gather(lambda it: ask_command(it["scratchpad"], it["utterance"], it["regions"], it["chips"]), items)
    rows = [(it, r) for it, r in zip(items, res) if "error" not in r]
    print(f"command: {len(rows)}/{len(items)} answered")
    print("  confusion (gold -> got):", dict(Counter((it["gold_command"], r["command"]) for it, r in rows)))
    for t in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        acted = [(it, r) for it, r in rows if r["command"] != "dictate" and r["confidence"] >= t]
        wrong = [(it, r) for it, r in acted if r["command"] != it["gold_command"]]
        gold_dict = [it for it, _ in rows if it["gold_command"] == "dictate"]
        dict_ok = sum(1 for it, r in rows if it["gold_command"] == "dictate"
                      and not (r["command"] != "dictate" and r["confidence"] >= t))
        cmd_gold = [it for it, _ in rows if it["gold_command"] != "dictate"]
        cmd_ok = sum(1 for it, r in acted if r["command"] == it["gold_command"])
        print(f"  t={t:.1f}: acted {len(acted)}, wrong command {len(wrong)}, dictate kept {dict_ok}/{len(gold_dict)}, "
              f"commands caught {cmd_ok}/{len(cmd_gold)}")
    reg = [(it, r) for it, r in rows if it["gold_command"] == "send_to_region" or it.get("gold_region")]
    print(f"  target region right: {sum(r['region'] == it['gold_region'] for it, r in reg)}/{len(reg)}")
    chip = [(it, r) for it, r in rows if it["gold_command"] == "accept_suggestion"]
    print(f"  target chip right: {sum(r['chip'] == it['gold_chip'] for it, r in chip)}/{len(chip)}")
    for it, r in rows:
        bad = (r["command"] != it["gold_command"]
               or (it["gold_command"] == "send_to_region" and r["region"] != it["gold_region"])
               or (it["gold_command"] == "accept_suggestion" and r["chip"] != it["gold_chip"]))
        if bad:
            print(f"  ✗ {it['id']} gold={it['gold_command']}/{it.get('gold_region') or it.get('gold_chip')} "
                  f"got={r['command']}@{r['confidence']:.2f}/{r['region'] or r['chip']}: {it['utterance']!r}")


async def chip_lab() -> None:
    items = json.loads((FIX / "chip_fixture.json").read_text())
    res = await _gather(lambda it: ask_stated(it["dictation"], [it["chip"]]), items)
    rows = [(it, r[0]) for it, r in zip(items, res) if isinstance(r, list)]
    print(f"chip: {len(rows)}/{len(items)} answered")
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        fp = [(it, p) for it, p in rows if p >= t and not it["gold_stated"]]
        tp = sum(1 for it, p in rows if p >= t and it["gold_stated"])
        pos = sum(1 for it, _ in rows if it["gold_stated"])
        print(f"  t={t:.1f}: stated recall {tp}/{pos}, false stated {len(fp)} "
              f"({dict(Counter(it['kind'] for it, _ in fp))})")
    for it, p in sorted(rows, key=lambda x: x[1]):
        print(f"  {p:.2f} {it['kind']:<19} gold={it['gold_stated']!s:<5} {it['chip']!r}")


async def contra_lab() -> None:
    """Both questions in one call, as chips.suggest asks them: stated bands and the contradiction guard."""
    items = json.loads((FIX / "chip_fixture.json").read_text())
    res = await _gather(lambda it: ask_checks(it["dictation"], [it["chip"]]), items)
    rows = [(it, r[0]) for it, r in zip(items, res) if isinstance(r, list)]
    print(f"checks: {len(rows)}/{len(items)} answered")
    for t in (0.3, 0.5, 0.7, 0.8):
        hit = [it["kind"] for it, (_, c) in rows if c >= t]
        print(f"  contra t={t:.1f}: flagged {dict(Counter(hit))} (contradicted items: "
              f"{sum(it['kind'] == 'contradicted' for it, _ in rows)})")
    for it, (st, c) in sorted(rows, key=lambda x: -x[1][1]):
        print(f"  stated {st:.2f} contra {c:.2f} {it['kind']:<19} {it['chip']!r}")


# Row checks (checklist spec §10.2): two wordings each for "removed" and "multiple findings", asked in one call
# with stated and contradicted, as production will ask them.
ROW_WORDINGS = {
    "removed_a": ("The STATEMENT says the same thing as one of the REMOVED statements: the same check on the same "
                  "structure, in any wording. STATEMENT: {s}"),
    "removed_b": "One of the REMOVED statements already makes this claim, in other words: {s}",
    "multi_a": ("This statement states the absence of more than one distinct finding (two different abnormalities, "
                "or the same abnormality in two different structures), so it should be split: {s}"),
    "multi_b": ("This statement can be split into two statements that each make a separate claim a radiologist could "
                "accept or reject on its own: {s}"),
}


async def _rows_one(sentence: str, removed: list[str]) -> dict:
    from rapid_reports_ai.hybrid_stack.jev_stack import contra_question, stated_question
    from rapid_reports_ai.jev_client import JEV_MODEL, jev_post
    import os
    qs = {"stated": stated_question(sentence), "contra": contra_question(sentence)}
    qs.update({k: {"type": "noul", "instructions": w.format(s=sentence)} for k, w in ROW_WORDINGS.items()})
    state = ("DICTATION:\nThe study was reviewed.\n\nREMOVED BY THE RADIOLOGIST:\n"
             + ("\n".join(f"- {r}" for r in removed) or "(none)"))
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), 6.0, None)
    r.raise_for_status()
    a = r.json().get("answers") or {}
    return {k: float((a.get(k) or {}).get("noul") or 0.0) for k in qs}


async def rows_lab() -> None:
    fx = json.loads((FIX / "jev_rows_fixture.json").read_text())
    rem = await _gather(lambda it: _rows_one(it["sentence"], it["removed"]), fx["removed"])
    mul = await _gather(lambda it: _rows_one(it["sentence"], []), fx["multi"])
    for name, items, res, keys in (("removed", fx["removed"], rem, ("removed_a", "removed_b")),
                                   ("multi", fx["multi"], mul, ("multi_a", "multi_b"))):
        rows = [(it, r) for it, r in zip(items, res) if "error" not in r]
        print(f"{name}: {len(rows)}/{len(items)} answered")
        for k in keys:
            for t in (0.3, 0.5, 0.6, 0.7, 0.8):
                tp = sum(1 for it, r in rows if it["gold"] and r[k] >= t)
                fp = sum(1 for it, r in rows if not it["gold"] and r[k] >= t)
                print(f"  {k} t={t:.1f}: hit {tp}/{sum(it['gold'] for it, _ in rows)}  false {fp}")
        for it, r in sorted(rows, key=lambda x: (not x[0]["gold"], -x[1][keys[0]])):
            print(f"   gold={it['gold']!s:<5} " + " ".join(f"{k}={r[k]:.2f}" for k in keys) +
                  f"  {it['sentence']!r}" + (f" vs {it['removed']}" if "removed" in it else ""))


async def main(argv: list[str]) -> None:
    for name in argv or ["command", "chip"]:
        await {"command": command_lab, "chip": chip_lab, "contra": contra_lab, "rows": rows_lab}[name]()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
