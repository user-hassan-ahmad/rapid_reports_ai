"""Lab: end-to-end templated two-phase pipeline vs today's production template path (LAB ONLY).

    uv run python -m rapid_reports_ai.scripts.template_e2e_lab --sets ct_ap_acute
    uv run python -m rapid_reports_ai.scripts.template_e2e_lab --reuse-sheets <prev out dir>   # no analyser calls
    uv run python -m rapid_reports_ai.scripts.template_e2e_lab --sets ct_ap_acute --only ct_ap_acute-d1,ct_ap_acute-d3
    uv run python -m rapid_reports_ai.scripts.template_e2e_lab --rescore <prev out dir>        # no model calls

Per synthetic set (backend/tests/fixtures/sheet_lab/<set>/):
 1. Lean sheet: the lean analyser (template_sheet_lab_prompts) on examples/*.md, one lint-repair call when the
    parse has errors, parsed mode=template (must be usable; recorded when not).
 2. Per dictation: Phase 1 ``case_analyser.deliberate`` on the clinical history (no findings) -> merge_master
    -> parse mode=master (must be usable).
 3. Phase 2: ``compile_template_brief`` over the master sheet (real Jev / Qwen).
 4. Generate: ``_generate_report_skill_sheet_guided`` with the brief (history_supplied when the sheet defines a
    history-role section), the option writer beside it; the verbatim history inserted; post-generation check
    (sections from the lean structure, protected = history + FIXED texts, suppressed = TERM AVOID). A second
    check call on the final report counts the contradictions left after repair.
 5. QUICK (``--quick``; the clinical-content reference): the production quick pipeline exactly as quick_report_api
    runs it: generate_ephemeral_skill_sheet (FAST analyser, production directives) -> generate_quick_report
    (GENERATOR_MODEL, brief on, post-generation check on per RR_QUALITY_CHECK).
 6. Baseline (today's production template path): the production analyser on the same examples (once per set;
    retried once on its "No JSON object found" failure, every failed attempt recorded: a production exposure)
    -> the generator with the raw sheet, no brief, no check. One check call (no repair) counts its
    contradictions for a like-for-like score.

Scoring vs answer_key expected_per_dictation (text of the final report; heuristics, the hand read decides):
rules met / not met by effect (see ``score_rule``), expected omissions not asserted (per single finding of the
negative, negation governing the finding), missing items flagged, contradictions left, history n-grams outside
the history section, brief label words in the report, options stated vs offered.

Outputs to SCRATCH/e2e_<pid>/: <set>/<dictation>.md + .json, <set>/lean_sheet.md, <set>/baseline_sheet.md,
summary.md, summary.json, hand_read.md. ``--reuse-sheets`` reads <dir>/<set>/sheets.json, else its
lean_sheet.md / baseline_sheet.md; a missing or empty sheet is rebuilt. ``--reuse-reports <dir>`` takes the NEW
(and QUICK) arms of each dictation from <dir>/<set>/<id>.json (no model calls for those arms); ``--rerun new``
runs the named arms again while the others are reused. With ``--quick``,
negatives.md lists every negative clause stated in each report with its likely source.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")  # the lab never touches an app database

from rapid_reports_ai import case_analyser as ca  # noqa: E402
from rapid_reports_ai import report_reconcile as rc  # noqa: E402
from rapid_reports_ai import report_review as rr  # noqa: E402
from rapid_reports_ai import template_sheet_grammar as g  # noqa: E402

HERE = Path(__file__).resolve()
FIXTURES = HERE.parents[3] / "tests" / "fixtures" / "sheet_lab"
SCRATCH = Path("/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/"
               "9e672c4e-4eef-41cc-a40f-806516ac58ef/scratchpad")

STEP_TIMEOUT_S = 300  # a hung provider call is recorded as a failure, never stalls the run


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers for scoring
# ─────────────────────────────────────────────────────────────────────────────

_EXTRA_STOP = frozenset("mm cm ml".split())


def _w(text: str) -> set:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in g._content_words(text or "") if w not in _EXTRA_STOP}


def _clauses(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"(?<=[.;])\s+|\n+", text or "") if c.strip()]


def _parts(negative: str) -> List[str]:
    """A bundled negative split into its single findings."""
    body = re.sub(r"^\s*(?:there\s+is\s+|there\s+are\s+)?no\s+", "", negative.strip(), flags=re.I)
    parts = re.split(r",\s*|\s+or\s+|\s+and\s+no\s+|;\s*|\.\s+(?:no\s+)?", body)
    return [p.strip().rstrip(".;, ") for p in parts if _w(p)] or [negative]


_NEG_PREFIX = re.compile(r"\b(?:no|without|nil|negative\s+for|free\s+of)\b", re.I)
_NEG_POSTFIX = re.compile(r"\b(?:not\s+(?:seen|identified|demonstrated|present|evident)|(?:is|are)\s+absent|excluded)\b", re.I)


def _negated_span(clause: str) -> str:
    """The part of a clause a negation governs: after a prefix cue, or the whole clause for a postfix cue."""
    if _NEG_POSTFIX.search(clause):
        return clause
    m = _NEG_PREFIX.search(clause)
    return clause[m.end():] if m else ""


def asserted_parts(negative: str, text: str) -> List[dict]:
    """Single findings of `negative` that `text` asserts absent (every content word of the finding inside a
    negated span of one clause)."""
    hits = []
    for part in _parts(negative):
        pw = _w(part)
        for c in _clauses(text):
            if pw and pw <= _w(_negated_span(c)):
                hits.append({"part": part, "clause": c})
                break
    return hits


def present(text: str, report: str, thresh: float = 0.6) -> float:
    """Best per-clause containment of `text`'s content words (0..1); slots are ignored."""
    tw = _w(re.sub(r"\{[^}]*\}", " ", text or ""))
    if not tw:
        return 0.0
    best = 0.0
    cl = _clauses(report)
    for i in range(len(cl)):  # a clause, or two consecutive clauses (a sentence split by ';')
        for span in (cl[i], " ".join(cl[i:i + 2])):
            best = max(best, len(tw & _w(span)) / len(tw))
    return best


def split_sections(report: str, sections: List[dict]) -> Dict[str, str]:
    """{section name: text} by header lines (a line starting with the header, case-insensitive). Text before
    the first found header goes to "_pre"; implicit sections are not split out."""
    lines = report.splitlines()
    marks = []
    for s in sections:
        h = (s.get("header") or "").strip()
        if not h:
            continue
        for i, ln in enumerate(lines):
            if ln.strip().lower().lstrip("#* ").startswith(h.lower().rstrip(":")) and len(ln.strip()) <= len(h) + 400:
                marks.append((i, s["name"], h))
                break
    marks.sort()
    out = {"_pre": "\n".join(lines[: marks[0][0]] if marks else lines)}
    for k, (i, name, h) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        first = re.sub(r"^[#*\s]*" + re.escape(h.rstrip(":")) + r":?\**", "", lines[i].strip(), flags=re.I)
        out[name] = "\n".join([first] + lines[i + 1:end]).strip()
    return out


