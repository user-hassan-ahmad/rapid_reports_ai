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


async def main(argv: list[str]) -> None:
    for name in argv or ["command", "chip"]:
        await {"command": command_lab, "chip": chip_lab, "contra": contra_lab}[name]()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
