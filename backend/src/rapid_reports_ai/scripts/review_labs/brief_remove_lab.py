"""Brief OMIT removal lab (2026-10-09, feat/negatives-one-owner): when the brief labels a report negative OMIT
(contradicted by the dictation), is removing it on contra >= 0.6 and a purely negative sentence (q_type "normal")
right, in the zone where the L-47 guards (restated >= 0.5, dictated < 0.5) disagree?

    python -m rapid_reports_ai.scripts.review_labs.brief_remove_lab run --runs 2 [--only id,id]
    python -m rapid_reports_ai.scripts.review_labs.brief_remove_lab score --results <jsonl>

Cases are synthetic (fixtures/brief_remove_cases.json); the brief OMIT label is assumed present for every case.
Outputs go under $RR_LAB_OUT/brief_remove/. One Jev request per case per run, strictly sequential (Jev only)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.report_review import (CONTRA_FLAG, DICTATED_KEEP, Q_CONTRA, RESTATED_FLAG, q_dictated,
                                            q_restated, restate)
from rapid_reports_ai.review_engine.jev_pass import clause_type_of, q_type

from . import common

GATE = "brief_remove"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "brief_remove_cases.json"


def questions(sentence: str) -> dict:
    """The check() builders, verbatim: contradiction, restated (when the clause is a negative), dictated, type."""
    qs = {"c": {"type": "noul", "instructions": Q_CONTRA + sentence}}
    r = restate(sentence)
    if r:
        qs["r"] = q_restated(r)
    qs["d"] = q_dictated(sentence, "")
    qs["typ"] = q_type(sentence)
    return qs


def _state(c: dict) -> str:
    return f"SCAN TYPE: {c['scan']}\nDICTATED FINDINGS:\n{c['dictation']}"


async def _run(cases: List[dict], runs: int, path) -> None:
    with open(path, "a") as fh:
        for run in range(1, runs + 1):
            for c in cases:
                try:
                    ans, err = await rc._jev(_state(c), questions(c["sentence"])), None
                except Exception as e:   # noqa: BLE001
                    ans, err = {}, f"{type(e).__name__}: {e}"
                fh.write(json.dumps({"id": c["id"], "run": run, "gold": c["gold"], "zone": c["zone"],
                                     "domain": c["domain"], "sentence": c["sentence"], "answer": ans,
                                     "error": err}) + "\n")
                fh.flush()


def cmd_run(args) -> None:
    common.load_env()
    cases = common.read_json(FIXTURE)
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only.split(","))]
    path = common.out_file(GATE, "brief_remove_jev", "jsonl")
    asyncio.run(_run(cases, args.runs, path))
    print(path)


def _noul(ans: dict, k: str) -> Optional[float]:
    try:
        return float(ans[k]["noul"])
    except Exception:   # noqa: BLE001
        return None


def decide(ans: dict) -> Optional[dict]:
    c, r, d, t = _noul(ans, "c"), _noul(ans, "r"), _noul(ans, "d"), clause_type_of(ans.get("typ"))
    if c is None or d is None:
        return None
    r = 0.0 if r is None else r   # restate() found no denied finding: L-47 cannot confirm
    neg = t == "normal"
    l47 = c >= CONTRA_FLAG and r >= RESTATED_FLAG and d < DICTATED_KEEP and neg
    brief = c >= CONTRA_FLAG and neg
    return {"contra": c, "restated": r, "dictated": d, "type": t, "l47": l47, "brief": brief, "extra": brief and not l47}


def _tally(rows: List[dict], key: str) -> dict:
    tp = sum(r[key] and r["gold"] == "remove" for r in rows)
    fp = sum(r[key] and r["gold"] == "keep" for r in rows)
    fn = sum(not r[key] and r["gold"] == "remove" for r in rows)
    return {"tp": tp, "fp": fp, "fn": fn}


def score(rows: List[dict]) -> dict:
    by_run: Dict[int, List[dict]] = {}
    for row in rows:
        dec = decide(row.get("answer") or {})
        if dec is None:
            continue
        by_run.setdefault(row["run"], []).append({**row, **dec, "answer": None})
    out: dict = {"runs": {}}
    for run, rs in sorted(by_run.items()):
        out["runs"][run] = {
            "n": len(rs), "l47": _tally(rs, "l47"), "brief": _tally(rs, "brief"),
            "extra": {"correct": sum(r["extra"] and r["gold"] == "remove" for r in rs),
                      "wrong": [f"{r['id']} [{r['zone']}] {r['sentence']} (c={r['contra']:.2f} r={r['restated']:.2f} "
                                f"d={r['dictated']:.2f})" for r in rs if r["extra"] and r["gold"] == "keep"]},
            "missed_by_brief": [r["id"] for r in rs if not r["brief"] and r["gold"] == "remove"],
            "cases": {r["id"]: {k: (round(r[k], 2) if isinstance(r[k], float) else r[k])
                                for k in ("gold", "contra", "restated", "dictated", "type", "l47", "brief")} for r in rs}}
    if len(by_run) >= 2:
        r1, r2 = (({r["id"]: r for r in by_run[k]}) for k in sorted(by_run)[:2])
        common_ids = r1.keys() & r2.keys()
        out["stability"] = {
            "flips_l47": sorted(i for i in common_ids if r1[i]["l47"] != r2[i]["l47"]),
            "flips_brief": sorted(i for i in common_ids if r1[i]["brief"] != r2[i]["brief"]),
            "max_drift": {k: round(max(abs(r1[i][k] - r2[i][k]) for i in common_ids), 3)
                          for k in ("contra", "restated", "dictated")},
            "type_changes": sorted(i for i in common_ids if r1[i]["type"] != r2[i]["type"])}
    return out


def cmd_score(args) -> None:
    res = score(common.read_jsonl(args.results))
    print(json.dumps(res, indent=1))
    print(common.write_json(common.out_file(GATE, "brief_remove_score"), res))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--runs", type=int, default=2); r.add_argument("--only", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score"); s.add_argument("--results", required=True); s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
