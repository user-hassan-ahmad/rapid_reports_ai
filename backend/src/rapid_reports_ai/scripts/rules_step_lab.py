"""Rules-step lab (spec 2026-10-13-template-rules-step-design, "The lab for this spec"). Reported, not gated: it
prints tables and writes JSON under the private folder; Hassan decides.

    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab decide --root <dir> [--run 1|2] [--only slug,...]
    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root <dir> --stage decide

<dir> is ~/Code/rr-template-conversion-private/synthetic/rules_step (never the repo). Sets: <dir>/sets/*.json (format
in the plan, Task 19). Outputs: <dir>/runs/<stage>/run<k>/<slug>.json and <dir>/REPORT_<stage>.md. The generator of
the synthetic sets (Claude) is never the model under test (Qwen, Jev)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional


def _n(s: str) -> str:
    return " ".join((s or "").lower().split())


def load_sets(root: Path, only: Optional[List[str]] = None) -> List[dict]:
    sets = [json.loads(p.read_text()) for p in sorted((root / "sets").glob("*.json"))]
    return [s for s in sets if not only or s["slug"] in only]


def _value_names(truth_value: dict) -> set:
    return {_n(truth_value["name"]), *(_n(a) for a in truth_value.get("aliases") or [])}


def score_decide(s: dict, payload: dict) -> dict:
    """One set's decision-run result against its planted truth."""
    truth = s["truth"]
    n = len(s["examples"])
    from rapid_reports_ai.template_rules_cards import flat
    cards = flat(payload.get("cards", []) + payload.get("more", []))
    value_cards = {_n(c["key"]): c for c in cards + payload.get("kept", []) if c["id"].startswith("value:")}
    kept_ids = {c["id"] for c in payload.get("kept", [])}
    found = every_kept = partial_carded = 0
    matched = set()
    for v in truth.get("values", []):
        hit = next((k for k in value_cards if k in _value_names(v)), None)
        if hit is None:
            continue
        found += 1
        matched.add(hit)
        in_all = len(v["reports"]) == n
        every_kept += in_all and value_cards[hit]["id"] in kept_ids
        partial_carded += (not in_all) and value_cards[hit]["id"] not in kept_ids
    states = payload.get("states") or {}
    cells = correct = 0
    for name, t in truth.get("concepts", {}).items():
        said = set(states.get(name) or [])
        for k in range(1, n + 1):
            cells += 1
            correct += (k in said) == (k in set(t.get("stated_in") or []))
    # contrast polarity (D1): the stored condition is the opposite of the usual state the set was planted with
    from rapid_reports_ai import template_decisions as td
    pol_total = pol_ok = 0
    for name, t in truth.get("concepts", {}).items():
        card = next((c for c in cards if c.get("key") == name and c.get("wording")), None)
        if not t.get("usual_state") or card is None:
            continue
        pol_total += 1
        other = next(st for st in td.CONCEPTS[name].states if st != t["usual_state"])
        pol_ok += card["wording"].get("condition") == td.CONCEPTS[name].states[other]
    dis = {c["key"] for c in cards if c.get("kind") == "disagree"}
    return {"slug": s["slug"], "kind": s.get("kind", "base"), "values_found": found,
            "values_total": len(truth.get("values", [])), "values_extra": len(set(value_cards) - matched),
            "every_kept": every_kept, "partial_carded": partial_carded, "concept_cells": cells,
            "concept_correct": correct, "disagreements_found": len(dis & set(truth.get("disagreements", []))),
            "disagreements_total": len(truth.get("disagreements", [])), "polarity_correct": pol_ok,
            "polarity_total": pol_total, "cards": len(cards),
            "over_budget": len(cards) > 8, "dropped_quotes": (payload.get("run") or {}).get("dropped_quotes", 0)}


def summarise(rows: List[dict], fields: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in rows:
        agg = out.setdefault(r.get("kind", "base"), {"n": 0, **{f: 0 for f in fields}})
        agg["n"] += 1
        for f in fields:
            agg[f] += int(r.get(f) or 0)
    return out


async def _decide_one(s: dict) -> dict:
    from rapid_reports_ai import template_decision_run as tdr
    from rapid_reports_ai import template_rules_cards as trc
    run = await tdr.run_decisions(s["examples"], s.get("scan_type", ""))
    built = trc.build_cards(run, len(s["examples"]))
    return {**built, "ok": run.ok, "states": run.states, "run": tdr.evidence(run, built),
            "candidates": {"values": [v.model_dump() for v in run.values],
                           "concepts": [c.model_dump() for c in run.concepts]}}


async def decide(root: Path, run_no: int, only: Optional[List[str]]) -> None:
    out_dir = root / "runs" / "decide" / f"run{run_no}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in load_sets(root, only):
        payload = await _decide_one(s)
        payload["score"] = score_decide(s, payload)
        (out_dir / f"{s['slug']}.json").write_text(json.dumps(payload, indent=1))
        print(s["slug"], json.dumps(payload["score"]))


FIELDS = {"decide": ["values_found", "values_total", "values_extra", "every_kept", "partial_carded", "concept_cells",
                     "concept_correct", "disagreements_found", "disagreements_total", "polarity_correct", "polarity_total",
                     "cards", "dropped_quotes"]}


def report(root: Path, stage: str) -> str:
    lines = [f"# Rules-step lab: {stage}", ""]
    for run_dir in sorted((root / "runs" / stage).glob("run*")):
        rows = [json.loads(p.read_text())["score"] for p in sorted(run_dir.glob("*.json"))]
        lines += [f"## {run_dir.name}", "", "| slug | kind | " + " | ".join(FIELDS[stage]) + " |",
                  "|---|---|" + "---|" * len(FIELDS[stage])]
        lines += [f"| {r['slug']} | {r['kind']} | " + " | ".join(str(r.get(f)) for f in FIELDS[stage]) + " |"
                  for r in rows]
        lines += ["", "Totals by kind (synthetic and real reported apart):", ""]
        for kind, agg in summarise(rows, FIELDS[stage]).items():
            lines.append(f"- {kind}: " + ", ".join(f"{k} {v}" for k, v in agg.items()))
        lines.append("")
    text = "\n".join(lines)
    (root / f"REPORT_{stage}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["decide", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--stage", dest="report_stage", default="decide")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "decide":
        asyncio.run(decide(a.root, a.run, only))
    else:
        print(report(a.root, a.report_stage))


if __name__ == "__main__":
    main()
