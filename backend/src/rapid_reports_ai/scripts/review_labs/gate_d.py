# backend/src/rapid_reports_ai/scripts/review_labs/gate_d.py
"""Gate D: read-only production audit of the automatic edits since L-49 (spec §9, §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_d pull [--since 2026-10-01]
    python -m rapid_reports_ai.scripts.review_labs.gate_d replay --source <json> [--limit N] [--only id8,...]
    python -m rapid_reports_ai.scripts.review_labs.gate_d page
    python -m rapid_reports_ai.scripts.review_labs.gate_d rescore [--only key,key]
    python -m rapid_reports_ai.scripts.review_labs.gate_d decide --labels <json> --rescored <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

from rapid_reports_ai import report_review
from rapid_reports_ai.report_review import is_negative

from . import common, judgement, label_page


def reconstruct(qc: dict, content: str, final: Optional[str]) -> List[dict]:
    kept = {k.get("text") for k in qc.get("kept_dictated_negative") or []}
    edits = []
    for f in qc.get("flags") or []:
        if f["kind"] == "contradiction" and is_negative(f["text"]) and f["text"] not in kept:
            edits.append({"type": "removal", "text": f["text"], "score": f.get("score"),
                          "still_absent": f["text"].lower() not in content.lower()})
        elif f["kind"] == "omission":
            a, b = common.best_sentence(content, f["text"])
            located = content[a:b].strip()
            edits.append({"type": "insertion", "text": f["text"], "score": f.get("score"), "located": located,
                          "kept_by_user": None if final is None else located in final})
    return edits


SQL = """select id::text as id, created_at::text as created_at, report_type, input_data,
       candidate_reports->0->>'content' as content, final_report_content,
       candidate_reports->0->'quality_check' as qc
from reports
where created_at >= '{since}' and candidate_reports->0->'quality_check' is not null
  and (coalesce((candidate_reports->0->'quality_check'->>'clauses_removed')::int, 0) > 0
       or coalesce((candidate_reports->0->'quality_check'->>'edits_applied')::int, 0) > 0)
