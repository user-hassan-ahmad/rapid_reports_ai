"""Phase 1 (spec §5): the wording mini-check for the two new catalogue wordings, T2 on the dictation (T2d) and T6.

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.wording_check \
        --items test_cases/jev_tool_lab/wording_check.json --out-dir $LAB_OUT

A wording passes when AUC >= 0.95, there are zero confident errors at the fixed bands (0.3 / 0.7), at most 20% of
answers land in the unsure band, and repeat drift stays <= 0.2."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set

from dotenv import load_dotenv
from pydantic import BaseModel

from . import calls
from .catalogue import Case, QuestionSpec, render, state_for
from .rules import NOUL_HI, NOUL_LO, _p_yes
from .score import auc, brier, ece


class CheckItem(BaseModel):
    id: str
    kind: Literal["T2d", "T6"]
    scan_type: str = ""
    dictation: str
    topic: Optional[str] = None
    a: Optional[str] = None
    b: Optional[str] = None
    label: bool


def question(item: CheckItem, wording: str) -> dict:
    if item.kind == "T2d":
        spec = QuestionSpec(id=item.id, type="T2", source="dictation", topic=item.topic)
    else:
        spec = QuestionSpec(id=item.id, type="T6", source="dictation", a=item.a, b=item.b)
    return render(spec, wording=wording)


async def run(items: List[CheckItem], wordings=("w1", "w2"), repeats: int = 2, jev_fn=calls.jev) -> List[dict]:
    rows: List[dict] = []
    for wording in wordings:
        for rep in range(1, repeats + 1):
            by_state: Dict[str, Dict[str, dict]] = defaultdict(dict)
            for it in items:
                state = state_for(Case(scan_type=it.scan_type, dictation=it.dictation), "dictation")
                by_state[state][it.id] = question(it, wording)
            answers, _, _ = await jev_fn(dict(by_state))
            for it in items:
                rows.append({"id": it.id, "kind": it.kind, "wording": wording, "repeat": rep,
                             "p": _p_yes(answers.get(it.id)), "label": it.label})
    return rows


def report(rows: List[dict], groups: Optional[Dict[str, Set[str]]] = None) -> Dict[str, dict]:
    """Per kind|wording. Ids in a named group are reported under kind|wording|name instead of the main set
    (peer review: finding-scoped topics and context-side pairs are judged on their own)."""
    member = {i: name for name, ids in (groups or {}).items() for i in ids}
    buckets: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if r["p"] is not None:
            suffix = f"|{member[r['id']]}" if r["id"] in member else ""
            buckets[f"{r['kind']}|{r['wording']}{suffix}"].append(r)
    out: Dict[str, dict] = {}
    for g, rs in sorted(buckets.items()):
        ps, ys = [r["p"] for r in rs], [r["label"] for r in rs]
        by_id: Dict[str, List[float]] = defaultdict(list)
        for r in rs:
            by_id[r["id"]].append(r["p"])
        out[g] = {"n": len(by_id), "auc": round(auc(ps, ys), 3), "brier": round(brier(ps, ys), 3),
                  "ece": round(ece(ps, ys), 3),
                  "confident_errors": sum(1 for p, y in zip(ps, ys) if (p >= NOUL_HI and not y) or (p <= NOUL_LO and y)),
                  "unsure_share": round(sum(1 for p in ps if NOUL_LO < p < NOUL_HI) / len(ps), 3),
                  "max_drift": round(max((max(v) - min(v) for v in by_id.values()), default=0.0), 3)}
    return out


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--group", action="append", default=[],
                    help="name=path.json, a JSON list of ids reported separately (repeatable)")
    args = ap.parse_args()
    groups = {}
    for g in args.group:
        name, path = g.split("=", 1)
        groups[name] = set(json.loads(Path(path).read_text()))
    items = [CheckItem(**x) for x in json.loads(Path(args.items).read_text())]
    rows = asyncio.run(run(items))
    rep = report(rows, groups)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"wording_rows_{os.getpid()}.json").write_text(json.dumps(rows, indent=1))
    (out / f"wording_report_{os.getpid()}.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