def without_history(report: str, sections: List[dict]) -> str:
    hist = [s["name"] for s in sections if s["role"] == "history"]
    parts = split_sections(report, sections)
    return "\n".join(v for k, v in parts.items() if k not in hist)


_LABELS = re.compile(r"\b(?:OMIT SECTION|RULE OMIT|OMIT|KEEP NORMAL|KEEP|ADDRESS|OPEN DIFFERENTIAL|OPEN|CLOSED|"
                     r"CLINICAL QUESTION|DO NOT ASSERT AS NORMAL|DO NOT ASSERT|DO NOT RECOMMEND|RECOMMEND|OFFERED|"
                     r"INSTEAD|APPLY|INSERT|USE|DESCRIBE FROM DICTATION|REMOVED|DIFFERENTIAL|TARGETS|IF_PRESENT|"
                     r"NEGATIVE|NORMAL|FIXED|COVERS)\b(?=\s*[:\[\"]|\s*$|\s+[A-Z])")


def label_leaks(report: str, sections: List[dict]) -> List[str]:
    headers = {(s.get("header") or "").strip().lower() for s in sections} | {s["name"].lower() for s in sections}
    out = []
    for ln in report.splitlines():
        t = ln.strip()
        if not t or t.lower().rstrip(":") in {h.rstrip(":") for h in headers}:
            continue
        for m in _LABELS.finditer(t):
            out.append(f"{m.group(0)} :: {t[:160]}")
    return out


_TOK = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_AGESEX = re.compile(r"\b\d{1,3}\s?(?:yo|y/o|year[- ]old)?\s?[MF]\b")


def history_leaks(history: str, findings: str, report_body: str) -> List[str]:
    """History 3-grams (>= 2 content words) found outside the history section and not in the dictation, plus
    an age/sex token. Candidates for the hand read, not verdicts."""
    ht = _TOK.findall(history.lower())
    body = " ".join(_TOK.findall(report_body.lower()))
    dict_ = " ".join(_TOK.findall(findings.lower()))
    out = []
    for i in range(len(ht) - 2):
        gram = ht[i:i + 3]
        if sum(1 for w in gram if w not in g._STOP) < 2:
            continue
        s = " ".join(gram)
        if f" {s} " in f" {body} " and f" {s} " not in f" {dict_} ":
            out.append(s)
    for m in _AGESEX.finditer(report_body):
        if m.group(0) in history:
            out.append(f"age/sex '{m.group(0)}'")
    return list(dict.fromkeys(out))


# ─────────────────────────────────────────────────────────────────────────────
# Rule scoring (planted findings/context rules -> visible effect in the final report)
# ─────────────────────────────────────────────────────────────────────────────

def _structure_words(key: dict, paragraph: str) -> set:
    words = _w(paragraph)
    for p in key["planted"]:
        if p["kind"] == "NORMAL" and p["paragraph"] == paragraph:
            m = re.match(r"NORMAL\s*\[([^\]]+)\]", p["grammar"])
            words |= _w(m.group(1)) if m else set()
    return words


def score_rule(p: dict, should_fire: bool, report: str, key: dict) -> Optional[bool]:
    """True when the report shows the expected state (fired when should_fire, not fired otherwise); None when
    the effect has no reliable text test in that direction."""
    eff = p.get("effect")
    body = without_history(report, key["sections"])
    target, then = p.get("target") or "", p.get("then_text") or p.get("text") or ""
    target_neg = bool(re.match(r"^\s*(?:no|there\s+is\s+no)\b", target, re.I))
    if eff == "replace":
        if target_neg:
            dropped = [x for x in _parts(target) if not (_w(x) <= _w(then))]
            if should_fire:
                return not any(asserted_parts(x, body) for x in dropped) if dropped else None
            return None
        return (present(then, body) >= 0.6) if should_fire else (present(then, body) < 0.6)
    if eff in ("append", "use", "insert_before"):
        sc = present(then, body)
        return sc >= 0.6 if should_fire else sc < 0.6
    if eff == "suppress":
        if target_neg:
            return (not asserted_parts(target, body)) if should_fire else None
        sc = present(target, body)
        return sc < 0.6 if should_fire else sc >= 0.6
    if eff in ("suppress_section", "suppress_headers"):
        name = p.get("target") or re.sub(r".*SUPPRESS_SECTION\s+", "", p["grammar"]).strip()
        sec = next((s for s in key["sections"] if s["name"] == name), None)
        if eff == "suppress_headers" or not sec or not sec.get("header"):
            return None
        shown = name in split_sections(report, key["sections"])
        return (not shown) if should_fire else shown
    if eff == "suppress_paragraph_negatives":
        if not should_fire:
            return None
        negs = [x["text"] or re.sub(r'^NEGATIVE\s+"|".*$', "", x["grammar"]) for x in key["planted"]
                if x["kind"] == "NEGATIVE" and x["paragraph"] == p["paragraph"] and not x.get("condition")]
        return not any(asserted_parts(n, body) for n in negs)
    if eff == "order":
        findings = [s["name"] for s in key["sections"] if s["role"] == "findings"]
        parts = split_sections(report, key["sections"])
        text = next((parts[n] for n in findings if n in parts), "")
        first = _clauses(text)[:1]
        hit = bool(first) and bool(_w(first[0]) & _structure_words(key, p["paragraph"]))
        return hit if should_fire else None
    if p["kind"] == "NEGATIVE":  # a conditional NEGATIVE planted as a rule-like expectation
        text = p.get("text") or re.sub(r'^NEGATIVE\s+"|".*$', "", p["grammar"])
        sc = present(text, body)
        return sc >= 0.6 if should_fire else sc < 0.6
    return None


