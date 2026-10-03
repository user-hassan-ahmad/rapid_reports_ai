# backend/src/rapid_reports_ai/scripts/review_labs/gate_d.py
"""Gate D: read-only production audit of the automatic edits since L-49 (spec §9, §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_d pull [--since 2026-10-01]
    python -m rapid_reports_ai.scripts.review_labs.gate_d page
    python -m rapid_reports_ai.scripts.review_labs.gate_d rescore [--only key,key]
    python -m rapid_reports_ai.scripts.review_labs.gate_d decide --labels <json> --rescored <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List, Optional

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


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("--since", default="2026-10-01"); p.set_defaults(fn=cmd_pull)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
