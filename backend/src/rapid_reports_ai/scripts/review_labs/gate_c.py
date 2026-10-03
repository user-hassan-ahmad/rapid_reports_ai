# backend/src/rapid_reports_ai/scripts/review_labs/gate_c.py
"""Gate C: Additions (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_c pull              # enhancement_json for the 41 + criteria index
    python -m rapid_reports_ai.scripts.review_labs.gate_c gate --runs 2     # "already in report" Jev (noul + Choice)
    python -m rapid_reports_ai.scripts.review_labs.gate_c adjudicate [--only id,id]   # arms: nocrit, crit
    python -m rapid_reports_ai.scripts.review_labs.gate_c s1 --runs 2 [--only s1-01,s1-02]
    python -m rapid_reports_ai.scripts.review_labs.gate_c page --adjudicated <jsonl> --clinical <json> --gate <in_report jsonl>
    python -m rapid_reports_ai.scripts.review_labs.gate_c score --labels <json> --adjudicated <jsonl> --s1 <jsonl> --gate <in_report jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import List, Optional

from rapid_reports_ai.report_reconcile import Q_CONVEYS

from . import additions_map as AM
from . import common, judgement, label_page, metrics

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
                crit = AM.criteria_lookup(idx, cand["evidence"].get("system", ""))
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
                    crit = AM.criteria_lookup(idx, it["system"])
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

_REC = re.compile(r"\b(recommend\w*|suggest\w*|advise\w*|consider|follow-?up)\b", re.I)
_MGMT = re.compile(r"\b(refer\w*|surgery|surgical|prescrib\w*|commence|start(?:ing)?|anticoagul\w*|biopsy should|treat\w*)\b", re.I)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def hard_violations(row: dict, report: str, dictation: str, history: str) -> List[str]:
    """Spec §11 Gate C hard bar, checked in code where possible; the hand read decides the rest."""
    v = []
    new, old = row.get("edit_replace") or "", row.get("edit_find") or ""
    if row.get("kind") in ("grade", "threshold") and set(_NUM.findall(new)) - set(_NUM.findall(old)) - set(_NUM.findall(f"{dictation}\n{history}")):
        v.append("ungrounded_number")
    if _MGMT.search(new):
        v.append("management")
    imp = report.split("IMPRESSION:", 1)[1] if "IMPRESSION:" in report else ""
    if row.get("edit_mode") == "insert" and _REC.search(new) and _REC.search(imp) and (row.get("edit_after") or "") in imp:
        v.append("second_recommendation")
    return v


C_FIELDS = [{"key": "verdict", "label": "Should show as", "type": "choice",
             "options": ["action", "minor", "info", "suppress"], "required": True},
            {"key": "correct", "label": "Correct and useful", "type": "choice", "options": ["yes", "no"]},
            {"key": "in_report", "label": "Already in report", "type": "choice", "options": ["yes", "no"]},
            {"key": "violation", "label": "Hard violation", "type": "choice",
             "options": ["none", "undictated grade/threshold", "management", "second recommendation"]},
            {"key": "note", "type": "text", "label": "Note"}]


def _gate_by_key(gate_rows: List[dict]) -> dict:
    return {f"{r['id8']}-{r['k']}": r for r in gate_rows if r.get("run") == 1}


def _gate_block(g: Optional[dict]) -> dict:
    if not g:
        return {"label": "Already in report (gate)", "text": "(no gate row)"}
    return {"label": "Already in report (gate)",
            "text": f"noul = {g.get('noul')}\nchoice = {json.dumps(g.get('choice'), ensure_ascii=False)}"}


def dropped_sample(gate_rows: List[dict], limit: int = 40) -> List[dict]:
    """Run-1 rows the gate judged `stated` (so dropped), up to `limit`, spread evenly across reports."""
    by: dict = {}
    for r in gate_rows:
        if r.get("run") == 1 and (r.get("choice") or {}).get("choice") == "stated":
            by.setdefault(r["id8"], []).append(r)
    out, i = [], 0
    queues = [by[k] for k in sorted(by)]
    while len(out) < limit and any(i < len(q) for q in queues):
        out += [q[i] for q in queues if i < len(q)][: limit - len(out)]
        i += 1
    return out


def cmd_page(args) -> None:
    out = common.lab_out("gate_c")
    cases = {c["id8"]: c for c in common.read_json(out / "cases.json")}
    rows = [r for r in common.read_jsonl(args.adjudicated) if r["arm"] == "nocrit"]
    clinical = {r["id8"]: r for r in common.read_json(args.clinical)}
    gate_rows = common.read_jsonl(args.gate)
    gate = _gate_by_key(gate_rows)
    cards = []
    for r in rows:
        c = cases[r["id8"]]
        fix = (f"{r.get('edit_mode')}: «{r.get('edit_find') or r.get('edit_after') or ''}» → «{r.get('edit_replace') or ''}»"
               if r.get("edit_mode") not in (None, "none") else "no edit")
        cards.append({"id": f"{r['id8']}-{r['k']}", "title": f"{r['id8']} · {r['kind_in']} → {r.get('cls')}/{r.get('kind')}",
                      "meta": f"{c['scan']} · {json.dumps(r.get('citation'))}",
                      "blocks": [{"label": "Guideline point", "text": r["text"]},
                                 _gate_block(gate.get(f"{r['id8']}-{r['k']}")),
                                 {"label": "Engine label / reason", "text": f"{r.get('label')}\n{r.get('reason') or ''}"},
                                 {"label": "Fix", "text": fix + "\ncode hard checks: " +
                                  (", ".join(hard_violations(r, c["report"], c["dictation"], c["history"])) or "none")},
                                 {"label": "Full report", "text": c["report"], "collapsed": True},
                                 {"label": "Full dictation", "text": c["dictation"], "collapsed": True}], "hidden": []})
    for g in dropped_sample(gate_rows):
        c = cases.get(g["id8"])
        if not c:
            continue
        cards.append({"id": f"{g['id8']}-{g['k']}-dropped", "title": f"{g['id8']} · dropped as already stated",
                      "meta": c["scan"],
                      "blocks": [{"label": "Guideline point", "text": g["text"]}, _gate_block(g),
                                 {"label": "Full report", "text": c["report"]},
                                 {"label": "Full dictation", "text": c["dictation"], "collapsed": True}], "hidden": []})
    for id8, r in clinical.items():
        c = cases.get(id8)
        if not c:
            continue
        for key in ("characterise", "safety"):
            for k, s in enumerate(r.get(key) or []):
                cards.append({"id": f"{id8}-cp-{key}-{k}", "title": f"{id8} · clinical pass {key}", "meta": c["scan"],
                              "blocks": [{"label": key, "text": s},
                                         {"label": "Audit items (for comparison)",
                                          "text": "\n".join(f"{a['criterion']} [{a.get('verdict')}]: {a.get('finding') or ''}"
                                                            for a in c.get("audit_items") or []) or "(none)", "collapsed": True},
                                         {"label": "Full report", "text": c["report"], "collapsed": True}], "hidden": []})
        cards.append({"id": f"{id8}-cp-urgency", "title": f"{id8} · urgency {r.get('urgency')}", "meta": c["scan"],
                      "blocks": [{"label": "Urgency reason", "text": r.get("urgency_reason") or "(routine)"},
                                 {"label": "Audit banners", "text": "\n".join(
                                     f"[{a.get('verdict')}] {a.get('banners') or a.get('finding') or ''}"
                                     for a in c.get("audit_items") or [] if a.get("category") == "banner") or "(none)"}],
                      "hidden": []})
    print(label_page.write_page(out / "cards.html", "Gate C · additions read", "gateC-read-v1", cards, C_FIELDS), len(cards))


def _ok(r: dict) -> bool:
    return not r.get("skipped") and not r.get("error")


def score(labels: dict, adj_rows: List[dict], s1_rows: List[dict], gate_rows: Optional[List[dict]] = None) -> dict:
    adj = [r for r in adj_rows if _ok(r)]
    s1 = [r for r in s1_rows if _ok(r)]
    res: dict = {}
    act = [r for r in adj if r["arm"] == "nocrit" and r.get("cls") == "action"]
    good = [r for r in act if (labels.get(f"{r['id8']}-{r['k']}") or {}).get("correct") == "yes"]
    res["n_action"] = len(act)
    res["action_correct_share"] = len(good) / len(act) if act else None
    res["hard_violations_hand"] = sorted(k for k, v in labels.items() if v.get("violation") not in (None, "none"))
    for arm in ("nocrit", "crit"):
        for run in (1, 2):
            rows = [r for r in s1 if r["arm"] == arm and r["run"] == run]
            g = [r for r in rows if r["gradable"]]
            ng = [r for r in rows if not r["gradable"]]
            res[f"s1_{arm}_run{run}"] = {
                "n": len(rows),
                "false_cant_grade": sum(r["kind"] == "characterise" for r in g) / len(g) if g else None,
                "overcall": sum(r["kind"] == "grade" for r in ng) / len(ng) if ng else None,
                "by_category": {cat: sum((r["kind"] == "grade") == r["gradable"] for r in rows if r["category"] == cat) /
                                max(1, sum(1 for r in rows if r["category"] == cat))
                                for cat in sorted({r["category"] for r in rows})}}
    nc = {r["item_id"]: (r["kind"] == "grade") == r["gradable"] for r in s1 if r["arm"] == "nocrit" and r["run"] == 1}
    cr = {r["item_id"]: (r["kind"] == "grade") == r["gradable"] for r in s1 if r["arm"] == "crit" and r["run"] == 1}
    both = [i for i in nc if i in cr]
    b = sum(1 for i in both if cr[i] and not nc[i])
    c = sum(1 for i in both if nc[i] and not cr[i])
    res["crit_vs_nocrit_paired"] = {"n": len(both), "gains": b, "losses": c, "mcnemar_p": metrics.mcnemar_exact(b, c)}
    gate = _gate_by_key(gate_rows or [])
    pairs = []                                    # (label_positive, noul, choice_stated) per in_report-labelled card
    for key, lab in labels.items():
        g = gate.get(key[: -len("-dropped")] if key.endswith("-dropped") else key)
        if lab.get("in_report") in ("yes", "no") and g and g.get("noul") is not None:
            pairs.append((lab["in_report"] == "yes", float(g["noul"]), (g.get("choice") or {}).get("choice") == "stated"))
    res["in_report_gate"] = {
        "n_labelled": len(pairs),
        "noul": metrics.binary([(l, n >= 0.5) for l, n, _ in pairs]),
        "choice_stated": metrics.binary([(l, st) for l, _, st in pairs]),
        "noul_bands": metrics.errors_by_band([n for _, n, _ in pairs], [l for l, _, _ in pairs], 0.3, 0.7)}
    return res


def cmd_score(args) -> None:
    res = score(common.read_json(args.labels), common.read_jsonl(args.adjudicated), common.read_jsonl(args.s1),
                common.read_jsonl(args.gate) if args.gate else [])
    print(json.dumps(res, indent=1)); print(common.write_json(common.out_file("gate_c", "score"), res))


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
    pg = sub.add_parser("page"); pg.add_argument("--adjudicated", required=True); pg.add_argument("--clinical", required=True)
    pg.add_argument("--gate", required=True); pg.set_defaults(fn=cmd_page)
    sc = sub.add_parser("score"); sc.add_argument("--labels", required=True); sc.add_argument("--adjudicated", required=True)
    sc.add_argument("--s1", required=True); sc.add_argument("--gate", default=""); sc.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
