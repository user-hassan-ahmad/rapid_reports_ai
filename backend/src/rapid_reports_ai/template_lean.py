"""Lean templated reports (arm E, owner decision 2026-10-01): today's generator, unchanged, on the template's
stored sheet; the post-generation check; Phase 1 used ONLY for options.

    prepare:  Phase 1 (case_analyser) on the stored sheet: grammar summary, or the sheet's own prose when the
              grammar parse is unusable (old-format sheets) -> case units, stored by template_pipeline's plumbing.
    generate: TemplateManager._generate_report_skill_sheet_guided (brief_text None)  ||  case_options
              (Jev presence, Qwen contradicted / expected, impression plan, dedupe, caps) -> write_options
           -> run_quality_check with sections read from the generated report's own headers  ||  uniqueness gate
           -> gate drops -> signature last.

Nothing from Phase 1 is written into the report: its targeted exclusion negatives, If-present negatives for
dictated findings and recommendations whose trigger is dictated are only offered. No conversion, no grammar
requirement, no brief. The heavy path (template_pipeline.generate_template_report) is parked, not deleted.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from . import report_reconcile as rc
from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from .report_reconcile import write_options
from .report_review import ReportSection, run_quality_check
from .template_brief import _scores
from .template_manager import TemplateManager
from .template_sheet_structure import _key

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sections from the generated report's own headers
# ─────────────────────────────────────────────────────────────────────────────

_IMPRESSION = re.compile(r"(?i)^(conclusions?|impressions?|summary|opinion|comments?)\b")
_ROLES = (("comparison", re.compile(r"(?i)\b(comparison)\b")),
          ("technique", re.compile(r"(?i)\b(technique|procedure|protocol)\b")),
          ("history", re.compile(r"(?i)\b(history|clinical (details|information|indication)|indication)\b")))
_ALONE = re.compile(r"^([A-Za-z][A-Za-z0-9 /&(),'\-]{0,58}?)\s*:\s*$")
_INLINE = re.compile(r"^([A-Za-z][A-Za-z0-9 /&(),'\-]{0,40}?)\s*:\s+\S")
IMPLICIT = "FINDINGS"


def _role(label: str) -> str:
    if _IMPRESSION.match(label.strip()):
        return "impression"
    return next((role for role, rx in _ROLES if rx.search(label)), "findings")


def report_sections(report: str, sheet: str = "") -> List[ReportSection]:
    """The report's sections, in order, from its header lines: a short line ending in ':' or in capitals, or an
    inline 'Label: text' whose label the sheet declares as a header (header: "...") or is an impression word.
    Text before the first header is an implicit findings section."""
    declared = {h.strip().rstrip(":").strip().lower() for h in re.findall(r'header:\s*"([^"]+)"', sheet or "")}
    lines = (report or "").replace("\r\n", "\n").split("\n")
    secs: List[ReportSection] = []
    first: Optional[int] = None
    for i, ln in enumerate(lines):
        s = ln.strip().strip("*#").strip()
        if not s:
            continue
        label, colon = None, True
        m = _ALONE.match(s)
        if m:
            label = m.group(1).strip()
        elif len(s) <= 60 and not s.endswith(".") and (
                (s.isupper() and re.search(r"[A-Z]{3}", s)) or s.lower() in declared
                or re.fullmatch(_IMPRESSION.pattern + r"\s*", s, re.I)):
            label, colon = s, False  # a header line without a colon: capitals, declared, or an impression word
        else:
            m = _INLINE.match(s)
            if m and (m.group(1).strip().lower() in declared or _IMPRESSION.match(m.group(1).strip())):
                label = m.group(1).strip()
        if not label or label.upper() in {x.name for x in secs}:
            continue
        first = i if first is None else first
        secs.append(ReportSection(name=label.upper(), header=label + (":" if colon else ""), role=_role(label)))
    if first is None or any(x.strip() for x in lines[:first]):
        name = IMPLICIT if IMPLICIT not in {x.name for x in secs} else IMPLICIT + " (BODY)"
        secs.insert(0, ReportSection(name=name, header=None, role="findings"))
    return secs


def option_section(option: dict, sections: List[ReportSection]) -> str:
    """Where an option goes in this report: an impression / recommendation item in the impression section; a
    finding-linked negative in the section named as its Phase-1 paragraph, else the first findings section whose
    name says FINDINGS, else the first findings section."""
    if option.get("kind") != "finding_negative":
        return next((s.name for s in sections if s.role == "impression"), option.get("section") or "IMPRESSION")
    want = (option.get("section") or "").strip().upper()
    found = [s for s in sections if s.role == "findings"]
    return (next((s.name for s in found if s.name == want), None)
            or next((s.name for s in found if "FINDING" in s.name), None)
            or (found[0].name if found else IMPLICIT))


def _block(sheet: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$([\s\S]*?)(?=^##\s|\Z)", sheet or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def _split_report(report: str, sections: List[ReportSection], name: str) -> str:
    from .report_review import section_spans
    return next((report[a:b].strip() for s, a, b in section_spans(report, sections) if s.name == name), "")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 units -> options (shared routing; never written into the report)
# ─────────────────────────────────────────────────────────────────────────────

async def case_options(case: Optional[dict], findings: str, scan_type: str, history: str, *,
                       findings_section: str = "FINDINGS", impression_section: str = "IMPRESSION",
                       section_names: Optional[List[str]] = None, inclusion_logic: str = "") -> Tuple[List[dict], dict]:
    """(raw options for write_options, decisions). Phase-1 units are routed as the heavy brief routes them:
    - IF_PRESENT: Jev finding presence (rc.q_finding) + Qwen contradicted / expected + rc.route_finding;
      "stated" and "offered" are both offered (stated first), MAX_FINDING_OPTIONS in all;
    - targeted NEGATIVE: dropped when its differential is reported (rc.q_present + rc.route_differential) or Qwen
      finds it contradicted / expected; otherwise offered in the room the If-present options leave;
    - RECOMMEND: Jev condition met (rc.Q_REC_MET) + the impression plan (rc.route_recommendation) -> offered.
    Plus the plan's optional impression items, as before. Fails closed: a Jev or Qwen error offers no Phase-1
    negative or recommendation (the plan's impression items still go)."""
    case = case or {}
    dec: dict = {"differentials": [], "finding_negatives": [], "case_exclusions": [], "recommendations": [],
                 "impression_plan": None}
    items = rc.split_findings(findings or "")
    diffs = [d for d in case.get("differentials") or [] if d.get("name")]
    recs = [r for r in case.get("recommendations") or [] if r.get("tag") and r.get("text")]
    units = [u for u in case.get("placement_units") or [] if u.get("text")]
    negs = [u for u in units if u.get("kind") == "NEGATIVE"]
    ifps = [u for u in units if u.get("kind") == "IF_PRESENT"]
    fkeys = list(dict.fromkeys(u.get("key", "") for u in ifps))
    rec_text = [f"{r['tag']}: {r['text']} (when {r.get('when', '')})" for r in recs]
    names = {n.upper(): n for n in (section_names or [])}

    def section_of(u: dict) -> str:
        return names.get((u.get("paragraph") or "").upper()) or u.get("paragraph") or findings_section

    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    qs: Dict[str, dict] = {}
    for k, d in enumerate(diffs):
        qs[f"d{k}"] = rc.q_present(d["name"], d.get("discriminator", ""))
    for i, f in enumerate(fkeys):
        qs[f"f{i}"] = rc.q_finding(f)
    for k, t in enumerate(rec_text):
        qs[f"rec{k}"] = {"type": "noul", "instructions": rc.Q_REC_MET + t}

    async def plan_or_none():
        if not items:
            return None
        try:
            return await rc._plan(scan_type, history, items, rec_text, inclusion_logic=inclusion_logic)
        except Exception as e:  # noqa: BLE001 - as quick: no plan, no plan-sourced options
            logger.warning("lean template: impression plan failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    plan_t = asyncio.ensure_future(plan_or_none())
    options: List[dict] = []
    try:
        sc = _scores(await rc._jev(state, qs), qs) if qs else {}
        route = {d["name"]: rc.route_differential(sc[f"d{k}"], d.get("visible", "")) for k, d in enumerate(diffs)}
        dec["differentials"] = [{"name": d["name"], "visible": d.get("visible"), "present": round(sc[f"d{k}"], 3),
                                 "action": route[d["name"]]} for k, d in enumerate(diffs)]
        # A targeted negative whose branch is reported is never offered; nor is the same claim as an If-present.
        omit = {_key(u["text"]) for u in negs if route.get(u.get("key")) == "present"}
        to_classify: List[str] = []
        for u in negs:
            if _key(u["text"]) not in omit and _key(u["text"]) not in {_key(x) for x in to_classify}:
                to_classify.append(u["text"])
        for u in ifps:
            if (sc[f"f{fkeys.index(u.get('key', ''))}"] >= rc.PRESENT_LOW and _key(u["text"]) not in omit
                    and _key(u["text"]) not in {_key(x) for x in to_classify}):
                to_classify.append(u["text"])
        qw = (await rc._qwen_complete(state, to_classify, [], [], log=logger) if to_classify
              else rc.QwenDecisions(negatives=[], affected_normals=[], applicable_measurements=[]))
        label = {_key(to_classify[d.index]): d.action for d in qw.negatives}

        # If-present (handled once per claim; a claim a targeted negative carries is routed there)
        targeted = {_key(u["text"]) for u in negs}
        routed, seen = [], set()
        for u in ifps:
            k = _key(u["text"])
            pf = sc[f"f{fkeys.index(u.get('key', ''))}"]
            if k in seen or k in targeted or k in omit:
                dec["finding_negatives"].append({"finding": u.get("key"), "text": u["text"], "present": round(pf, 3),
                                                 "outcome": "handled_elsewhere"})
                continue
            seen.add(k)
            r = rc.route_finding(label.get(k, "keep") if pf >= rc.PRESENT_LOW else "keep", pf, u.get("tag", "contextual"))
            routed.append((u, pf, r))
        order = sorted((x for x in routed if x[2] in ("stated", "offered")), key=lambda x: x[2] != "stated")
        offered = order[:rc.MAX_FINDING_OPTIONS]
        for u, pf, r in routed:
            out = "offered" if any(u is o[0] for o in offered) else (r if r in ("dropped", "do_not_assert") else "trimmed")
            dec["finding_negatives"].append({"finding": u.get("key"), "text": u["text"], "present": round(pf, 3),
                                             "qwen": label.get(_key(u["text"])), "route": r, "outcome": out})
        options += [{"kind": "finding_negative", "section": section_of(u), "text": u["text"], "finding": u.get("key", ""),
                     "reason": "finding reported" if r == "stated" else f"finding reported (p={pf:.2f})"}
                    for u, pf, r in offered]

        # Targeted exclusions (never stated): offered unless the branch is reported or the dictation contradicts
        excl = []
        for u in negs:
            k = _key(u["text"])
            why = ("differential_present" if k in omit else
                   "qwen_" + label[k] if label.get(k) in ("contradicted", "expected") else None)
            if why:
                dec["case_exclusions"].append({"text": u["text"], "differential": u.get("key"), "outcome": why})
            else:
                excl.append({"kind": "finding_negative", "section": section_of(u), "text": u["text"],
                             "finding": u.get("key", ""), "reason": f"excludes {u.get('key', '')}"})
        plan = await plan_t

        # Recommendations: the trigger must be dictated; the plan includes or offers
        pdec = {d.index: d for d in plan.recommendations} if plan else {}
        for k, r in enumerate(recs):
            d = pdec.get(k)
            if plan is None and f"{r['tag']}:" in rc._BAR_KINDS:
                d = rc.RecDecision(index=k, decision="optional", reason="impression plan unavailable")
            room = len([o for o in options if o["kind"] != "finding_negative"]) < rc.MAX_OPTIONS
            rt = rc.route_recommendation(1 - sc[f"rec{k}"], d, tag=r["tag"], room=room)
            if rt in ("keep", "optional"):
                options.append({"kind": "recommendation", "section": impression_section, "text": f"{r['tag']}: {r['text']}",
                                "reason": (d.reason if d and d.reason else "condition reported")})
            dec["recommendations"].append({"tag": r["tag"], "text": r["text"], "unmet": round(1 - sc[f"rec{k}"], 3),
                                           "route": rt, "outcome": "offered" if rt in ("keep", "optional") else rt})
    except Exception as e:  # noqa: BLE001 - fail closed: no Phase-1 option is offered on an unchecked routing
        logger.warning("lean template: Phase 1 option routing failed (%s: %s); none offered", type(e).__name__,
                       str(e)[:200])
        dec["error"] = f"{type(e).__name__}: {e}"[:300]
        options, excl = [], []
        plan = await plan_t

    # The plan's optional impression items (as the heavy path and quick), in the room left
    if plan and items:
        carry = {items[i] for i in plan.impression if 0 <= i < len(items)}
        room = max(0, rc.MAX_OPTIONS - sum(o["kind"] != "finding_negative" for o in options))
        opt = [items[i] for i in dict.fromkeys(plan.optional_impression)
               if 0 <= i < len(items) and items[i] not in carry][:room]
        options += [{"kind": "impression", "section": impression_section, "text": t, "reason": ""} for t in opt]
        dec["impression_plan"] = {"carry": sorted(carry), "optional": opt}

    # De-duplicate against the dictation's own negatives; exclusions fill the finding-linked room
    options, dup = rc.dedupe_options(options, [], findings)
    kept, dup2 = rc.dedupe_options(excl, [o["text"] for o in options if o["kind"] == "finding_negative"], findings)
    room = max(0, rc.MAX_FINDING_OPTIONS - sum(o["kind"] == "finding_negative" for o in options))
    for o in excl:
        out = "duplicate_dropped" if o not in kept else ("offered" if room else "trimmed")
        if out == "offered":
            room -= 1
            options.append(o)
        dec["case_exclusions"].append({"text": o["text"], "differential": o["finding"], "outcome": out})
    dec["duplicates_dropped"] = dup + dup2
    return options, dec


# ─────────────────────────────────────────────────────────────────────────────
# Generate (arm E)
# ─────────────────────────────────────────────────────────────────────────────

async def generate_template_report_lean(*, sheet: str, scan_type: str, findings: str, history: str,
                                        case: Optional[dict], signature: Optional[str]) -> dict:
    """Today's single-pass generator on the stored sheet, Phase-1 options beside it, then the post-generation
    check (sections from the report's own headers) beside the impression uniqueness gate. `case` is the stored
    Phase 1 case_result (template_pipeline.phase1_record), or None."""
    rec: dict = {"lat": {}}
    style = "\n".join(x for x in (_block(sheet, "Impression Construction Rules") or _block(sheet, "Impression Construction"),
                                  _block(sheet, "Terminology Rules")) if x)

    async def gen():
        t0 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history})
        return out, round(time.time() - t0, 1)

    async def opts():
        t0 = time.time()
        raw, dec = await case_options(case, findings, scan_type, history, findings_section="FINDINGS",
                                      impression_section="IMPRESSION", inclusion_logic=style)
        t1 = time.time()
        written = await write_options(raw, findings, scan_type, model=MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"],
                                      runner=_run_agent_with_model, style=style, impression_section="IMPRESSION",
                                      require_service=True)
        return written, raw, dec, round(t1 - t0, 1), round(time.time() - t1, 1)

    (out, rec["lat"]["generator_s"]), (options, raw, dec, rec["lat"]["route_s"], rec["lat"]["options_s"]) = \
        await asyncio.gather(gen(), opts())
    report = out["report_content"]
    rec["report_generated"] = report

    # Sections come from the generated report; options are placed in its findings / impression sections
    sections = report_sections(report, sheet)
    imp = next((s.name for s in sections if s.role == "impression"), None)
    for o in options:
        o["section"] = option_section(o, sections)
    impression = _split_report(report, sections, imp) if imp else ""
    gate_qs = rc.gate_questions(options)

    async def checked():
        t0 = time.time()
        res = await run_quality_check(report, findings, scan_type, options, sections=sections, protected=[],
                                      suppressed=[], extra_report_qs=gate_qs["report"], history=None)
        return res, round(time.time() - t0, 1)

    async def gated():
        t0 = time.time()
        res = await rc.gate_scores(f"CONCLUSION:\n{impression}", gate_qs["impression"])
        return res, round(time.time() - t0, 2)

    ((report, checked_opts, quality), rec["lat"]["check_s"]), (imp_scores, rec["lat"]["gate_s"]) = \
        await asyncio.gather(checked(), gated())
    _, gate_dropped = rc.gate_apply(options, {**(quality or {}).get("extra_answers", {}), **imp_scores})
    drop_ids = {o.get("id") for o in gate_dropped}
    options = [o for o in checked_opts if o.get("id") not in drop_ids]
    if signature:
        report = report.rstrip() + "\n\n" + signature
    rec.update({
        "report_content": report, "model_used": out.get("model_used"), "description": out.get("description"),
        "scan_type": out.get("scan_type") or scan_type, "brief_used": False, "brief_text": None,
        "brief_decisions": None, "case_decisions": dec, "options_raw": raw, "options": options,
        "gate_dropped": gate_dropped, "quality_check": quality, "sections": [s.name for s in sections],
        "phase1_used": bool(case), "history_inserted": False,
    })
    return rec