def score_report(report: str, exp: dict, key: dict, history: str, findings: str) -> dict:
    planted = {p["id"]: p for p in key["planted"]}
    body = without_history(report, key["sections"])
    rules = {}
    for pid in exp["rules_met"]:
        if planted[pid].get("effect") == "list_missing":
            continue
        rules[pid] = {"expect": "met", "ok": score_rule(planted[pid], True, report, key)}
    for pid in exp["rules_not_met"]:
        if planted[pid].get("effect") == "list_missing":
            continue
        rules[pid] = {"expect": "not_met", "ok": score_rule(planted[pid], False, report, key)}
    omissions = []
    for n in exp["negatives_omitted"]:
        hits = asserted_parts(n, body)
        omissions.append({"negative": n, "honoured": not hits, "asserted": hits, "parts": len(_parts(n))})
    missing = []
    for item in exp.get("missing_items", []):
        lines = [ln for ln in report.splitlines() if item.lower() in ln.lower()]
        flagged = any(re.search(r"not\s+(?:stated|provided|given|available|reported|supplied)|missing|unavailable|"
                                r"not\s+dictated|\[", ln, re.I) for ln in lines)
        missing.append({"item": item, "flagged": flagged, "lines": lines[:2]})
    return {
        "rules": rules,
        "rules_scored": sum(1 for r in rules.values() if r["ok"] is not None),
        "rules_ok": sum(1 for r in rules.values() if r["ok"]),
        "omissions": omissions,
        "omissions_honoured": sum(o["honoured"] for o in omissions),
        "omissions_expected": len(omissions),
        "missing": missing,
        "missing_flagged": sum(m["flagged"] for m in missing),
        "label_leaks": label_leaks(report, key["sections"]),
        "history_leaks": history_leaks(history, findings, body),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline steps
# ─────────────────────────────────────────────────────────────────────────────

async def lean_sheet(examples: List[dict], scan_type: str) -> dict:
    from rapid_reports_ai.scripts import template_sheet_lab as lab

    rec: dict = {}
    t = time.time()
    try:
        parsed, rec["analyse_s"], raw = await lab.analyse(examples, scan_type)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:400], "analyse_s": round(time.time() - t, 1), "sheet": ""}
    sheet = parsed["skill_sheet"]
    rec["first_sheet"] = sheet
    _, errors = lab.parse(sheet)
    rec["first_errors"] = errors
    if errors:
        sheet, rec["repair_s"] = await lab.repair(sheet, errors)
        _, errors = lab.parse(sheet)
        rec["repair_errors"] = errors
    s = g.parse_sheet(sheet, mode="template").structure
    rec.update(sheet=sheet, usable=s.usable and not errors, final_errors=errors)
    return rec


async def baseline_sheet(examples: List[dict], scan_type: str) -> dict:
    from rapid_reports_ai.template_manager import TemplateManager

    failures: List[dict] = []
    for attempt in range(2):  # LAB ONLY: one retry, and only on the unparseable-response failure
        t = time.time()
        try:
            out = await TemplateManager().analyze_examples_to_skill_sheet(
                [{"content": e["content"]} for e in examples], scan_type, api_key="")
            return {"sheet": out["skill_sheet"], "analyse_s": round(time.time() - t, 1), "failed_attempts": failures}
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            failures.append({"error": msg[:300], "tail": msg[-300:], "len": len(msg), "s": round(time.time() - t, 1)})
            if attempt or not is_no_json_failure(msg):
                break
    return {"error": failures[-1]["error"], "failed_attempts": failures, "sheet": ""}


def is_no_json_failure(msg: str) -> bool:
    """The production analyser's 'No JSON object found' failure (the one the lab retries)."""
    return "No JSON object found" in msg


def first_with(dirs: str, name: str) -> Optional[Path]:
    """The first of comma-separated output dirs holding <set> (so one run can reuse several earlier runs)."""
    return next((Path(x.strip()) for x in (dirs or "").split(",") if x.strip() and (Path(x.strip()) / name).exists()),
                None)


def reused_sheets(reuse: Optional[Path], name: str) -> dict:
    """Saved sheets of a previous run: sheets.json, else lean_sheet.md / baseline_sheet.md. Empty when none."""
    if not reuse:
        return {}
    d = reuse / name
    if (d / "sheets.json").exists():
        return json.loads((d / "sheets.json").read_text())
    out: dict = {}
    for arm, fn in (("lean", "lean_sheet.md"), ("baseline", "baseline_sheet.md")):
        if (d / fn).exists() and (d / fn).read_text().strip():
            out[arm] = {"sheet": (d / fn).read_text(), "reused_file": str(d / fn)}
            if arm == "lean":
                out[arm]["usable"] = g.parse_sheet(out[arm]["sheet"], mode="template").structure.usable
    return out


def _section_block(sheet: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$([\s\S]*?)(?=^##\s|\Z)", sheet, re.M | re.I)
    return m.group(1).strip() if m else ""


async def run_new(sheet: str, d: dict) -> dict:
    """Phase 1 -> master -> brief -> generator (+ options, history) -> post-generation check."""
    from rapid_reports_ai.template_brief import compile_template_brief
    from rapid_reports_ai.template_history import insert_history, write_history
    from rapid_reports_ai.template_manager import TemplateManager
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    rec: dict = {"lat": {}}
    scan_type, history, findings = d["scan_type"], d.get("clinical_history", ""), d["findings"]
    lean = g.parse_sheet(sheet, mode="template").structure
    sections = [rr.ReportSection(name=x.name, header=x.header, role=x.role)
                for x in sorted(lean.sections, key=lambda x: x.order)]
    hist_sec = next((x for x in sections if x.role == "history"), None)
    imp = next((x.name for x in sections if x.role == "impression"), "IMPRESSION")

    # Phase 1
    summary = ca.summarise_template(sheet)
    res = await ca.deliberate(sheet, summary, scan_type, history)
    rec["lat"]["phase1_s"] = round(res.ms / 1000, 1)
    master = ca.merge_master(sheet, res)
    mres = g.parse_sheet(master, mode="master")
    rec["phase1"] = {"usable": res.usable, "errors": res.errors, "model": res.model, "question": res.question,
                     "differentials": res.differentials, "recommendations": res.recommendations,
                     "placements": [p.line if hasattr(p, "line") else str(p) for p in res.placements],
                     "placement_paragraphs": [getattr(p, "paragraph", "") for p in res.placements],
                     "rejected": res.rejected, "raw": res.raw}
    rec["master_usable"] = mres.structure.usable
    rec["master_errors"] = [f"{e.line}: {e.reason}: {e.text[:100]}" for e in mres.errors]
    rec["master_sheet"] = master
    brief_sheet, brief_struct = (master, mres.structure) if mres.structure.usable else (sheet, lean)

    # Phase 2 brief
    t = time.time()
    brief = None
    try:
        brief = await compile_template_brief(brief_sheet, brief_struct, scan_type, findings, history)
    except Exception as e:  # noqa: BLE001 - production generates down the raw path
        rec["brief_error"] = f"{type(e).__name__}: {e}"[:400]
    rec["lat"]["brief_s"] = round(time.time() - t, 2)
    rec["brief_text"] = brief.text if brief else None
    rec["decisions"] = brief.decisions if brief else None

    # Generate + options in parallel (as quick)
    style = "\n".join(x for x in (_section_block(sheet, "Impression Construction"),
                                  "\n".join(re.findall(r"^TERM .*$", sheet, re.M))) if x)

    async def gen():
        t0 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history},
            brief_text=brief.text if brief else None, history_supplied=hist_sec is not None)
        return out, round(time.time() - t0, 1)

    async def opts():
        t0 = time.time()
        o = await rc.write_options(brief.decisions.get("options", []) if brief else [], findings, scan_type,
                                   model=MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"], runner=_run_agent_with_model,
                                   style=style, impression_section=imp, require_service=True)
        return o, round(time.time() - t0, 1)

    (out, rec["lat"]["generator_s"]), (options, rec["lat"]["options_s"]) = await asyncio.gather(gen(), opts())
    report = out["report_content"]
    rec["generator_model"] = out.get("model_used")
    rec["report_generated"] = report
    hist_text = ""
    if hist_sec is not None:
        h = await write_history(history)
        if h:
            hist_text = h[0]
            report = insert_history(report, hist_text, sections)
    fixed = [f.text for f in lean.fixed_blocks if "{" not in f.text]
    protected = [x for x in [hist_text] + fixed if x]
    avoid = list(lean.terminology.suppressed)
    sec_dicts = [{"name": x.name, "header": x.header, "role": x.role} for x in sections]
    impression = split_sections(report, sec_dicts).get(imp, "")

    gate_qs = rc.gate_questions(options)  # report-scope questions ride on the check's report-state request

    async def checked():
        t0 = time.time()
        out = await rr.run_quality_check(report, findings, scan_type, options, sections=sections,
                                         protected=protected, suppressed=avoid, extra_report_qs=gate_qs["report"])
        return out, round(time.time() - t0, 1)

    async def gated():  # impression-scope questions need the conclusion as state: one parallel request
        t0 = time.time()
        out = await rc.gate_scores(f"CONCLUSION:\n{impression}", gate_qs["impression"])
        return out, round(time.time() - t0, 2)

    ((report, checked_opts, quality), rec["lat"]["check_s"]), (imp_scores, rec["lat"]["gate_s"]) = \
        await asyncio.gather(checked(), gated())
    _, gate_dropped = rc.gate_apply(options, {**quality.get("extra_answers", {}), **imp_scores})
    drop_ids = {o.get("id") for o in gate_dropped}
    options = [o for o in checked_opts if o.get("id") not in drop_ids]
    rec["jev_calls"] = {"check": 2, "gate_extra": 1 if gate_qs["impression"] else 0}
    rec["quality"] = quality
    rec["gate_dropped"] = gate_dropped
    rec["options"] = options
    rec["report"] = report
    rec["protected"] = protected
    return rec


