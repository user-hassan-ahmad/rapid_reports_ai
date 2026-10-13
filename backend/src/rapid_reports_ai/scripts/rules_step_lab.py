"""Rules-step lab (spec 2026-10-13-template-rules-step-design, "The lab for this spec"). Reported, not gated: it
prints tables and writes JSON under the private folder; Hassan decides.

    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab decide --root <dir> [--run 1|2] [--only slug,...]
    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab write --root <dir> [--run 1] [--arms A,B,C]
    .venv/bin/python -m rapid_reports_ai.scripts.rules_step_lab report --root <dir> --stage decide|write

<dir> is ~/Code/rr-template-conversion-private/synthetic/rules_step (never the repo). Sets: <dir>/sets/*.json (format
in the plan, Task 19). Outputs: <dir>/runs/<stage>/run<k>/<slug>.json and <dir>/REPORT_<stage>.md. The generator of
the synthetic sets (Claude) is never the model under test (Qwen, Jev)."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
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
            v = r.get(f)
            agg[f] += int(v) if isinstance(v, (bool, int)) else 0   # "n/a" and missing add nothing
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


# ── writer arms (Task 30): with and without the decisions, two temperatures ────────────────────────────────────
# Every arm uses the writer's next prompts (template_sheet_lab_prompts.analyser_system_prompt / writer_user_prompt:
# slot wording, no questions); A has no decisions. write_sheet keeps today's prompts until Task 31.

ARMS = {"A": (False, 0.8), "B": (True, 0.8), "C": (True, 0.4)}   # (decided, temperature)


NA = "n/a"
_NORMAL_LINE = re.compile(r"^\s*(?:-\s+)?NORMAL\b")


def _expected_concept(name: str, truth: dict, answers: List[dict]) -> dict:
    """{"default", "when_met", "condition"} the sheet should hold for a concept: the radiologist's used answer when
    there is one, else the set's planted truth (condition: the opposite of the usual state; "" when unknown)."""
    from rapid_reports_ai import template_decisions as td
    ans = next((a for a in reversed(answers or []) if a.get("kind") == "concept" and a.get("key") == name), None)
    if ans and (ans.get("choice") or {}).get("use"):
        try:
            return td.validate("concept", name, ans["choice"])[1]
        except td.DecisionError:
            pass
    t = (truth.get("concepts") or {}).get(name) or {}
    states = td.CONCEPTS[name].states
    usual = t.get("usual_state")
    other = next((st for st in states if st != usual), None) if usual in states else None
    return {"default": t.get("default") or "", "when_met": t.get("when_met") or "",
            "condition": states[other] or "" if other else ""}


def _concept_duplicates(st, truth: dict, answers: List[dict]) -> int:
    """Per concept, FIXED lines beyond one plus context rules beyond one. A concept's lines: the rules carrying its
    standard conditions, rules targeting one of its known wordings, and FIXED lines stating a known wording (the
    rules' targets and replacements, the truth's and the answers' wordings)."""
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from rapid_reports_ai.hybrid_stack.template import norm_key
    total = 0
    for name in td.CONCEPTS:
        rules = tla._concept_rules(st, name)
        exp = _expected_concept(name, truth, answers)
        t = (truth.get("concepts") or {}).get(name) or {}
        texts = {norm_key(x) for x in (*(r.target for r in rules), *(r.then_text for r in rules), exp["default"],
                                       exp["when_met"], t.get("default"), t.get("when_met")) if x}
        rules = [*rules, *(r for r in tla._targeting(st, texts) if r not in rules)]
        fixed = [f for f in st.fixed_blocks if norm_key(f.text) in texts]
        total += max(0, len(fixed) - 1) + max(0, len(rules) - 1)
    return total


