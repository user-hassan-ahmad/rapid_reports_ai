# backend/src/rapid_reports_ai/scripts/review_labs/gate_b.py
"""Gate B: Accuracy (spec §11). B1 = alignment + code checks (+ inconsistent arms); B2 = Jev wording lab for
"is this positive finding stated".

    python -m rapid_reports_ai.scripts.review_labs.gate_b cases
    python -m rapid_reports_ai.scripts.review_labs.gate_b gold-page
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-build
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-run --runs 2 [--only id,id] [--arms W1n,W1c,...]
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-escalate --results <jsonl> --lo X --hi Y
    python -m rapid_reports_ai.scripts.review_labs.gate_b b2-score --results <jsonl> --escalated <jsonl> --lo X --hi Y
    python -m rapid_reports_ai.scripts.review_labs.gate_b inconsistent-run
    python -m rapid_reports_ai.scripts.review_labs.gate_b align-page        # [after Plan 2 Task 2]
    python -m rapid_reports_ai.scripts.review_labs.gate_b checks-score      # [after Plan 2 Task 3]"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

from pydantic import BaseModel

from . import clinical_pass, common, judgement, label_page, metrics

GOLD_KINDS = ["invented_finding", "invented_measurement", "invented_prior", "certainty_upgrade", "misattributed",
              "inconsistent_modality", "inconsistent_size_word", "other"]


def load_cases() -> List[dict]:
    cases = common.prod_cases()
    out = []
    for r in common.read_json(common.pipeline_scratch() / "audit_compare" / "compare.json"):
        c = dict(cases[r["id8"]])
        c.update(id8=r["id8"], audit_items=r.get("audit_items") or [], both_missed=r.get("both_missed"))
        out.append(c)
    return out


def cmd_cases(_args) -> None:
    cs = load_cases()
    print(common.write_json(common.lab_out("gate_b") / "cases.json", cs), len(cs))


GOLD_FIELDS = [{"key": "verdict", "label": "Unsupported by dictation/history?", "type": "choice",
                "options": ["unsupported", "supported", "unsure"], "required": True},
               {"key": "kind", "label": "Kind", "type": "choice", "options": GOLD_KINDS},
               {"key": "note", "type": "text", "label": "Note"}]


def gold_candidates(out) -> List[dict]:
    """Reader-proposed spans, de-duplicated by (id8, span), with stable ids g0, g1, … shared by every subcommand."""
    seen, res = set(), []
    for f in sorted(out.glob("gold_candidates_*.json")):
        for x in common.read_json(f):
            key = (x["id8"], x["span"])
            if key not in seen:
                seen.add(key)
                res.append({**x, "gid": f"g{len(res)}"})
    return res


def confirmed_gold(out) -> List[dict]:
    """Candidates Hassan marked unsupported; his kind overrides the reader's."""
    verdicts = common.read_json(out / "gold.json")
    return [{**x, "kind": verdicts[x["gid"]].get("kind") or x.get("kind")} for x in gold_candidates(out)
            if verdicts.get(x["gid"], {}).get("verdict") == "unsupported"]


def cmd_gold_page(_args) -> None:
    out = common.lab_out("gate_b")
    cases = {c["id8"]: c for c in common.read_json(out / "cases.json")}
    cards = []
    for x in gold_candidates(out):
        c = cases[x["id8"]]
        cards.append({"id": x["gid"], "title": f"{x['id8']} · proposed {x.get('kind')}",
                      "meta": c["scan"], "blocks": [
                          {"label": "Report span", "text": x["span"]},
                          {"label": "Reader's reason", "text": x.get("reason", "")},
                          {"label": "Full dictation", "text": c["dictation"], "collapsed": True},
                          {"label": "Clinical history", "text": c["history"] or "(none)", "collapsed": True},
                          {"label": "Full report", "text": c["report"], "highlight": [x["span"]], "collapsed": True}],
                      "hidden": []})
    print(label_page.write_page(out / "gold.html", "Gate B · unsupported spans", "gateB-gold-v1", cards, GOLD_FIELDS),
          len(cards))


async def _clinical(cases: List[dict]) -> List[dict]:
    sem = asyncio.Semaphore(8)

    async def one(c):
        async with sem:
            out, usage, err = await clinical_pass.run(c)
        return {"id8": c["id8"], "error": err, "usage": usage, **(out.model_dump() if out else {})}
    return await asyncio.gather(*(one(c) for c in cases))


def cmd_inconsistent_run(args) -> None:
    common.load_env()
    cases = common.read_json(common.lab_out("gate_b") / "cases.json")
    if args.only:
        cases = [c for c in cases if c["id8"] in set(args.only.split(","))]
    rows = asyncio.run(_clinical(cases))
    print(common.write_json(common.out_file("gate_b", "clinical_pass"), rows))