async def run_baseline(sheet: str, d: dict) -> dict:
    from rapid_reports_ai.template_manager import TemplateManager

    t = time.time()
    out = await TemplateManager()._generate_report_skill_sheet_guided(
        template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": d["scan_type"]},
        user_inputs={"FINDINGS": d["findings"], "CLINICAL_HISTORY": d.get("clinical_history", "")})
    return {"report": out["report_content"], "generator_s": round(time.time() - t, 1), "model": out.get("model_used")}


def _md_section(sheet: str, title: str) -> str:
    """A '## <title>' block of a quick sheet, up to the next '## ' heading."""
    m = re.search(rf"^##\s+{re.escape(title)}[^\n]*\n([\s\S]*?)(?=^##\s|\Z)", sheet or "", re.M | re.I)
    return m.group(1).strip() if m else ""


async def run_quick(d: dict) -> dict:
    """The production quick pipeline, as quick_report_api runs it (analyser, then generator with brief + check)."""
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG
    from rapid_reports_ai.quick_report_analyser import generate_ephemeral_skill_sheet
    from rapid_reports_ai.quick_report_generator import generate_quick_report

    rec: dict = {"lat": {}}
    t = time.time()
    a = await generate_ephemeral_skill_sheet(scan_type=d["scan_type"], clinical_history=d.get("clinical_history", ""),
                                             api_key="", model_override=MODEL_CONFIG["QUICK_REPORT_ANALYZER_FAST"])
    rec["lat"]["analyser_s"] = round(time.time() - t, 1)
    sheet = a.get("skill_sheet", "")
    rec.update(sheet=sheet, analyser_model=a.get("model_used"), matrix=_md_section(sheet, "Companion Matrix"))
    t = time.time()
    gen_model = MODEL_CONFIG["QUICK_REPORT_GENERATOR"]
    out = await generate_quick_report(skill_sheet=sheet, scan_type=d["scan_type"], findings=d["findings"],
                                      clinical_history=d.get("clinical_history", ""), model_override=gen_model)
    rec["lat"]["generator_s"] = round(time.time() - t, 1)
    rec.update(report=out.get("report_content", ""), generator_model=out.get("model_used"),
               brief_used=out.get("brief_used"), brief_text=out.get("brief_text"),
               decisions=out.get("brief_decisions"), options=out.get("brief_options") or [],
               quality=out.get("quality_check"))
    return rec


async def contradictions_left(report: str, d: dict, key: dict, options: List[dict], protected=None) -> dict:
    """One check call (no repair) on a final report: the contradiction flags it still raises."""
    secs = [rr.ReportSection(name=s["name"], header=s.get("header"), role=s["role"]) for s in key["sections"]]
    try:
        res = await asyncio.wait_for(rr.check(report, d["findings"], d["scan_type"], options, sections=secs,
                                              protected=protected), 60)
        return {"contradictions": [f.text for f in res.flags if f.kind == "contradiction"],
                "omissions": [f.text for f in res.flags if f.kind == "omission"], "error": res.error}
    except Exception as e:  # noqa: BLE001
        return {"contradictions": [], "omissions": [], "error": f"{type(e).__name__}: {e}"[:200]}


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def _examples(name: str) -> List[dict]:
    return [{"report_id": f.name, "content": f.read_text()} for f in sorted((FIXTURES / name / "examples").glob("*.md"))]


