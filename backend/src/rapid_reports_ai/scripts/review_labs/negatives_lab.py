"""Negatives lab (2026-10-03): can one Qwen call label each generated normal/negative statement as dictated, default,
implicated or contradicted (memory feedback_default_negatives)?

    python -m rapid_reports_ai.scripts.review_labs.negatives_lab candidates --replay <jsonl> [<jsonl> ...]
    python -m rapid_reports_ai.scripts.review_labs.negatives_lab classify --runs 2 [--only id8,id8]
    python -m rapid_reports_ai.scripts.review_labs.negatives_lab page --results <jsonl>
    python -m rapid_reports_ai.scripts.review_labs.negatives_lab score --labels <json> --results <jsonl>

Work runs strictly one case at a time. Outputs go under $RR_LAB_OUT/neg_lab/."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator

from rapid_reports_ai.report_review import checked_clauses_in_context, q_dictated
from rapid_reports_ai.scripts.jev_tool_lab import calls

from . import common, label_page

PROMPT = (Path(__file__).parent / "prompts" / "negatives_v1.txt").read_text().strip()
CLASSES = ("dictated", "default", "implicated", "contradicted")
_NEG = re.compile(r"\b(no|not|nil|without|normal(ly)?|unremarkable|patent|intact|clear|preserved|maintained|"
                  r"within normal limits|non-?dilated|undilated|no evidence)\b", re.I)


def is_normal_or_negative(clause: str) -> bool:
    return bool(_NEG.search(clause))


def candidates(report: str) -> List[dict]:
    """Every normal/negative clause the check reads (FINDINGS + IMPRESSION), with the sentence before it."""
    return [{"clause": c, "before": b} for c, b in checked_clauses_in_context(report, None).items()
            if is_normal_or_negative(c)]


class Labels(BaseModel):
    labels: List[str]

    @field_validator("labels", mode="before")
    @classmethod
    def _decode(cls, v):
        return [str(x) for x in common.decode_json_list(v)]


def parse_labels(lines: List[str], n: int) -> Dict[int, dict]:
    """'<n> | <class> | <pointer or -> | <number yes/no>' → {n: {...}}; unknown classes and out-of-range n dropped."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0].strip().isdigit():
            continue
        i, cls = int(parts[0]), parts[1].lower()
        if 1 <= i <= n and cls in CLASSES:
            out[i] = {"cls": cls, "pointer": parts[2] if len(parts) > 2 and parts[2] != "-" else "",
                      "number": len(parts) > 3 and parts[3].lower().startswith("y")}
    return out


def user_message(case: dict, cands: List[dict]) -> str:
    listing = "\n".join(f"{i}. {c['clause']}" for i, c in enumerate(cands, 1))
    return (f"STUDY TITLE: {case['scan']}\n\nCLINICAL HISTORY:\n{case.get('history') or '(none)'}\n\n"
            f"DICTATION:\n{case['dictation']}\n\nREPORT:\n{case['report']}\n\nSTATEMENTS TO CLASSIFY:\n{listing}")


_NUM = re.compile(r"\d+(?:\.\d+)?")


def code_number_flag(clause: str, dictation: str, history: str) -> bool:
    return bool(set(_NUM.findall(clause)) - set(_NUM.findall(f"{dictation}\n{history}")))


# ── CLI ──────────────────────────────────────────────────────────────────────

def _out() -> Path:
    return common.lab_out("neg_lab")


def cmd_candidates(args) -> None:
    common.load_env()
    cases = {c["id8"]: c for c in common.read_json(_out() / "cases.json")}
    rows = {}
    for f in args.replay:
        for r in common.read_jsonl(f):
            if r["id8"] in cases and not r.get("error"):
                rows[r["id8"]] = r                       # last replay wins
    out = []

    async def go():
        for id8, case in cases.items():                  # strictly sequential
            r = rows.get(id8)
            if not r:
                print("no replay for", id8)
                continue
            cands = candidates(r["report"])
            qs = {f"d{i}": q_dictated(c["clause"], c["before"]) for i, c in enumerate(cands)}
            ans, _, _ = await calls.jev({f"SCAN TYPE: {case['scan']}\nDICTATED FINDINGS:\n{case['dictation']}": qs}) if qs else ({}, 0, 0)
            for i, c in enumerate(cands):
                c["jev_dictated"] = (ans.get(f"d{i}") or {}).get("noul")
                c["number_code"] = code_number_flag(c["clause"], case["dictation"], case["history"])
            out.append({**case, "report": r["report"], "candidates": cands})
            print(id8, len(cands), "candidates")
    asyncio.run(go())
    print(common.write_json(_out() / "candidates.json", out), sum(len(c["candidates"]) for c in out))


async def _classify(cases: List[dict], runs: int, path) -> None:
    with open(path, "a") as fh:
        for run in range(1, runs + 1):
            for case in cases:                           # strictly sequential
                cands = case["candidates"]
                try:
                    out, usage = await calls.qwen(Labels, PROMPT, user_message(case, cands), True)
                    parsed, err = parse_labels(out.labels, len(cands)), None
                except Exception as e:   # noqa: BLE001
                    parsed, usage, err = {}, None, f"{type(e).__name__}: {str(e)[:200]}"
                fh.write(json.dumps({"id8": case["id8"], "run": run, "error": err,
                                     "usage": usage.model_dump() if usage else None,
                                     "labels": {str(k): v for k, v in parsed.items()}, "n": len(cands)}) + "\n")
                fh.flush()
                print(f"run {run} {case['id8']} labelled {len(parsed)}/{len(cands)} err={err is not None}", flush=True)