order by created_at"""


def cmd_pull(args) -> None:
    rows = common.metabase(SQL.format(since=args.since))
    out = []
    for r in rows:
        qc = json.loads(r["qc"]) if isinstance(r["qc"], str) else r["qc"]
        inp = json.loads(r["input_data"]) if isinstance(r["input_data"], str) else (r["input_data"] or {})
        v = inp.get("variables") or {}
        for k, e in enumerate(reconstruct(qc, r["content"] or "", r["final_report_content"])):
            out.append({"key": f"{r['id'][:8]}-{k}", "report_id": r["id"], "created_at": r["created_at"],
                        "report_type": r["report_type"], "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "",
                        "history": v.get("CLINICAL_HISTORY") or "", "content": r["content"] or "",
                        "final": r["final_report_content"], **e})
    p = common.write_json(common.lab_out("gate_d") / f"edits_since_{args.since}.json", out)
    by = {t: sum(1 for e in out if e["type"] == t) for t in ("removal", "insertion")}
    print(p, len(rows), "reports", by)


def replay_edits(tel: dict, report: str, new_report: str) -> List[dict]:
    """Edits of a replayed quality check. Insertions are located EXACTLY: the sentences present in the new report and
    absent from the old one. Removals count only when the flagged text is really gone from the new report."""
    if new_report == report:
        return []
    old = {report[a:b].strip() for a, b in common.sentences(report)}
    added = "\n".join(t for a, b in common.sentences(new_report) if (t := new_report[a:b].strip()) not in old)
    out = []
    for e in reconstruct(tel, new_report, None):
        if e["type"] == "removal" and not e["still_absent"]:
            continue
        if e["type"] == "insertion":
            if added:
                a, b = common.best_sentence(added, e["text"])
                e["located"] = added[a:b].strip()
            e["located_exact"] = bool(added)
            e["kept_by_user"] = None
        out.append({**e, "original": report})
    return out


async def _replay(rows: List[dict]) -> List[dict]:
    sem = asyncio.Semaphore(6)

    async def one(r: dict) -> List[dict]:
        v = (r.get("input_data") or {}).get("variables") or {}
        report = r.get("report_content") or ""
        async with sem:
            new_report, _, tel = await report_review.run_quality_check(report, v.get("FINDINGS") or "", v.get("SCAN_TYPE") or "", [])
        return [{"key": f"{str(r['id'])[:8]}-{k}", "report_id": str(r["id"]), "created_at": "replay", "report_type": "replay",
                 "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "", "history": v.get("CLINICAL_HISTORY") or "",
                 "content": new_report, "final": None, **e}
                for k, e in enumerate(replay_edits(tel, report, new_report))]
    return [e for part in await asyncio.gather(*(one(r) for r in rows)) for e in part]


def cmd_replay(args) -> None:
    common.load_env()
    rows = common.read_json(args.source)
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if str(r["id"])[:8] in keep]
    if args.limit:
        rows = rows[: args.limit]
    out = asyncio.run(_replay(rows))
    p = common.write_json(common.lab_out("gate_d") / "edits_replay.json", out)
    print(p, len(rows), "reports", {t: sum(1 for e in out if e["type"] == t) for t in ("removal", "insertion")})


D_FIELDS = [{"key": "verdict", "label": "This automatic edit was", "type": "choice",
             "options": ["correct", "redundant", "harmful"], "required": True},
            {"key": "harm", "label": "Harm type", "type": "choice",
             "options": ["invented", "duplicated", "incoherent", "whole-line rewrite", "other"]},
            {"key": "note", "type": "text", "label": "Note"}]


def _latest_path():
    """edits_replay.json when present, else the widest pull window (the earliest --since is a superset)."""
    d = common.lab_out("gate_d")
    if (d / "edits_replay.json").exists():
        return d / "edits_replay.json"
    return sorted(d.glob("edits_since_*.json"))[0]


def _latest_edits() -> List[dict]:
    return common.read_json(_latest_path())


def _source_label() -> str:
    n = _latest_path().stem
    return "replay" if n == "edits_replay" else "pull since " + n.removeprefix("edits_since_")


def cmd_page(_args) -> None:
    cards = []
    label = _source_label()
    for e in _latest_edits():
        what = (f"REMOVED from the report: \u00ab{e['text']}\u00bb" if e["type"] == "removal"
                else f"INSERTED for the dictated line \u00ab{e['text']}\u00bb\nlocated sentence: \u00ab{e['located']}\u00bb\n"
                     f"radiologist kept it: {e['kept_by_user']}")
        cards.append({"id": e["key"], "title": f"{e['key']} \u00b7 {e['type']}", "meta": f"{e['scan']} \u00b7 {e['created_at'][:16]}",
                      "blocks": [{"label": "Automatic edit", "text": what},
                                 {"label": "Report as shown", "text": e["content"],
                                  "highlight": [e.get("located") or ""], "collapsed": True},
                                 {"label": "Dictation", "text": e["dictation"], "highlight": [e["text"]], "collapsed": True},
                                 {"label": "Final (radiologist)", "text": e.get("final") or "(not finalised)", "collapsed": True}],
                      "hidden": []})
    print(label_page.write_page(common.lab_out("gate_d") / "edits.html", f"Gate D \u00b7 automatic edits ({label})",
                                "gateD-edits-v1-" + label.replace(" ", "-"), cards, D_FIELDS), len(cards))


def pre_edit(e: dict) -> str:
    """The report before the edit. Replay rows carry it as `original`. Live-pulled rows: insertion -> the located
    sentence deleted; removal -> the clause re-added at the end of FINDINGS (position approximate, a ledger limitation)."""
    if e.get("original") is not None:
        return e["original"]
    if e["type"] == "insertion":
        return e["content"].replace(e["located"], "", 1)
    c = e["content"]
    i = c.find("\nIMPRESSION:")
    return (c[:i] + f" {e['text']}." + c[i:]) if i >= 0 else c + f"\n{e['text']}."


async def _rescore(edits: List[dict], out_path) -> None:
    sem = asyncio.Semaphore(8)

    async def one(e):
        case = {"scan": e["scan"], "dictation": e["dictation"], "history": e["history"], "report": pre_edit(e)}
        cand = ({"lane": "coverage", "kind": "absent", "detector": "jev.classify_first", "line": e["text"], "anchor": None,
                 "evidence": {}} if e["type"] == "insertion" else
                {"lane": "accuracy", "kind": "contradicted", "detector": "jev.contradiction", "line": None,
                 "anchor": e["text"], "evidence": {}})
        r = await judgement.judge_and_verify(case, [cand], sem)
        would = bool(r.get("cls") == "action" and r.get("verified") and r["verified"]["code"]
                     and not r["verified"].get("unconfirmed") and r.get("kind") != "slip"
                     and ((e["type"] == "insertion" and r.get("kind") == "absent" and r.get("edit_mode") == "insert")
                          or (e["type"] == "removal" and r.get("edit_mode") == "remove")))
        return {"key": e["key"], "type": e["type"], "would_pre_apply": would, **r}
    with open(out_path, "w") as fh:
        for row in await asyncio.gather(*(one(e) for e in edits)):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_rescore(args) -> None:
    common.load_env()
    edits = _latest_edits()
    if args.only:
        edits = [e for e in edits if e["key"] in set(args.only.split(","))]
    out = common.out_file("gate_d", "rescored", "jsonl")
    asyncio.run(_rescore(edits, out))
    print(out)


def cmd_decide(args) -> None:
    labels = common.read_json(args.labels)
    rows = common.read_jsonl(args.rescored)
    res = {}
    for t in ("insertion", "removal"):
        mine = [r for r in rows if r["type"] == t]
        routed = [r for r in mine if r["would_pre_apply"]]
        lab = [labels.get(r["key"], {}).get("verdict") for r in routed]
        today = [labels.get(r["key"], {}).get("verdict") for r in mine]
        correct = sum(v == "correct" for v in lab) / len(lab) if lab else None
        res[t] = {"n_today": len(mine), "today": {v: today.count(v) for v in ("correct", "redundant", "harmful")},
                  "n_routed_pre_apply": len(routed), "routed_correct_share": correct,
                  "routed_harmful": sum(v == "harmful" for v in lab),
                  "option": "A" if (correct is not None and correct >= 0.95 and not any(v == "harmful" for v in lab)) else "B"}
    print(json.dumps(res, indent=1)); print(common.write_json(common.out_file("gate_d", "decision"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("--since", default="2026-10-01"); p.set_defaults(fn=cmd_pull)
    q = sub.add_parser("replay"); q.add_argument("--source", required=True); q.add_argument("--limit", type=int, default=0)
    q.add_argument("--only", default=""); q.set_defaults(fn=cmd_replay)
    sub.add_parser("page").set_defaults(fn=cmd_page)
    r = sub.add_parser("rescore"); r.add_argument("--only", default=""); r.set_defaults(fn=cmd_rescore)
    d = sub.add_parser("decide"); d.add_argument("--labels", required=True); d.add_argument("--rescored", required=True)
    d.set_defaults(fn=cmd_decide)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