async def run_set(name: str, out: Path, sem: asyncio.Semaphore, reuse: Optional[Path],
                  only: Optional[set] = None, reuse_reports: Optional[Path] = None, quick: bool = False,
                  rerun: Optional[set] = None) -> dict:
    key = json.loads((FIXTURES / name / "answer_key.json").read_text())
    dictations = [d for d in json.loads((FIXTURES / name / "dictations.json").read_text())
                  if not only or d["id"] in only]
    expected = {e["dictation_id"]: e for e in key["expected_per_dictation"]}
    d_out = out / name
    d_out.mkdir(parents=True, exist_ok=True)
    examples = _examples(name)
    setrec: dict = {"set": name, "scan_type": key["scan_type"]}

    prev = reused_sheets(reuse, name)
    sheets = {"reused_from": str(reuse) if prev else None}
    if (prev.get("lean") or {}).get("sheet"):  # a sheet that exists is reused; a failed one is rebuilt
        sheets["lean"] = prev["lean"]
    else:
        async with sem:
            log(f"[{name}] lean analyser")
            sheets["lean"] = await lean_sheet(examples, key["scan_type"])
    if (prev.get("baseline") or {}).get("sheet"):
        sheets["baseline"] = prev["baseline"]
    else:
        async with sem:
            log(f"[{name}] production analyser (baseline)")
            sheets["baseline"] = await baseline_sheet(examples, key["scan_type"])
    (d_out / "sheets.json").write_text(json.dumps(sheets, indent=1, default=str))
    lean, base = sheets["lean"], sheets["baseline"]
    (d_out / "lean_sheet.md").write_text(lean.get("sheet", ""))
    (d_out / "baseline_sheet.md").write_text(base.get("sheet", ""))
    setrec["lean"] = {k: v for k, v in lean.items() if k not in ("sheet", "first_sheet")}
    setrec["baseline_sheet"] = {k: v for k, v in base.items() if k != "sheet"}

    async def one(d: dict) -> dict:
        rec: dict = {"id": d["id"], "history": d.get("clinical_history", ""), "findings": d["findings"],
                     "scan_type": d["scan_type"]}
        prev_rec = reuse_reports / name / f"{d['id']}.json" if reuse_reports else None
        if prev_rec and prev_rec.exists():
            old = json.loads(prev_rec.read_text())
            for arm in ("new", "quick", "baseline"):
                if arm not in (rerun or set()) and (old.get(arm) or {}).get("report"):
                    rec[arm] = {k: v for k, v in old[arm].items() if k != "score"}
                    rec[arm]["reused_from"] = str(prev_rec)
        if quick and "quick" not in rec:
            async with sem:
                log(f"[{name}] {d['id']} quick pipeline")
                try:
                    rec["quick"] = await asyncio.wait_for(run_quick(d), STEP_TIMEOUT_S)
                except Exception as e:  # noqa: BLE001
                    rec["quick"] = {"error": f"{type(e).__name__}: {e}"[:500]}
        if "new" not in rec or "baseline" not in rec:
            await run_new_and_baseline(rec, d)
        (d_out / f"{d['id']}.json").write_text(json.dumps(rec, indent=1, default=str))
        return rec

    async def run_new_and_baseline(rec: dict, d: dict) -> None:
        if "new" not in rec:
            await run_new_arm(rec, d)
        if "baseline" not in rec:
            await run_baseline_arm(rec, d)

    async def run_new_arm(rec: dict, d: dict) -> None:
        async with sem:
            log(f"[{name}] {d['id']} new pipeline")
            if lean.get("sheet") and g.parse_sheet(lean["sheet"], mode="template").structure.usable:
                try:
                    rec["new"] = await asyncio.wait_for(run_new(lean["sheet"], d), STEP_TIMEOUT_S)
                except Exception as e:  # noqa: BLE001
                    rec["new"] = {"error": f"{type(e).__name__}: {e}"[:500]}
                    log(f"!! {d['id']} new: {rec['new']['error'][:200]}")
            else:
                rec["new"] = {"error": "lean sheet unusable"}
        if rec["new"].get("report"):
            rec["new"]["left"] = await contradictions_left(rec["new"]["report"], d, key, rec["new"].get("options", []),
                                                           rec["new"].get("protected") or None)

    async def run_baseline_arm(rec: dict, d: dict) -> None:
        async with sem:
            log(f"[{name}] {d['id']} baseline")
            if base.get("sheet"):
                try:
                    rec["baseline"] = await asyncio.wait_for(run_baseline(base["sheet"], d), STEP_TIMEOUT_S)
                except Exception as e:  # noqa: BLE001
                    rec["baseline"] = {"error": f"{type(e).__name__}: {e}"[:500]}
            else:
                rec["baseline"] = {"error": "baseline sheet failed"}
        if rec["baseline"].get("report"):  # contradictions left (one check call, no repair)
            rec["baseline"]["left"] = await contradictions_left(rec["baseline"]["report"], d, key, [])

    recs = await asyncio.gather(*(one(d) for d in dictations))
    setrec["dictations"] = recs
    return setrec


def score_all(results: List[dict]) -> None:
    for s in results:
        key = json.loads((FIXTURES / s["set"] / "answer_key.json").read_text())
        exp = {e["dictation_id"]: e for e in key["expected_per_dictation"]}
        for r in s["dictations"]:
            for arm in ("new", "quick", "baseline"):
                a = r.get(arm) or {}
                if a.get("report") and r["id"] in exp:
                    a["score"] = score_report(a["report"], exp[r["id"]], key, r["history"], r["findings"])


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

def _opt_counts(new: dict) -> dict:
    dec = new.get("decisions") or {}
    recs = Counter(x.get("action") for x in dec.get("recommendations", []))
    fneg = Counter(x.get("qwen") or x.get("label") for x in dec.get("finding_negatives", []))
    return {"recommendations": dict(recs), "finding_negatives": dict(fneg),
            "offered_written": len(new.get("options") or []),
            "offered_by_kind": dict(Counter(o.get("kind") for o in new.get("options") or []))}


def _decisions_summary(dec: Optional[dict]) -> List[str]:
    if not dec:
        return ["(no brief: raw path)"]
    L = [f"- CLINICAL QUESTION: {dec.get('question') or '-'}"]
    for x in dec.get("differentials", []):
        L.append(f"- differential [{x.get('name')}] visible {x.get('visible')} -> {x.get('action') or x.get('route')}")
    acts = Counter(x.get("action") for x in dec.get("negatives", []))
    L.append(f"- negatives: {dict(acts)}")
    for x in dec.get("negatives", []):
        if any("OMIT" in ln or "DO NOT ASSERT" in ln for ln in x.get("lines", [])) or x.get("action") in (
                "removed", "section_omitted", "differential_present"):
            L.append(f"  - {x.get('origin')}: \"{x.get('text')}\" -> {x.get('action')}")
    nacts = Counter(x.get("action") for x in dec.get("normals", []))
    L.append(f"- normals: {dict(nacts)}")
    for x in dec.get("finding_negatives", []):
        L.append(f"- if-present [{x.get('finding')}] \"{x.get('text')}\" -> {x.get('qwen')}"
                 + (f" (denies {x['differential']})" if x.get("differential") else ""))
    for x in dec.get("recommendations", []):
        L.append(f"- recommendation {x.get('tag')} \"{x.get('text')}\" -> {x.get('action')}")
    for x in dec.get("rules", []):
        if x.get("met"):
            L.append(f"- rule met: {x.get('condition', '')[:100]} -> {x.get('action', '')}")
    for x in dec.get("missing", []):
        L.append(f"- missing items: {x.get('missing')}")
    for x in dec.get("conflicts", []):
        L.append(f"- conflict: \"{x.get('text')}\" winner {x.get('winner')} ({x.get('differential', '')})")
    return L


