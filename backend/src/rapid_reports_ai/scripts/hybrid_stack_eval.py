"""Replay the hybrid stack lab sets through the production modules (real models).

Each case is the scratchpad text after each utterance (tests/fixtures/hybrid_stack/replay_*.json);
every step calls service.group_update with the previous units, as the client does; the closing
check runs at the end. Scores the lab's checks ('region' exact; 'group' against name + includes).

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_eval [dev|heldout|template ...]

Lab results to match (2026-10-10): dev 133/139 (lenient), held-out 97/108, template 104/122.
With tests/fixtures/hybrid_stack/abnormal_gold.json present, also scores the grouper's `abnormal`
flag per sentence (spec 2026-10-11 §3): recall, precision, and regions it would hide in the tray.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
import logging  # noqa: E402
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from rapid_reports_ai.hybrid_stack import service  # noqa: E402
from rapid_reports_ai.hybrid_stack.family import choose_family  # noqa: E402
from rapid_reports_ai.hybrid_stack.schemas import GENERIC_FAMILY, family_keys, family_regions  # noqa: E402
from rapid_reports_ai.hybrid_stack.template import template_regions  # noqa: E402
from rapid_reports_ai.template_sheet_grammar import parse_sheet  # noqa: E402

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hybrid_stack"


async def regions_for(case: dict):
    if case.get("template"):
        return template_regions(parse_sheet(Path(case["template"]).read_text(), mode="template").structure)
    choice, _ = await choose_family(case["scan_type"], case["clinical_history"])
    return family_regions(choice if choice in family_keys() else GENERIC_FAMILY)


def score(case: dict, units, regions) -> list[dict]:
    includes = {r.name: r.includes for r in regions}
    out = []
    for e in case["expect"]:
        u = next((u for u in units if e["phrase"].lower() in u.text.lower()), None)
        if u is None:
            out.append({**e, "result": "phrase not found"})
            continue
        grp = u.group or ""
        if u.parts:
            grp = next((p.group for p in u.parts if e["phrase"].lower() in p.text.lower()), grp)
        if "region" in e:
            ok = grp.lower() in {x.lower() for x in e["region"]}
        else:
            ok = any(s in (grp + " " + includes.get(grp, "")).lower() for s in e["group"])
        if ok and e.get("attach") and u.attach_to is None:
            out.append({**e, "result": "not attached", "got": grp})
        else:
            out.append({**e, "result": "ok" if ok else "wrong group", "got": grp})
    return out


async def run_case(case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        regions = await regions_for(case)
        units, served = [], []
        for text in case["steps"]:
            res = await service.group_update(case["scan_type"], text, regions, units)
            units = res.units
            if res.new_ids:
                served.append(res.model or f"failed: {res.error}")
        closed = await service.close_update(units, regions)
        return {"id": case["id"], "checks": score(case, closed.units, regions), "served": served,
                "units": closed.units}


def score_abnormal(name: str, results: list[dict], gold: list[dict]) -> None:
    """Gold is per sentence of the final text; unit ids are sentence positions (units.match_units)."""
    want = {(g["case"], g["i"]): g["abnormal"] for g in gold if g["set"] == name[0]}
    tp = fp = fn = tn = hidden = 0
    for r in results:
        for u in r["units"]:
            g = want.get((r["id"], u.id))
            if g is None:
                continue
            tp += g and u.abnormal
            fp += (not g) and u.abnormal
            fn += g and not u.abnormal
            tn += (not g) and not u.abnormal
            if g and not u.abnormal:
                rest = [x for x in r["units"] if x.group == u.group and x.abnormal]
                if not rest and u.group not in ("Technique", "General", "Conclusion"):
                    hidden += 1
                print(f"  ✗abn {r['id']}[{u.id}] missed ({u.group}{'; region hidden' if not rest else ''}): {u.text}")
            elif u.abnormal and not g:
                print(f"  ✗abn {r['id']}[{u.id}] over ({u.group}): {u.text}")
    rec = tp / (tp + fn) if tp + fn else 1.0
    prec = tp / (tp + fp) if tp + fp else 1.0
    print(f"  abnormal: recall {tp}/{tp + fn} = {rec:.3f}, precision {tp}/{tp + fp} = {prec:.3f}, "
          f"true negatives {tn}, regions hidden {hidden}")


async def main(argv: list[str]) -> None:
    sem = asyncio.Semaphore(int(__import__("os").environ.get("EVAL_CONCURRENCY", "3")))
    for name in argv or ["dev", "heldout", "template"]:
        cases = json.loads((FIX / f"replay_{name}.json").read_text())["cases"]
        results = await asyncio.gather(*(run_case(c, sem) for c in cases))
        checks = [x for r in results for x in r["checks"]]
        ok = sum(x["result"] == "ok" for x in checks)
        lost = sum(x["result"] == "phrase not found" for x in checks)
        print(f"{name}: {ok}/{len(checks)} (scorable {ok}/{len(checks) - lost})")
        served = Counter(s.split(":")[0] if s.startswith("failed") else s for r in results for s in r["served"])
        print(f"  grouper calls served by: {dict(served)}")
        gold_path = FIX / "abnormal_gold.json"
        if gold_path.exists():
            score_abnormal(name, results, json.loads(gold_path.read_text()))
        for r in results:
            for x in r["checks"]:
                if x["result"] not in ("ok", "phrase not found"):
                    print(f"  ✗ {r['id']} {x['phrase']!r} {x['result']} got={x.get('got')} "
                          f"want={x.get('region') or x.get('group')}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
