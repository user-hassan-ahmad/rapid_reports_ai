# backend/src/rapid_reports_ai/scripts/review_labs/gate_a.py
"""Gate A: Coverage recall (spec §11).

    python -m rapid_reports_ai.scripts.review_labs.gate_a page            # 27-card labelling page
    python -m rapid_reports_ai.scripts.review_labs.gate_a items           # the ~72 items (50 cards + unsampled pool)
    python -m rapid_reports_ai.scripts.review_labs.gate_a run --runs 2 [--only c2,c3]
    python -m rapid_reports_ai.scripts.review_labs.gate_a read-page --results <jsonl>
    python -m rapid_reports_ai.scripts.review_labs.gate_a score --labels <json> --read <json> --results <jsonl>"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List, Optional

from . import common, judgement, label_page, metrics

LABEL_SET = [2, 3, 4, 5, 6, 7, 9, 11, 18, 20, 24, 25, 28, 31, 33, 35, 38, 39, 40, 42, 43, 44, 46, 47, 48, 49, 50]
KIND_MAP = {"partial": ("coverage", "partial"), "differs": ("coverage", "differs"),
            "omission": ("coverage", "absent"), "contradiction": ("accuracy", "contradicted")}
FIELDS = [{"key": "verdict", "label": "Should show as", "type": "choice",
           "options": ["action", "minor", "info", "suppress"], "required": True},
          {"key": "material", "type": "check", "label": "Material loss"},
          {"key": "note", "type": "text", "label": "Note"}]
RULES = ("action = dictated meaning lost or changed, the radiologist should fix it. minor = real but low impact. "
         "info = a speech-recognition slip the report fixed. suppress = noise (present elsewhere, no effect, misread). "
         "Tick 'Material loss' for a clinically material loss. The engine's call and the peer read appear after you choose.")


def label_card(src: dict, peer: Optional[dict]) -> dict:
    line = src["detector_line"]
    return {
        "id": f"c{src['n']}", "title": f"Card {src['n']} · {src['kind']}", "meta": f"{src['scan']} · {src['id8']}",
        "blocks": [
            {"label": "Flagged" + (" report statement" if src["kind"] == "contradiction" else " dictated line"), "text": line},
            {"label": "Nearest report sentence", "text": src.get("report_sentence") or ""},
            {"label": "Full dictation", "text": src["dictation_full"], "highlight": [line], "collapsed": True},
            {"label": "Full report", "text": src["report_full"], "highlight": [src.get("report_sentence") or ""],
             "collapsed": True},
        ],
        "hidden": [
            {"label": "v3 call", "text": f"{src.get('class')}: {src.get('issue') or ''}"},
            {"label": "Peer read (2026-10-03)",
             "text": f"{peer['verdict']}: {peer['reason']}" if peer else "not in the peer read (both reads: suppress)"},
        ],
    }


def cmd_page(_args) -> None:
    cards = {c["n"]: c for c in common.read_json(common.pipeline_scratch() / "review_cards50_v3.json")}
    out = common.lab_out("gate_a")
    peer = {p["n"]: p for f in ("blind_A.json", "blind_B.json") for p in common.read_json(out / f)}
    page_cards = [{"id": "rules", "title": "Labelling rules", "meta": "read first", "blocks": [{"label": "Rules", "text": RULES}],
                   "hidden": []}]
    page_cards += [label_card(cards[n], peer.get(n)) for n in LABEL_SET]
    p = label_page.write_page(out / "label_27.html", "Gate A · label 27 cards", "gateA-label27-v1", page_cards, FIELDS)
    print(p)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("page").set_defaults(fn=cmd_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