def _score_lines(sc: Optional[dict]) -> List[str]:
    if not sc:
        return ["(no report)"]
    L = [f"- rules: {sc['rules_ok']}/{sc['rules_scored']} scored ok ({len(sc['rules'])} expected; "
         f"{len(sc['rules']) - sc['rules_scored']} not text-scorable)"]
    for pid, r in sc["rules"].items():
        L.append(f"  - {pid} expect {r['expect']}: {'ok' if r['ok'] else ('n/a' if r['ok'] is None else 'MISS')}")
    L.append(f"- expected omissions honoured: {sc['omissions_honoured']}/{sc['omissions_expected']}")
    for o in sc["omissions"]:
        if not o["honoured"]:
            L.append(f"  - ASSERTED \"{o['negative']}\": " + "; ".join(f"[{h['part']}] in \"{h['clause'][:120]}\""
                                                                      for h in o["asserted"]))
    if sc["missing"]:
        L.append(f"- missing items flagged: {sc['missing_flagged']}/{len(sc['missing'])}")
    L.append(f"- label leaks: {sc['label_leaks'] or 'none'}")
    L.append(f"- history n-grams outside history section: {sc['history_leaks'] or 'none'}")
    return L


def render_dictation(r: dict) -> str:
    new, base = r.get("new") or {}, r.get("baseline") or {}
    L = [f"# {r['id']} — {r['scan_type']}", "", "## Dictation", f"**Clinical history:** {r['history']}", "",
         f"**Findings:** {r['findings']}", ""]
    p1 = new.get("phase1") or {}
    L += ["## Phase 1 deliberation", f"- usable {p1.get('usable')}, master usable {new.get('master_usable')}, "
          f"{new.get('lat', {}).get('phase1_s')} s", f"- QUESTION: {p1.get('question')}"]
    for x in p1.get("differentials", []):
        L.append(f"- DIFFERENTIAL [{x['name']}] {x['tier']} VISIBLE {x['visible']} — {x['discriminator']}")
    for x in p1.get("recommendations", []):
        L.append(f"- RECOMMEND {x['tag']} \"{x['text']}\" WHEN [{x['when']}]")
    for para, line in zip(p1.get("placement_paragraphs", []), p1.get("placements", [])):
        L.append(f"- PLACE [{para}] {line}")
    for line, why in p1.get("rejected", []):
        L.append(f"- rejected ({why}): {line[:160]}")
    if new.get("master_errors"):
        L.append(f"- master lint: {new['master_errors']}")
    L += ["", "## Brief decisions"] + ([f"- BRIEF ERROR: {new['brief_error']}"] if new.get("brief_error") else [])
    L += _decisions_summary(new.get("decisions"))
    L += ["", "## NEW report (two-phase)", "```", new.get("report") or f"ERROR: {new.get('error')}", "```", "",
          "## BASELINE report (production path)", "```", base.get("report") or f"ERROR: {base.get('error')}", "```", ""]
    L += ["## Options offered (NEW)"]
    for o in new.get("options") or []:
        L.append(f"- [{o.get('kind')} → {o.get('section')}] {o.get('sentence')}")
    if not new.get("options"):
        L.append("- none")
    for o in new.get("gate_dropped") or []:
        L.append(f"- GATE DROPPED ({o.get('score')}): [{o.get('kind')}] {o.get('sentence')}")
    q = new.get("quality") or {}
    L += ["", "## Post-generation check (NEW)", f"- flags: {[(f['kind'], f['text'][:100]) for f in q.get('flags', [])]}",
          f"- clauses removed {q.get('clauses_removed')}, edits applied {q.get('edits_applied')}, "
          f"options dropped {q.get('options_dropped')}",
          f"- contradictions left after repair: {(new.get('left') or {}).get('contradictions')}",
          f"- BASELINE contradictions (check, no repair): {(base.get('left') or {}).get('contradictions')}"]
    L += ["", "## Scores — NEW"] + _score_lines(new.get("score")) + ["", "## Scores — BASELINE"] + _score_lines(base.get("score"))
    L += ["", f"Latency NEW: {new.get('lat')}; BASELINE generator {base.get('generator_s')} s"]
    return "\n".join(L) + "\n"


def _agg(recs: List[dict], arm: str) -> dict:
    sc = [r[arm]["score"] for r in recs if (r.get(arm) or {}).get("score")]
    left = [len(((r.get(arm) or {}).get("left") or {}).get("contradictions", [])) for r in recs if (r.get(arm) or {}).get("left")]
    return {"reports": len(sc), "rules_ok": sum(s["rules_ok"] for s in sc), "rules_scored": sum(s["rules_scored"] for s in sc),
            "rules_expected": sum(len(s["rules"]) for s in sc),
            "omit_ok": sum(s["omissions_honoured"] for s in sc), "omit_exp": sum(s["omissions_expected"] for s in sc),
            "missing_ok": sum(s["missing_flagged"] for s in sc), "missing_exp": sum(len(s["missing"]) for s in sc),
            "contradictions_left": sum(left), "label_leak_reports": sum(1 for s in sc if s["label_leaks"]),
            "history_leak_reports": sum(1 for s in sc if s["history_leaks"])}