def cmd_classify(args) -> None:
    common.load_env()
    cases = common.read_json(_out() / "candidates.json")
    if args.only:
        cases = [c for c in cases if c["id8"] in set(args.only.split(","))]
    path = common.out_file("neg_lab", f"classify_{args.tag}", "jsonl")
    asyncio.run(_classify(cases, args.runs, path))
    print(path)


FIELDS = [{"key": "verdict", "label": "Class", "type": "choice", "options": list(CLASSES), "required": True},
          {"key": "note", "type": "text", "label": "Note"}]
RULES = ("dictated = the dictation states this normal/negative. default = not dictated, nothing dictated points towards "
         "what it denies: correct by convention, keep. implicated = not dictated, but a dictated finding points towards "
         "what it denies (consequence, extension, cause, same structure/level/region): should be an option, not core. "
         "contradicted = the dictation states the opposite. The model's call and Jev's 'dictated' score appear after you choose.")


def cmd_page(args) -> None:
    cases = common.read_json(_out() / "candidates.json")
    res = {(r["id8"], r["run"]): r for r in common.read_jsonl(args.results)}
    cards = [{"id": "rules", "title": "Labelling rules", "meta": "read first", "blocks": [{"label": "Rules", "text": RULES}],
              "hidden": []}]
    for case in cases:
        r1 = (res.get((case["id8"], 1)) or {}).get("labels", {})
        r2 = (res.get((case["id8"], 2)) or {}).get("labels", {})
        for i, c in enumerate(case["candidates"], 1):
            m1, m2 = r1.get(str(i)) or {}, r2.get(str(i)) or {}
            cards.append({"id": f"{case['id8']}-{i}", "title": f"{case['id8']} · {case['scan']} · #{i}",
                          "meta": "number not in dictation (code)" if c.get("number_code") else "",
                          "blocks": [{"label": "Report statement", "text": c["clause"]},
                                     {"label": "Dictation", "text": case["dictation"]},
                                     {"label": "Clinical history", "text": case.get("history") or "(none)"},
                                     {"label": "Full report", "text": case["report"], "highlight": [c["clause"]],
                                      "collapsed": True}],
                          "hidden": [{"label": "Model (run 1 / run 2)",
                                      "text": f"{m1.get('cls')} / {m2.get('cls')}  ·  pointer: {m1.get('pointer') or '-'}"
                                              f"  ·  number: {m1.get('number')}"},
                                     {"label": "Jev 'dictated' score", "text": str(c.get("jev_dictated"))}]})
    print(label_page.write_page(_out() / "negatives.html", "Negatives lab · label generated negatives",
                                "neglab-v1", cards, FIELDS), len(cards) - 1)


def score(labels: Dict[str, dict], results: List[dict]) -> dict:
    gold = {k: v["verdict"] for k, v in labels.items() if isinstance(v, dict) and v.get("verdict") in CLASSES}
    by_run = {}
    for r in results:
        for i, m in (r.get("labels") or {}).items():
            by_run.setdefault(r["run"], {})[f"{r['id8']}-{i}"] = m["cls"]
    out = {"n_gold": len(gold), "gold": dict(Counter(gold.values()))}
    for run, pred in sorted(by_run.items()):
        ids = [k for k in gold if k in pred]
        conf = Counter((gold[k], pred[k]) for k in ids)
        imp_gold = [k for k in ids if gold[k] == "implicated"]
        imp_pred = [k for k in ids if pred[k] == "implicated"]
        bad = [k for k in ids if gold[k] in ("implicated", "contradicted")]
        out[f"run{run}"] = {
            "n": len(ids), "accuracy": sum(gold[k] == pred[k] for k in ids) / len(ids) if ids else None,
            "implicated_recall": sum(pred[k] == "implicated" for k in imp_gold) / len(imp_gold) if imp_gold else None,
            "implicated_precision": sum(gold[k] == "implicated" for k in imp_pred) / len(imp_pred) if imp_pred else None,
            # the safety number: an implicated/contradicted negative the model would leave in the core as default/dictated
            "unsafe_misses": sorted(k for k in bad if pred[k] in ("default", "dictated")),
            "confusion": {f"{g}->{p}": n for (g, p), n in sorted(conf.items())},
        }
    if 1 in by_run and 2 in by_run:
        common_ids = [k for k in by_run[1] if k in by_run[2]]
        out["run_flip_share"] = (sum(by_run[1][k] != by_run[2][k] for k in common_ids) / len(common_ids)
                                 if common_ids else None)
    return out


def cmd_score(args) -> None:
    res = score(common.read_json(args.labels), common.read_jsonl(args.results))
    print(json.dumps(res, indent=1))
    print(common.write_json(common.out_file("neg_lab", "score"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates"); c.add_argument("--replay", nargs="+", required=True); c.set_defaults(fn=cmd_candidates)
    k = sub.add_parser("classify"); k.add_argument("--runs", type=int, default=2); k.add_argument("--only", default="")
    k.add_argument("--tag", default="v1"); k.set_defaults(fn=cmd_classify)
    p = sub.add_parser("page"); p.add_argument("--results", required=True); p.set_defaults(fn=cmd_page)
    s = sub.add_parser("score"); s.add_argument("--labels", required=True); s.add_argument("--results", required=True)
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