_W = {
    "W1": 'The dictated findings report this finding, including as a possibility, in any wording. Report statement: "{c}"',
    "W2": ('Read only this one report statement: "{c}". Everything it asserts (each finding, measurement, comparison '
           'and its certainty) is stated in the dictated findings or clinical history, in any wording, including as a possibility.'),
    "W3": ('Read only this one report statement: "{c}". Find what the dictated findings and clinical history say about '
           'the same structure, then decide whether they state what this statement asserts.'),
}
_CHOICES = {
    "stated": "Every finding, measurement, comparison and certainty level in the statement is in the dictation or history, "
              "in any wording, including as a possibility.",
    "not_stated": "The statement asserts a finding, measurement, comparison or certainty that the dictation and history do not state.",
    "cant_tell": "The statement cannot be checked against the dictation and history from the text alone.",
}
B2_ARMS = ["W1n", "W1c", "W2n", "W2c", "W3c"]


def b2_question(arm: str, clause: str) -> dict:
    w, t = arm[:2], arm[2]
    if t == "n":
        return {"type": "noul", "instructions": _W[w].format(c=clause),
                "criteria": {"true": "stated", "false": "not stated"}}
    return {"type": "choice", "instructions": _W[w].format(c=clause), "criteria": dict(_CHOICES)}


def p_stated(arm: str, ans: dict) -> float:
    if arm.endswith("n"):
        return float(ans["noul"])
    return float((ans.get("probabilities") or {}).get("stated", 0.0))


def is_cant_tell(arm: str, ans: dict) -> bool:
    return arm.endswith("c") and ans.get("choice") == "cant_tell"


def _state(c: dict) -> str:
    return (f"SCAN TYPE: {c['scan']}\nCLINICAL HISTORY: {c.get('history') or '(none)'}\n"
            f"DICTATED FINDINGS:\n{c['dictation']}")


FABRICATE_SYS = ("Write ONE sentence in the style of this radiology report that states a {kind} which the dictation does "
                 "not contain. kind meanings: invented_finding = a plausible abnormal finding in an organ the report "
                 "covers; invented_measurement = a measurement for a structure the report names without one; "
                 "invented_prior = a comparison with a prior study; certainty_upgrade = a definite restatement of a "
                 "finding the dictation hedges. Return only the sentence.")


class OneSentence(BaseModel):
    sentence: str


async def _fabricate(case: dict, kind: str) -> Optional[str]:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    try:
        out, _ = await calls.qwen(OneSentence, FABRICATE_SYS.format(kind=kind),
                                  f"DICTATION:\n{case['dictation']}\n\nREPORT:\n{case['report']}", False)
        return out.sentence.strip()
    except Exception:   # noqa: BLE001
        return None


def cmd_b2_build(_args) -> None:
    common.load_env()
    out = common.lab_out("gate_b")
    cases = common.read_json(out / "cases.json")
    by8 = {c["id8"]: c for c in cases}
    items = [{"id": f"p-{x['gid']}", "id8": x["id8"], "category": "production", "label": "not_stated",
              "clause": x["span"], "case": by8[x["id8"]]} for x in confirmed_gold(out)][:10]
    kinds = ["invented_finding", "invented_measurement", "invented_prior", "certainty_upgrade"]
    need = {k: 10 for k in kinds}
    need[kinds[0]] += 10 - len(items)                   # top up when production positives < 10

    async def build():
        jobs = []
        for k in kinds:
            for i in range(need[k]):
                c = cases[(i * 7 + kinds.index(k) * 3) % len(cases)]
                jobs.append((k, c, _fabricate(c, k)))
        res = await asyncio.gather(*(j[2] for j in jobs))
        for (k, c, _), s in zip(jobs, res):
            if s:
                items.append({"id": f"f-{k}-{len(items)}", "id8": c["id8"], "category": k, "label": "not_stated",
                              "clause": s, "case": {**c, "report": c["report"].replace("\nIMPRESSION:", f" {s}\nIMPRESSION:", 1)}})
    asyncio.run(build())
    print(common.write_json(out / "b2_items_unsupported.json", items), len(items))


async def _b2(items: List[dict], arms: List[str], runs: int, out_path) -> None:
    from rapid_reports_ai.scripts.jev_tool_lab import calls
    sem = asyncio.Semaphore(4)
    with open(out_path, "a") as fh:
        for run in range(1, runs + 1):
            async def one(it):
                qs = {a: b2_question(a, it["clause"]) for a in arms}
                async with sem:
                    try:
                        ans, _, secs = await calls.jev({_state(it["case"]): qs})
                        err = None
                    except Exception as e:   # noqa: BLE001
                        ans, secs, err = {}, None, f"{type(e).__name__}: {e}"
                return [{"item_id": it["id"], "run": run, "arm": a, "label": it["label"], "category": it["category"],
                         "answer": ans.get(a), "jev_s": secs, "error": err} for a in arms]
            for rows in await asyncio.gather(*(one(it) for it in items)):
                for r in rows:
                    fh.write(json.dumps(r) + "\n")