def _pct(vals: List[float]) -> str:
    v = sorted(x for x in vals if x is not None)
    if not v:
        return "-"
    med = v[len(v) // 2]
    return f"median {med:.1f} / max {v[-1]:.1f} (n={len(v)})"


def render_summary(results: List[dict]) -> str:
    L = ["# Templated two-phase pipeline — end-to-end lab", "",
         "Scores are text heuristics against the answer keys; the hand read is authoritative.", "",
         "| set | arm | reports | expected omissions honoured | rules ok/scored (expected) | missing items flagged | "
         "contradictions left | reports with label leaks | reports with history n-grams |",
         "|---|---|---|---|---|---|---|---|---|"]
    allrecs = []
    for s in results:
        allrecs += s["dictations"]
        for arm in ("new", "quick", "baseline"):
            a = _agg(s["dictations"], arm)
            if not a["reports"]:
                continue
            L.append(f"| {s['set']} | {arm} | {a['reports']} | {a['omit_ok']}/{a['omit_exp']} | {a['rules_ok']}/{a['rules_scored']} "
                     f"({a['rules_expected']}) | {a['missing_ok']}/{a['missing_exp']} | {a['contradictions_left']} | "
                     f"{a['label_leak_reports']} | {a['history_leak_reports']} |")
    for arm in ("new", "quick", "baseline"):
        a = _agg(allrecs, arm)
        if not a["reports"]:
            continue
        L.append(f"| **all** | {arm} | {a['reports']} | {a['omit_ok']}/{a['omit_exp']} | {a['rules_ok']}/{a['rules_scored']} "
                 f"({a['rules_expected']}) | {a['missing_ok']}/{a['missing_exp']} | {a['contradictions_left']} | "
                 f"{a['label_leak_reports']} | {a['history_leak_reports']} |")
    L += ["", "## Per dictation", "",
          "| dictation | NEW omit | BASE omit | NEW rules | BASE rules | NEW contra left | BASE contra | NEW flags (pre-repair) | offered | recs (actions) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in allrecs:
        n, b = r.get("new") or {}, r.get("baseline") or {}
        ns, bs = n.get("score") or {}, b.get("score") or {}
        oc = _opt_counts(n)
        L.append(f"| {r['id']} | {ns.get('omissions_honoured', '-')}/{ns.get('omissions_expected', '-')} | "
                 f"{bs.get('omissions_honoured', '-')}/{bs.get('omissions_expected', '-')} | "
                 f"{ns.get('rules_ok', '-')}/{ns.get('rules_scored', '-')} | {bs.get('rules_ok', '-')}/{bs.get('rules_scored', '-')} | "
                 f"{len((n.get('left') or {}).get('contradictions', []))} | {len((b.get('left') or {}).get('contradictions', []))} | "
                 f"{len((n.get('quality') or {}).get('flags', []))} | {oc['offered_written']} | {oc['recommendations']} |")
    L += ["", "## Latency (seconds)", ""]
    lat = lambda k: [((r.get("new") or {}).get("lat") or {}).get(k) for r in allrecs]  # noqa: E731
    for k in ("phase1_s", "brief_s", "generator_s", "options_s", "check_s"):
        L.append(f"- NEW {k}: {_pct(lat(k))}")
    L.append(f"- BASELINE generator_s: {_pct([(r.get('baseline') or {}).get('generator_s') for r in allrecs])}")
    for s in results:
        L.append(f"- {s['set']}: lean analyser {s['lean'].get('analyse_s')} s (+repair {s['lean'].get('repair_s', 0)} s), "
                 f"production analyser {s['baseline_sheet'].get('analyse_s')} s")
    L += ["", "## Failures", ""]
    for s in results:
        if s["lean"].get("error") or not s["lean"].get("usable"):
            L.append(f"- {s['set']}: lean sheet {'ERROR ' + s['lean']['error'] if s['lean'].get('error') else 'unusable'}: "
                     f"{s['lean'].get('final_errors')}")
        if s["lean"].get("first_errors"):
            L.append(f"- {s['set']}: lean first-pass lint {len(s['lean']['first_errors'])} errors -> repair -> "
                     f"{len(s['lean'].get('repair_errors') or [])}: "
                     + "; ".join(f"{e.get('reason')}" for e in s["lean"]["first_errors"][:6]))
        fa = s["baseline_sheet"].get("failed_attempts") or []
        if fa:
            L.append(f"- {s['set']}: production analyser failed attempts: {len(fa)} "
                     f"({sum(is_no_json_failure(f['error']) for f in fa)} 'No JSON object found')")
        for f in fa:
            L.append(f"- {s['set']}: production analyser attempt failed ({f['s']} s): {f['error'][:160]}")
        for r in s["dictations"]:
            n = r.get("new") or {}
            for what in ("error", "brief_error"):
                if n.get(what):
                    L.append(f"- {r['id']} NEW {what}: {n[what]}")
            if n.get("phase1") and not n["phase1"].get("usable"):
                L.append(f"- {r['id']} Phase 1 unusable: {n['phase1'].get('errors')}")
            if n.get("phase1") and not n.get("master_usable"):
                L.append(f"- {r['id']} master sheet unusable: {n.get('master_errors')}")
            if (r.get("baseline") or {}).get("error"):
                L.append(f"- {r['id']} BASELINE error: {r['baseline']['error']}")
    return "\n".join(L) + "\n"


def _esc(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_hand_read(results: List[dict]) -> str:
    L = ["# Hand read — NEW (two-phase) vs BASELINE (today's template path)", "",
         "Each case: the dictation, then the two finished reports side by side. NEW = lean template sheet + per-case "
         "Phase 1 clinical layer + brief + post-generation check; BASELINE = production analyser sheet straight into "
         "the generator. The options listed under NEW are offered to the reporter, not in the report.", ""]
    for s in results:
        L += [f"## {s['set']} — {s['scan_type']}", ""]
        for r in s["dictations"]:
            n, b = r.get("new") or {}, r.get("baseline") or {}
            arms = [("NEW", n)] + ([("QUICK", r["quick"])] if r.get("quick") else []) + [("BASELINE", b)]
            w = 100 // len(arms)
            L += [f"### {r['id']}", "", f"**History:** {r['history']}", "", f"**Findings:** {r['findings']}", "",
                  "<table><tr>" + "".join(f'<th width="{w}%">{lab_}</th>' for lab_, _ in arms) + "</tr><tr>"]
            L += [f'<td valign="top"><pre style="white-space:pre-wrap">{_esc(a.get("report") or "ERROR: " + str(a.get("error")))}</pre></td>'
                  for _, a in arms]
            L += ["</tr></table>", ""]
            if n.get("options"):
                L.append("NEW options offered: " + " | ".join(f"[{o.get('kind')}] {o.get('sentence')}" for o in n["options"]))
                L.append("")
            if (r.get("quick") or {}).get("options"):
                L.append("QUICK options offered: " + " | ".join(f"[{o.get('kind')}] {o.get('sentence') or o.get('text')}"
                                                               for o in r["quick"]["options"]))
                L.append("")
    return "\n".join(L) + "\n"


_NEG_CUE = re.compile(r"\b(?:no|not|without|nil|absent|unremarkable|normal)\b", re.I)


def negative_clauses(report: str, sections: List[dict]) -> List[str]:
    """Clauses outside the history section that state an absence (a 'no'/'without'/'not seen' negation)."""
    body = without_history(report, sections)
    return [c for c in _clauses(body) if _negated_span(c) and not re.match(r"^\d+\.?$", c)]


def _source_texts(arm: str, a: dict) -> Dict[str, List[str]]:
    """{source label: [negative texts]} the arm's brief or sheet supplied."""
    dec = a.get("decisions") or {}
    out: Dict[str, List[str]] = {}
    if arm == "new":
        for n in dec.get("negatives", []):
            out.setdefault("case negative (Phase 1)" if n.get("origin") == "case" else "template sweep negative",
                           []).append(n.get("text", ""))
        for n in dec.get("finding_negatives", []):
            out.setdefault("case If-present (Phase 1)", []).append(n.get("text", ""))
        for n in dec.get("normals", []):
            out.setdefault("template normal", []).append(n.get("text", "") or "")
    elif arm == "quick":
        for n in dec.get("negatives", []):
            src = n.get("source", "sheet")
            out.setdefault("quick finding-linked negative" if src.startswith("finding:") else
                           "quick sheet mandatory negative", []).append(n.get("text", ""))
        for n in dec.get("finding_negatives", []):
            out.setdefault("quick finding-linked negative", []).append(n.get("text", ""))
    return out


def classify_negative(clause: str, findings: str, sources: Dict[str, List[str]]) -> str:
    """Likely source of a stated negative: dictated (its negated words all sit in a negated dictation clause),
    else the brief/sheet source with the best word overlap, else 'unsourced'. A heuristic for the hand read."""
    cw = _w(_negated_span(clause)) or _w(clause)
    for dc in _clauses(findings.replace(",", ".")):
        span = _w(_negated_span(dc))
        if span and cw and len(cw & span) / len(cw) >= 0.6:
            return "dictated"
    best, label = 0.0, "unsourced (generator)"
    for lab_, texts in sources.items():
        for t in texts:
            tw = _w(t)
            if tw and cw:
                sc = len(cw & tw) / len(cw | tw)
                if sc > best:
                    best, label = sc, lab_
    return label if best >= 0.34 else "unsourced (generator)"


def beside_positive(clause: str, findings: str) -> List[str]:
    """Dictated POSITIVE clauses sharing a content word with what this negative denies (e.g. fluid / fluid)."""
    cw = _w(_negated_span(clause))
    hits = []
    for dc in _clauses(findings.replace(",", ".")):
        pos = _w(dc) - _w(_negated_span(dc))
        common = cw & pos
        if common:
            hits.append(f"{'/'.join(sorted(common))} ← \"{dc[:70]}\"")
    return hits


def render_negatives(results: List[dict]) -> str:
    L = ["# Stated negatives — NEW / QUICK / BASELINE", "",
         "Every clause outside the history section that states an absence. Source and 'beside' are heuristics: "
         "the hand read decides. 'beside' = shares a content word with a dictated positive finding.", ""]
    for s in results:
        key = json.loads((FIXTURES / s["set"] / "answer_key.json").read_text())
        for r in s["dictations"]:
            L += [f"## {r['id']}", "", f"**Findings:** {r['findings']}", "",
                  "| arm | stated negative | source | beside a dictated positive |", "|---|---|---|---|"]
            for arm in ("new", "quick", "baseline"):
                a = r.get(arm) or {}
                if not a.get("report"):
                    continue
                srcs = _source_texts(arm, a)
                for c in negative_clauses(a["report"], key["sections"]):
                    b = beside_positive(c, r["findings"])
                    L.append(f"| {arm.upper()} | {c} | {classify_negative(c, r['findings'], srcs)} | "
                             f"{'; '.join(b) or ''} |")
            dec = (r.get("new") or {}).get("decisions") or {}
            for x in dec.get("case_exclusions", []):
                L.append(f"| NEW | NOT STATED, {x['outcome']}: {x['text']} | case negative (Phase 1) → {x['differential']} | |")
            for n in dec.get("negatives", []):
                for x in n.get("dropped", []):
                    L.append(f"| NEW | NOT STATED, dropped (Qwen {x['qwen']}): {x['text']} | case negative (Phase 1) → "
                             f"{n.get('targets')} | |")
            for arm in ("new", "quick"):
                a = r.get(arm) or {}
                stated = " ".join(negative_clauses(a.get("report") or "", key["sections"])) + " " + r["findings"]
                dup = [o.get("sentence") or o.get("text") for o in a.get("options") or []
                       if (o.get("sentence") or o.get("text")) and asserted_parts(o.get("sentence") or o.get("text"), stated)]
                L += ["", f"{arm.upper()} options offered: "
                      + (" | ".join(str(o.get("sentence") or o.get("text")) for o in a.get("options") or []) or "none")
                      + (f"  \n**{arm.upper()} options already stated or dictated:** {dup}" if dup else "")]
            L.append("")
    return "\n".join(L) + "\n"


def write_outputs(results: List[dict], out: Path) -> None:
    score_all(results)
    for s in results:
        for r in s["dictations"]:
            (out / s["set"] / f"{r['id']}.md").write_text(render_dictation(r))
            (out / s["set"] / f"{r['id']}.json").write_text(json.dumps(r, indent=1, default=str))
    (out / "summary.json").write_text(json.dumps(results, indent=1, default=str))
    (out / "summary.md").write_text(render_summary(results))
    (out / "hand_read.md").write_text(render_hand_read(results))
    if any(r.get("quick") for s in results for r in s["dictations"]):
        (out / "negatives.md").write_text(render_negatives(results))


def load_saved(out: Path, sets: List[str]) -> List[dict]:
    results = []
    for name in sets:
        recs = [json.loads(p.read_text()) for p in sorted((out / name).glob(f"{name}-d*.json"))]
        sheets = json.loads((out / name / "sheets.json").read_text())
        key = json.loads((FIXTURES / name / "answer_key.json").read_text())
        results.append({"set": name, "scan_type": key["scan_type"],
                        "lean": {k: v for k, v in sheets["lean"].items() if k not in ("sheet", "first_sheet")},
                        "baseline_sheet": {k: v for k, v in sheets["baseline"].items() if k != "sheet"},
                        "dictations": recs})
    return results


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default=",".join(sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())))
    ap.add_argument("--out", default="")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--reuse-sheets", default="", help="a previous output dir: reuse its lean and baseline sheets")
    ap.add_argument("--only", default="", help="comma-separated dictation ids (e.g. ct_ap_acute-d1); default all")
    ap.add_argument("--reuse-reports", default="", help="a previous output dir: reuse its NEW and BASELINE reports")
    ap.add_argument("--quick", action="store_true", help="add the production quick pipeline arm (QUICK)")
    ap.add_argument("--rerun", default="", help="with --reuse-reports: comma-separated arms to run again (new,quick,baseline)")
    ap.add_argument("--rescore", default="", help="a previous output dir: re-score and re-render, no model calls")
    a = ap.parse_args()
    from rapid_reports_ai.scripts.case_analyser_lab import _load_env  # loads backend/.env (model keys)

    _load_env()
    sets = [s.strip() for s in a.sets.split(",") if s.strip()]
    if a.rescore:
        out = Path(a.rescore)
        write_outputs(load_saved(out, [s for s in sets if (out / s).exists()]), out)
        print(out)
        return
    out = Path(a.out) if a.out else SCRATCH / f"e2e_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(min(a.concurrency, 2))
    results = []
    import faulthandler
    import signal

    faulthandler.register(signal.SIGUSR1, all_threads=True)  # kill -USR1 <pid>: stack dump to stderr
    runner_log = open(out / "runner_stdout.log", "w")
    with contextlib.redirect_stdout(runner_log):  # the model runner prints settings to stdout
        for name in sets:  # sets in sequence; within a set at most 2 model calls at once
            results.append(await run_set(name, out, sem, first_with(a.reuse_sheets, name),
                                         {x.strip() for x in a.only.split(",") if x.strip()} or None,
                                         first_with(a.reuse_reports, name), a.quick,
                                         {x.strip() for x in a.rerun.split(",") if x.strip()}))
            write_outputs(results, out)
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