def _contrast(st, truth: dict, answers: List[dict]) -> dict:
    """Present; condition right (the default's polarity); default wording right (n/a when no wording is known)."""
    from rapid_reports_ai import template_ledger_apply as tla
    from rapid_reports_ai.hybrid_stack.template import norm_key
    o = tla.observe(st, "concept", "contrast")
    exp = _expected_concept("contrast", truth, answers)
    if not exp["condition"]:
        return {"contrast_rule": int(o["use"]), "contrast_condition_ok": NA, "contrast_default_ok": NA}
    cond_ok = int(o["use"] and o["condition"] == exp["condition"])
    default_ok = NA if not exp["default"] else int(bool(o["use"]) and norm_key(o["default"]) == norm_key(exp["default"]))
    return {"contrast_rule": int(o["use"]), "contrast_condition_ok": cond_ok, "contrast_default_ok": default_ok}


def score_sheet(s: dict, sheet: str, gold: Optional[str] = None, answers: Optional[List[dict]] = None) -> dict:
    """One written sheet against the set's planted truth, the radiologist's answers (when given) and the curated
    production sheet (when given; else the truth's `normals` list, else n/a)."""
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from rapid_reports_ai import template_sheet_grammar as tsg
    from rapid_reports_ai.hybrid_stack.template import norm_key
    base = {"slug": s["slug"], "kind": s.get("kind", "base")}
    if not tsg.is_grammar_sheet(sheet or ""):
        return {**base, "usable": 0}
    st = tsg.parse_sheet(sheet, mode="template").structure
    truth = s.get("truth") or {}
    normals = [td._name(n.structure) for n in st.normals]
    items = {td._name(x) for r in st.rules if r.effect == "list_missing" for x in r.items}
    every = [v for v in truth.get("values", []) if v.get("need") == "every"]
    out = {**base, "usable": int(st.usable),
           "duplicate_normals": len(normals) - len(set(normals)),
           "multi_structure_normals": sum(1 for n in st.normals if re.search(r"\band\b|/|,", n.structure)),
           "patient_fixed_present": sum(1 for t in truth.get("patient_specific_fixed", [])
                                        if any(norm_key(f.text) == norm_key(t) for f in st.fixed_blocks)),
           "comparison_rule": int(tla.observe(st, "concept", "comparison")["use"]),
           "context_rules": sum(1 for r in st.rules if r.condition_source == "context"),
           "required_values_listed": sum(1 for v in every if items & _value_names(v)),
           "required_values_total": len(every),
           "extra_values_listed": sum(1 for x in items
                                      if not any(x in _value_names(v) for v in truth.get("values", []))),
           "concept_duplicates": _concept_duplicates(st, truth, answers or []),
           "normal_slots": sum(1 for ln in sheet.splitlines() if _NORMAL_LINE.match(ln) and "{" in ln),
           **_contrast(st, truth, answers or [])}
    if gold:
        gold_n = {td._name(n.structure) for n in tsg.parse_sheet(gold, mode="template").structure.normals}
        source = "gold"
    elif truth.get("normals"):
        gold_n, source = {td._name(td.structure_label(x)) for x in truth["normals"]}, "truth"
    else:
        gold_n, source = None, NA
    if gold_n is None:
        out.update(gold_normals_hit=NA, gold_normals_total=NA, normals_source=NA)
    else:
        out.update(gold_normals_hit=len(gold_n & set(normals)), gold_normals_total=len(gold_n), normals_source=source)
    return out


async def _write_one(s: dict, answers: List[dict], decided: bool, temperature: float) -> dict:
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_sheet_lab_prompts as P
    from rapid_reports_ai import template_sheet_model, template_sheet_save
    ledger = td.ledger_from_changes(answers, source="creation")[0] if decided else []
    ex = [{"label": "", "content": e} for e in s["examples"]]
    t0 = time.monotonic()
    raw = await template_sheet_model.model_call(
        P.analyser_system_prompt(decided),
        P.writer_user_prompt(ex, s.get("scan_type", ""), "", decisions=ledger or None),
        {**P.ANALYSER_SETTINGS, "temperature": temperature})
    ans = P.split_answer(raw)
    v = await template_sheet_save.vet_sheet(ans["skill_sheet"] or "", origin="analyser", ledger=ledger or None)
    return {"status": v.status, "sheet": v.sheet if v.status == "saved" else (ans["skill_sheet"] or ""),
            "drift": v.ledger_drift, "ms": int((time.monotonic() - t0) * 1000)}


