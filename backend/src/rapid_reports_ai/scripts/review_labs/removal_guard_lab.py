"""Removal-guard lab (2026-10-09): is Jev's statement type (`jev_pass.q_type`, argmax == "normal") a safe guard before
the post-gen check deletes a contradicted negative sentence? Asked of whole report sentences, in the same dictation-state
request the check uses (SCAN TYPE + DICTATED FINDINGS).

    python -m rapid_reports_ai.scripts.review_labs.removal_guard_lab build [--days 45]
    # peer read: write $RR_LAB_OUT/removal_guard/gold.json  {sid: "pure" | "carries"}
    python -m rapid_reports_ai.scripts.review_labs.removal_guard_lab run [--only sid,sid] [--run 1]
    python -m rapid_reports_ai.scripts.review_labs.removal_guard_lab score --results <jsonl> [--results <jsonl>]

Gold: "pure" = only absences / normal structures; "carries" = also something present or abnormal, a measurement, a
change, or a hedge ("not excluded"). Removal is allowed only on "normal": a carries sentence called normal is the
dangerous error (looseness, must be 0); a pure sentence not called normal is a nuisance (strictness).

Production text stays under $RR_LAB_OUT/removal_guard/; the repo fixture is synthetic only."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import report_review as rr
from rapid_reports_ai.review_engine.jev_pass import TYPES, clause_type_of, q_type

from . import common

GATE = "removal_guard"
FIXTURE = Path(__file__).parent / "fixtures" / "removal_guard_cases.json"
_NEGATOR = re.compile(r"\b(?:no|without|nil|not)\b", re.I)

SQL = """select id::text as id, input_data, candidate_reports->0->>'content' as cand, report_content
from reports where created_at >= now() - interval '{days} days'
  and (candidate_reports->0->>'content' is not null or report_content is not null)
order by created_at"""


def _obj(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def candidates(report: str) -> List[str]:
    findings, imp = rr.report_sections(report)
    out = []
    for s in rr._sentences(findings) + rr._sentences(imp):
        if _NEGATOR.search(s) and (rr.restate(s) is not None or " no " in f" {s.lower()} "):
            out.append(s)
    return out


def cmd_build(args) -> None:
    common.load_env()
    out = common.lab_out(GATE)
    rows = common.metabase(SQL.format(days=int(args.days)))
    cases, seen = [], set()
    for r in rows:
        v = _obj(r.get("input_data")).get("variables") or {}
        report = r.get("cand") or r.get("report_content") or ""
        sents = [s for s in candidates(report) if s not in seen]
        seen.update(sents)
        if sents:
            cases.append({"id8": r["id"][:8], "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "",
                          "sentences": [{"sid": f"{r['id'][:8]}-{k}", "text": s} for k, s in enumerate(sents)]})
    common.write_json(out / "cases.json", cases)
    print(len(rows), "reports;", len(cases), "with candidates;", sum(len(c["sentences"]) for c in cases), "sentences")


def _items() -> List[dict]:
    """One Jev request per report (as in the check); synthetic cases are one-sentence reports."""
    out = common.lab_out(GATE)
    gold = common.read_json(out / "gold.json") if (out / "gold.json").exists() else {}
    items = [{"set": "real", "scan": c["scan"], "dictation": c["dictation"],
              "sentences": [dict(s, gold=gold.get(s["sid"])) for s in c["sentences"]]}
             for c in common.read_json(out / "cases.json")]
    for c in common.read_json(FIXTURE):
        items.append({"set": "synthetic", "scan": c["scan"], "dictation": c["dictation"],
                      "sentences": [{"sid": c["id"], "text": c["sentence"], "gold": c["gold"]}]})
    return items


async def _run(items: List[dict], only: set, run: int, path) -> None:
    with open(path, "a") as fh:
        for it in items:                                           # strictly sequential
            sents = [s for s in it["sentences"] if not only or s["sid"] in only]
            if not sents:
                continue
            qs = {f"t{k}": q_type(s["text"]) for k, s in enumerate(sents)}
            try:
                ans = await rc._jev(f"SCAN TYPE: {it['scan']}\nDICTATED FINDINGS:\n{it['dictation']}", qs)
                err = None
            except Exception as e:   # noqa: BLE001
                ans, err = {}, f"{type(e).__name__}: {e}"
            for k, s in enumerate(sents):
                a = ans.get(f"t{k}")
                fh.write(json.dumps({"sid": s["sid"], "set": it["set"], "run": run, "gold": s["gold"],
                                     "type": clause_type_of(a), "probs": (a or {}).get("probabilities"),
                                     "error": err}) + "\n")
            fh.flush()


def cmd_run(args) -> None:
    common.load_env()
    path = common.out_file(GATE, f"jev_run{args.run}", "jsonl")
    asyncio.run(_run(_items(), set(args.only.split(",")) if args.only else set(), args.run, path))
    print(path)


def cmd_score(args) -> None:
    rows = [r for p in args.results for r in common.read_jsonl(p)]
    for st in ("real", "synthetic"):
        r1 = [r for r in rows if r["set"] == st and r["run"] == 1 and r["gold"]]
        conf = Counter((r["gold"], r["type"]) for r in r1)
        out = {"n": len(r1), "confusion": {f"{g}->{t}": n for (g, t), n in sorted(conf.items(), key=str)}}
        for g in ("pure", "carries"):
            gs = [r for r in r1 if r["gold"] == g]
            out[f"{g}_normal_rate"] = f"{sum(r['type'] == 'normal' for r in gs)}/{len(gs)}"
        r2 = {r["sid"]: r["type"] for r in rows if r["set"] == st and r["run"] == 2}
        out["run2_on_disagreements"] = {sid: [next(r["type"] for r in r1 if r["sid"] == sid), t] for sid, t in r2.items()}
        pn = sorted((float((r["probs"] or {}).get("normal", 0)), r["gold"], r["sid"]) for r in r1)
        out["p_normal_carries_max"] = max([p for p, g, _ in pn if g == "carries"], default=None)
        out["p_normal_pure_lt_0.5"] = [(round(p, 3), sid) for p, g, sid in pn if g == "pure" and p < 0.5]
        print(st, json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--days", default=45)
    r = sub.add_parser("run")
    r.add_argument("--only")
    r.add_argument("--run", type=int, default=1)
    s = sub.add_parser("score")
    s.add_argument("--results", action="append", required=True)
    a = ap.parse_args()
    {"build": cmd_build, "run": cmd_run, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
