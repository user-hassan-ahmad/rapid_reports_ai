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
from typing import List, Optional

from . import common, label_page

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


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases").set_defaults(fn=cmd_cases)
    sub.add_parser("gold-page").set_defaults(fn=cmd_gold_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