async def write(root: Path, run_no: int, arms: List[str], only: Optional[List[str]], gold_dir: Path) -> None:
    for arm in arms:
        decided, temperature = ARMS[arm]
        out_dir = root / "runs" / "write" / f"run{run_no}" / arm
        out_dir.mkdir(parents=True, exist_ok=True)
        for s in load_sets(root, only):
            ans_path = root / "answers" / f"{s['slug']}.json"
            if decided and not ans_path.exists():
                continue
            answers = json.loads(ans_path.read_text()) if ans_path.exists() else []
            res = await _write_one(s, answers, decided, temperature)
            gold_path = gold_dir / f"{s.get('seed', '')}.final.md"
            res["score"] = {**score_sheet(s, res["sheet"], gold_path.read_text() if gold_path.exists() else None,
                                          answers=answers),
                            "arm": arm, "drift": res["drift"], "refused": int(res["status"] != "saved")}
            (out_dir / f"{s['slug']}.json").write_text(json.dumps(res, indent=1))
            print(arm, s["slug"], json.dumps(res["score"]))


FIELDS = {"decide": ["values_found", "values_total", "values_extra", "every_kept", "partial_carded", "concept_cells",
                     "concept_correct", "disagreements_found", "disagreements_total", "polarity_correct",
                     "polarity_total", "cards", "dropped_quotes"],
          "write": ["usable", "refused", "drift", "required_values_listed", "required_values_total",
                    "extra_values_listed", "patient_fixed_present", "comparison_rule", "contrast_rule",
                    "contrast_condition_ok", "contrast_default_ok", "context_rules", "concept_duplicates",
                    "duplicate_normals", "multi_structure_normals", "normal_slots", "gold_normals_hit",
                    "gold_normals_total", "normals_source"]}


def report(root: Path, stage: str) -> str:
    """Tables per run; totals by kind (writer: by arm and kind). Synthetic and real are reported apart."""
    lines = [f"# Rules-step lab: {stage}", ""]
    for run_dir in sorted((root / "runs" / stage).glob("run*")):
        rows = [json.loads(p.read_text())["score"] for p in sorted(run_dir.rglob("*.json"))]
        for r in rows:
            if r.get("arm"):
                r["kind"] = f"{r['arm']}:{r['kind'].split(':')[-1]}"
        lines += [f"## {run_dir.name}", "", "| slug | kind | " + " | ".join(FIELDS[stage]) + " |",
                  "|---|---|" + "---|" * len(FIELDS[stage])]
        lines += [f"| {r['slug']} | {r['kind']} | " + " | ".join(str(r.get(f, "")) for f in FIELDS[stage]) + " |"
                  for r in rows]
        lines += ["", "Totals by kind:", ""]
        for kind, agg in summarise(rows, FIELDS[stage]).items():
            lines.append(f"- {kind}: " + ", ".join(f"{k} {v}" for k, v in agg.items()))
        lines.append("")
    text = "\n".join(lines)
    (root / f"REPORT_{stage}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["decide", "write", "report"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--gold-dir", type=Path, default=Path.home() / "Code/rr-template-conversion-private/final")
    ap.add_argument("--stage", dest="report_stage", default="decide")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "decide":
        asyncio.run(decide(a.root, a.run, only))
    elif a.stage == "write":
        asyncio.run(write(a.root, a.run, [x for x in a.arms.split(",") if x], only, a.gold_dir))
    else:
        print(report(a.root, a.report_stage))


if __name__ == "__main__":
    main()
