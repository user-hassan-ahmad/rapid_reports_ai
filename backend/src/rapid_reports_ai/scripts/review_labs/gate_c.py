# backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py
"""Gate C: Additions (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_c pull              # enhancement_json for the 41 + criteria index
    python -m rapid_reports_ai.scripts.review_labs.gate_c gate --runs 2     # "already in report" Jev (noul + Choice)
    python -m rapid_reports_ai.scripts.review_labs.gate_c adjudicate [--only id,id]   # arms: nocrit, crit
    python -m rapid_reports_ai.scripts.review_labs.gate_c s1 --runs 2 [--only s1-01,s1-02]
    python -m rapid_reports_ai.scripts.review_labs.gate_c page --adjudicated <jsonl> --clinical <json>
    python -m rapid_reports_ai.scripts.review_labs.gate_c score --labels <json> --adjudicated <jsonl> --s1 <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

from rapid_reports_ai.report_reconcile import Q_CONVEYS

from . import additions_map as AM
from . import common, judgement

IN_REPORT_CHOICES = {
    "stated": "The report itself already states this point, in any wording (not merely implied or inferable).",
    "not_stated": "The report does not state this point.",
    "cant_tell": "Whether the report states this point cannot be judged from the text alone.",
}


def candidate_text(c: dict) -> str:
    ev = c["evidence"]
    if c["kind"] == "grade":
        return f"a {ev.get('system')} category for the {c.get('anchor')}"
    if c["kind"] == "threshold":
        return f"the {ev.get('parameter')} threshold {ev.get('threshold')} for the {c.get('anchor')}"
    if c["kind"] in ("follow_up", "option") and ev.get("modality"):
        return f"{ev.get('modality')} follow-up {ev.get('timing') or ''} for the {c.get('anchor')}".strip()
    return f"{ev.get('text')} (for the {c.get('anchor')})"


def cmd_pull(_args) -> None:
    out = common.lab_out("gate_c")
    cases = common.read_json(common.lab_out("gate_b") / "cases.json")
    ids = ",".join(f"'{c['id']}'" for c in cases)
    rows = common.metabase(f"select id::text as id, enhancement_json->'guidelines' as guidelines from reports where id in ({ids})")
    g = {r["id"]: (json.loads(r["guidelines"]) if isinstance(r["guidelines"], str) else r["guidelines"]) or [] for r in rows}
    for c in cases:
        c["guidelines"] = g.get(c["id"], [])
    common.write_json(out / "cases.json", cases)
    allrows = common.metabase("select enhancement_json->'guidelines' as guidelines from reports "
                              "where enhancement_json is not null and created_at >= now() - interval '120 days'")
    cards = [card for r in allrows for card in ((json.loads(r["guidelines"]) if isinstance(r["guidelines"], str)
                                                 else r["guidelines"]) or [])]
    idx = AM.criteria_index(cards)
    common.write_json(out / "criteria_index.json", idx)
    print(f"{sum(1 for c in cases if c['guidelines'])}/41 with synthesis; criteria systems: {sorted(idx)}")


async def _gate(cases: List[dict], runs: int, out_path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    sem = asyncio.Semaphore(4)
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(c):
                cands = [x for card in c["guidelines"] for x in AM.map_card(card)]
                qs = {}
                for k, x in enumerate(cands):
                    t = candidate_text(x)
                    qs[f"n{k}"] = {"type": "noul", "instructions": Q_CONVEYS + t}
                    qs[f"c{k}"] = {"type": "choice", "criteria": dict(IN_REPORT_CHOICES),
                                   "instructions": f'Read only this one guideline point: "{t}". Does the report state it?'}
                if not qs:
                    return []
                async with sem:
                    ans, _, _ = await calls.jev({f"REPORT:\n{c['report']}": qs})
                return [{"id8": c["id8"], "run": run, "k": k, "candidate": x, "text": candidate_text(x),
                         "noul": (ans.get(f"n{k}") or {}).get("noul"), "choice": ans.get(f"c{k}")} for k, x in enumerate(cands)]
            for rows in await asyncio.gather(*(one(c) for c in cases)):
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def cmd_gate(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_c") / "cases.json")
    if args.only:
        cases = [c for c in cases if c["id8"] in set(args.only.split(","))]
    out = common.out_file("gate_c", "in_report", "jsonl")
    asyncio.run(_gate(cases, args.runs, out))
    print(out)


async def _adjudicate(cases: List[dict], gate_rows: List[dict], out_path) -> None:
    sem = asyncio.Semaphore(8)
    idx = common.read_json(common.lab_out("gate_c") / "criteria_index.json")
    by8 = {c["id8"]: c for c in cases}
    keep = [r for r in gate_rows if r["run"] == 1 and (r["choice"] or {}).get("choice") != "stated"]
    with open(out_path, "a") as fh:
        async def one(r, arm):
            cand = json.loads(json.dumps(r["candidate"]))
            if arm == "crit" and cand["kind"] == "grade":
                crit = idx.get(AM.system_key(cand["evidence"].get("system", "")))
                if not crit:
                    return None
                cand["evidence"]["criteria"] = " | ".join(crit)
            elif arm == "crit":
                return None                                 # the criteria arm only changes grade items
            res = await judgement.judge_and_verify(by8[r["id8"]], [cand], sem)
            return {"id8": r["id8"], "k": r["k"], "arm": arm, "kind_in": cand["kind"], "text": r["text"],
                    "citation": cand.get("citation"), **res}
        rows = await asyncio.gather(*(one(r, a) for r in keep for a in ("nocrit", "crit")))
        for row in rows:
            if row:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_adjudicate(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_c") / "cases.json")
    gate_rows = common.read_jsonl(args.gate)
    if args.only:
        gate_rows = [r for r in gate_rows if f"{r['id8']}-{r['k']}" in set(args.only.split(","))]
    out = common.out_file("gate_c", "adjudicated", "jsonl")
    asyncio.run(_adjudicate(cases, gate_rows, out))
    print(out)


def s1_case(item: dict) -> dict:
    return {"scan": item["scan_type"], "history": "", "dictation": item["dictation"],
            "report": "FINDINGS:\n" + item["dictation"].replace("\n", " ") + "\nIMPRESSION:\nSee findings."}


async def _s1(items: List[dict], runs: int, out_path) -> None:
    sem = asyncio.Semaphore(4)
    idx = common.read_json(common.lab_out("gate_c") / "criteria_index.json")
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it, arm):
                ev = {"system": it["system"], "finding": it["finding"]}
                if arm == "crit":
                    crit = idx.get(AM.system_key(it["system"]))
                    if not crit:
                        return {"item_id": it["id"], "run": run, "arm": arm, "skipped": "no_criteria"}
                    ev["criteria"] = " | ".join(crit)
                cand = {"lane": "additions", "kind": "grade", "detector": "s1", "line": None,
                        "anchor": it["finding"], "evidence": ev}
                r = await judgement.judge_and_verify(s1_case(it), [cand], sem)
                return {"item_id": it["id"], "run": run, "arm": arm, "kind": r.get("kind"), "cls": r.get("cls"),
                        "label": r.get("label"), "error": r.get("error"), "usage": r.get("usage"),
                        "gradable": it["gradable"], "category": it["category"]}
            for row in await asyncio.gather(*(one(it, a) for it in items for a in ("nocrit", "crit"))):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_s1(args) -> None:
    common.load_env()
    items = common.read_json(common.BACKEND / "test_cases" / "jev_tool_lab" / "s1_phase3.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    out = common.out_file("gate_c", "s1", "jsonl")
    asyncio.run(_s1(items, args.runs, out))
    print(out)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull").set_defaults(fn=cmd_pull)
    g = sub.add_parser("gate"); g.add_argument("--runs", type=int, default=2); g.add_argument("--only", default="")
    g.set_defaults(fn=cmd_gate)
    a = sub.add_parser("adjudicate"); a.add_argument("--gate", required=True); a.add_argument("--only", default="")
    a.set_defaults(fn=cmd_adjudicate)
    s = sub.add_parser("s1"); s.add_argument("--runs", type=int, default=2); s.add_argument("--only", default="")
    s.set_defaults(fn=cmd_s1)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