def cmd_b2_run(args) -> None:
    common.load_env()
    items = common.read_json(common.lab_out("gate_b") / "b2_items.json")
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    arms = args.arms.split(",") if args.arms else B2_ARMS
    out = common.out_file("gate_b", "b2_jev", "jsonl")
    asyncio.run(_b2(items, arms, args.runs, out))
    print(out)


def cmd_b2_escalate(args) -> None:
    common.load_env()
    items = {i["id"]: i for i in common.read_json(common.lab_out("gate_b") / "b2_items.json")}
    rows = [r for r in common.read_jsonl(args.results) if r["run"] == 1 and r["answer"]]
    unsure = sorted({r["item_id"] for r in rows if is_cant_tell(r["arm"], r["answer"]) or
                     args.lo <= p_stated(r["arm"], r["answer"]) < args.hi})
    sem = asyncio.Semaphore(8)

    async def go():
        async def one(iid):
            it = items[iid]
            cand = {"lane": "accuracy", "kind": "unsupported", "detector": "jev.b2", "anchor": it["clause"], "line": None,
                    "evidence": {"jev_unsure": {"question": "positive_stated", "band": "unsure"}}}
            r = await judgement.judge_and_verify({**it["case"]}, [cand], sem)
            return {"item_id": iid, **r}
        return await asyncio.gather(*(one(i) for i in unsure))
    out = common.out_file("gate_b", "b2_escalated", "jsonl")
    with open(out, "w") as fh:
        for r in asyncio.run(go()):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(out, len(unsure))


def cmd_b2_score(args) -> None:
    rows = [r for r in common.read_jsonl(args.results) if r["answer"]]
    esc = {r["item_id"]: r for r in common.read_jsonl(args.escalated)} if args.escalated else {}
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        r1 = [r for r in rows if r["arm"] == arm and r["run"] == 1]
        probs = [p_stated(arm, r["answer"]) for r in r1]
        labels = [r["label"] == "stated" for r in r1]

        def flagged(r):
            p = p_stated(arm, r["answer"])
            if is_cant_tell(arm, r["answer"]) or args.lo <= p < args.hi:
                e = esc.get(r["item_id"])
                return bool(e and e.get("cls") in ("action", "minor"))
            return p < args.lo
        by_cat = {}
        for r in r1:
            by_cat.setdefault(r["category"], []).append((r["label"] == "not_stated", flagged(r)))
        r2 = {r["item_id"]: p_stated(arm, r["answer"]) for r in rows if r["arm"] == arm and r["run"] == 2}
        out[arm] = {
            "auc": metrics.auc([1 - p for p in probs], [not l for l in labels]),
            "brier": metrics.brier(probs, labels), "ece": metrics.ece(probs, labels),
            "bands": metrics.errors_by_band(probs, labels, args.lo, args.hi),
            "after_escalation": metrics.binary([(r["label"] == "not_stated", flagged(r)) for r in r1]),
            "by_category": {k: metrics.binary(v) for k, v in by_cat.items()},
            "unsure_items": sum(1 for r in r1 if is_cant_tell(arm, r["answer"]) or args.lo <= p_stated(arm, r["answer"]) < args.hi),
            "max_drift": max((abs(r2[r["item_id"]] - p_stated(arm, r["answer"])) for r in r1 if r["item_id"] in r2), default=None),
        }
    print(json.dumps(out, indent=1))
    print(common.write_json(common.out_file("gate_b", "b2_score"), out))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases").set_defaults(fn=cmd_cases)
    sub.add_parser("gold-page").set_defaults(fn=cmd_gold_page)
    ir = sub.add_parser("inconsistent-run"); ir.add_argument("--only", default=""); ir.set_defaults(fn=cmd_inconsistent_run)
    b = sub.add_parser("b2-build"); b.set_defaults(fn=cmd_b2_build)
    r = sub.add_parser("b2-run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.add_argument("--arms", default=""); r.set_defaults(fn=cmd_b2_run)
    e = sub.add_parser("b2-escalate"); e.add_argument("--results", required=True)
    e.add_argument("--lo", type=float, required=True); e.add_argument("--hi", type=float, required=True); e.set_defaults(fn=cmd_b2_escalate)
    s = sub.add_parser("b2-score"); s.add_argument("--results", required=True); s.add_argument("--escalated", default="")
    s.add_argument("--lo", type=float, default=0.3); s.add_argument("--hi", type=float, default=0.7); s.set_defaults(fn=cmd_b2_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
