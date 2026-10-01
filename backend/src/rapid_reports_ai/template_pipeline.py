"""Templated reports, mirror of the quick flow (plan 2026-10-01-template-wiring).

Phase 1 (case analyser on the clinical history, at "Set up workspace") -> master sheet; then at Generate:
brief over the master (the lean sheet when the master is missing or unusable) -> generator + option writer
in parallel -> verbatim CLINICAL HISTORY inserted by code -> post-generation check beside the impression
uniqueness gate -> gate drops applied -> signature last.

Production (main.py) and the lab (scripts/template_e2e_lab.py) run this same code, so the lab measures
what ships. Behind RR_TEMPLATE_MIRROR (kill switch, default off) and the RR_PIPELINE_OVERRIDE_USERS
allowlist. Imports no quick_report* module (tests/test_report_path_split.py).
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import case_analyser as ca
from . import report_reconcile as rc
from . import template_sheet_grammar as g
from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from .report_reconcile import write_options
from .report_review import ReportSection, run_quality_check
from .template_brief import compile_template_brief
from .template_history import insert_history, write_history
from .template_manager import TemplateManager

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────

def enabled() -> bool:
    """Kill switch: RR_TEMPLATE_MIRROR=1 turns the mirror on (default off)."""
    return os.environ.get("RR_TEMPLATE_MIRROR", "0").strip().lower() in ("1", "true", "on")


def choose_mirror(requested: Optional[str], email: Optional[str]) -> bool:
    """An explicit pipeline choice ("mirror" / "current") is honoured only for allowlisted users
    (RR_PIPELINE_OVERRIDE_USERS); everyone else gets the flag's value."""
    allow = {e.strip().lower() for e in os.environ.get("RR_PIPELINE_OVERRIDE_USERS", "").split(",") if e.strip()}
    if requested in ("mirror", "current") and (email or "").strip().lower() in allow:
        return requested == "mirror"
    return enabled()


def keys(sheet: str, history: str) -> Tuple[str, str]:
    """The case key of a Phase 1 result: (sheet hash, history hash), sha256[:16] each."""
    h = lambda t: hashlib.sha256((t or "").encode()).hexdigest()[:16]  # noqa: E731
    return h(sheet), h((history or "").strip())


# ─────────────────────────────────────────────────────────────────────────────
# Jev request counting (LAB ONLY: installed by the lab, never by production)
# ─────────────────────────────────────────────────────────────────────────────

# Jev requests made by one counted run (a list per run; tasks it spawns inherit the context).
_JEV_LOG: contextvars.ContextVar = contextvars.ContextVar("jev_log", default=None)


def install_jev_counter() -> None:
    """Wrap rc._jev once so every request made inside a counted run is recorded (number of questions)."""
    if getattr(rc._jev, "_counted", False):
        return
    inner = rc._jev

    async def counted(state, questions):
        log_ = _JEV_LOG.get()
        if log_ is not None:
            log_.append(len(questions))
        return await inner(state, questions)
    counted._counted = True
    rc._jev = counted


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_VERSION = hashlib.sha256((ca.CASE_ANALYSER_SYSTEM_PROMPT + ca.CASE_ANALYSER_USER_TEMPLATE).encode()
                                ).hexdigest()[:16]


def phase1_record(res: "ca.CaseResult") -> dict:
    """Everything of a CaseResult worth keeping (raw and units_block included, so a later run can reuse it)."""
    return {"usable": res.usable, "errors": res.errors, "model": res.model, "question": res.question,
            "differentials": res.differentials, "recommendations": res.recommendations,
            "placements": [p.line if hasattr(p, "line") else str(p) for p in res.placements],
            "placement_paragraphs": [getattr(p, "paragraph", "") for p in res.placements],
            "placement_units": [{"kind": p.kind, "text": p.text, "key": p.key, "paragraph": p.paragraph}
                                for p in res.placements if hasattr(p, "kind")],
            "units_block": res.units_block, "rejected": res.rejected, "raw": res.raw,
            "grounding": getattr(res, "grounding", "grammar")}


async def run_phase1(sheet: str, scan_type: str, history: str) -> dict:
    """Phase 1 -> {"master_sheet", "case_result", "model", "latency_ms", "prompt_version"}. Raises when the
    model call failed (the caller records a failed row; generate then runs on the lean sheet). Any other
    unusable result keeps the lean sheet as the master (merge_master returns it unchanged)."""
    res = await ca.deliberate(sheet, ca.summarise_template(sheet), scan_type, history or "")
    failed = [e for e in res.errors if e.startswith("model call failed")]
    if failed:
        raise RuntimeError(failed[0])
    # An old-format sheet is never merged (its units serve options only): the master is the sheet as stored.
    master = sheet if getattr(res, "grounding", "grammar") == "old_sheet" else ca.merge_master(sheet, res)
    return {"master_sheet": master, "case_result": phase1_record(res), "model": res.model,
            "latency_ms": res.ms, "prompt_version": PROMPT_VERSION}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 at "Set up workspace", resolved at Generate
# ─────────────────────────────────────────────────────────────────────────────

PHASE1_AWAIT_S = 60  # Generate waits this long for an in-flight Phase 1, then runs on the lean sheet
# In-flight Phase 1 jobs of this process, by case key (user, template, sheet hash, history hash). One uvicorn
# process: a replica or worker that misses this dict runs Phase 1 inline once (about 15 s), nothing else.
_PHASE1_TASKS: Dict[tuple, "asyncio.Task"] = {}


def _session():
    """A DB session of the job's own (the request's session is closed when the request returns)."""
    from .database.connection import SessionLocal
    return SessionLocal()


def _persist(write) -> None:
    """Run one write in a session of its own; called in a worker thread so the event loop never blocks."""
    db = _session()
    try:
        write(db)
    except Exception as e:  # noqa: BLE001 - the in-memory result still serves the generate awaiting it
        logger.warning("template Phase 1: persist failed (%s: %s)", type(e).__name__, str(e)[:200])
    finally:
        db.close()


async def _phase1_job(key: tuple, row_id, sheet: str, scan_type: str, history: str) -> Optional[str]:
    """Run Phase 1 and persist it (ready, or failed on any exception). Returns the master sheet, None on
    failure. Always removes its own _PHASE1_TASKS entry."""
    from .database import crud
    try:
        try:
            out = await run_phase1(sheet, scan_type, history)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:2000]
            logger.warning("template Phase 1 failed: %s", err[:200])
            await asyncio.to_thread(_persist, lambda db: crud.fail_case_sheet(db, row_id, error=err))
            return None
        await asyncio.to_thread(_persist, lambda db: crud.finish_case_sheet(
            db, row_id, master_sheet=out["master_sheet"], case_result=out.get("case_result"), model=out.get("model"),
            latency_ms=out.get("latency_ms"), prompt_version=out.get("prompt_version")))
        return out["master_sheet"]
    finally:
        if _PHASE1_TASKS.get(key) is asyncio.current_task():
            _PHASE1_TASKS.pop(key, None)


def _start(db, key: tuple, sheet: str, scan_type: str, history: str) -> Optional["asyncio.Task"]:
    """Create (or reset a failed) running row and start its job; None when the row is already ready."""
    from .database import crud
    user_id, template_id, sk, hk = key
    row = crud.create_case_sheet(db, user_id=user_id, template_id=template_id, sheet_hash=sk, history_hash=hk,
                                 clinical_history=history or "")
    if row.status == "ready":
        return None
    task = asyncio.create_task(_phase1_job(key, row.id, sheet, scan_type, history))
    _PHASE1_TASKS[key] = task
    return task


def _key(user_id, template_id, sheet: str, history: str) -> tuple:
    return (str(user_id), str(template_id), *keys(sheet, history))


async def prepare_phase1(db, user_id, template_id, sheet: str, scan_type: str, history: str) -> str:
    """"ready" (stored), or "running" (in flight, or started now). No await between the lookups and the
    task registration, so concurrent prepares of one case in this process start one job."""
    from .database import crud
    key = _key(user_id, template_id, sheet, history)
    row = crud.get_case_sheet(db, *key)
    if row is not None and row.status == "ready":
        return "ready"
    task = _PHASE1_TASKS.get(key)
    if task is not None and not task.done():
        return "running"
    return "running" if _start(db, key, sheet, scan_type, history) is not None else "ready"


async def resolve_master(db, user, template, sheet: str, scan_type: str, history: str) -> Tuple[Optional[str], str]:
    """The case's master sheet for Generate, and where it came from: "cached" (stored), "awaited" (in flight
    since prepare), "inline" (no prepare: run now), or (None, "failed") (failed row, timeout or error: the
    pipeline then runs on the lean sheet). Waiting never cancels the job: it persists for the next generate."""
    from .database import crud
    key = _key(getattr(user, "id", user), getattr(template, "id", template), sheet, history)
    try:
        row = crud.get_case_sheet(db, *key)
        if row is not None and row.status == "ready" and row.master_sheet:
            return row.master_sheet, "cached"
        task, source = _PHASE1_TASKS.get(key), "awaited"
        if task is None or task.done():
            if row is not None and row.status == "failed":
                return None, "failed"
            task, source = _start(db, key, sheet, scan_type, history), "inline"
            if task is None:  # became ready meanwhile
                row = crud.get_case_sheet(db, *key)
                return (row.master_sheet, "cached") if row is not None and row.master_sheet else (None, "failed")
        master = await asyncio.wait_for(asyncio.shield(task), PHASE1_AWAIT_S)
        return (master, source) if master else (None, "failed")
    except Exception as e:  # noqa: BLE001 - timeout or error: generate on the lean sheet
        logger.warning("template Phase 1 unavailable (%s: %s); lean sheet", type(e).__name__, str(e)[:200])
        return None, "failed"


async def resolve_case(db, user, template, sheet: str, scan_type: str, history: str) -> Tuple[Optional[dict], str]:
    """The lean path's view of Phase 1 (template_lean): the stored case_result (units for options only), and
    where it came from, as resolve_master. (None, source) when Phase 1 is unavailable: no Phase-1 options."""
    from .database import crud
    master, source = await resolve_master(db, user, template, sheet, scan_type, history)
    if master is None:
        return None, source
    try:
        row = crud.get_case_sheet(db, *_key(getattr(user, "id", user), getattr(template, "id", template), sheet, history))
        return (row.case_result if row is not None else None), source
    except Exception as e:  # noqa: BLE001
        logger.warning("template Phase 1 case read failed (%s: %s)", type(e).__name__, str(e)[:200])
        return None, "failed"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: brief -> generate (+ options, history) -> check + gate
# ─────────────────────────────────────────────────────────────────────────────

def section_block(sheet: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$([\s\S]*?)(?=^##\s|\Z)", sheet, re.M | re.I)
    return m.group(1).strip() if m else ""


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


async def generate_template_report(*, sheet: str, scan_type: str, findings: str, history: str,
                                   master_sheet: Optional[str], signature: Optional[str]) -> dict:
    """Phase 2 over a lean template sheet and its Phase 1 master sheet (None when Phase 1 is unavailable)."""
    rec: dict = {"lat": {}}
    jev_log = _JEV_LOG.get()
    jev0 = len(jev_log) if jev_log is not None else 0
    lean = g.parse_sheet(sheet, mode="template").structure
    sections = [ReportSection(name=x.name, header=x.header, role=x.role)
                for x in sorted(lean.sections, key=lambda x: x.order)]
    hist_sec = next((x for x in sections if x.role == "history"), None)
    imp = next((x.name for x in sections if x.role == "impression"), "IMPRESSION")

    # Master sheet (Phase 1 output), else the lean sheet
    mres = g.parse_sheet(master_sheet, mode="master") if master_sheet else None
    phase1_used = bool(mres and mres.structure.usable)
    rec["master_usable"] = mres.structure.usable if mres else None
    rec["master_errors"] = [f"{e.line}: {e.reason}: {e.text[:100]}" for e in mres.errors] if mres else []
    brief_sheet, brief_struct = (master_sheet, mres.structure) if phase1_used else (sheet, lean)

    # Phase 2 brief (fail-soft: the generator then takes the raw path)
    t = time.time()
    brief = None
    try:
        brief = await compile_template_brief(brief_sheet, brief_struct, scan_type, findings, history)
    except Exception as e:  # noqa: BLE001
        rec["brief_error"] = f"{type(e).__name__}: {e}"[:400]
        logger.warning("template brief failed (%s); generating from the raw sheet", rec["brief_error"][:200])
    rec["lat"]["brief_s"] = round(time.time() - t, 2)
    jev_brief = len(jev_log) if jev_log is not None else 0

    # Generate + options in parallel (as quick)
    style = "\n".join(x for x in (section_block(sheet, "Impression Construction"),
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
        o = await write_options(brief.decisions.get("options", []) if brief else [], findings, scan_type,
                                model=MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"], runner=_run_agent_with_model,
                                style=style, impression_section=imp, require_service=True)
        return o, round(time.time() - t0, 1)

    (out, rec["lat"]["generator_s"]), (options, rec["lat"]["options_s"]) = await asyncio.gather(gen(), opts())
    report = out["report_content"]
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
        res = await run_quality_check(report, findings, scan_type, options, sections=sections,
                                      protected=protected, suppressed=avoid, extra_report_qs=gate_qs["report"],
                                      history=hist_text)
        return res, round(time.time() - t0, 1)

    async def gated():  # impression-scope questions need the conclusion as state: one parallel request
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
    jev_end = len(jev_log) if jev_log is not None else 0
    rec.update({
        "report_content": report, "model_used": out.get("model_used"), "description": out.get("description"),
        "scan_type": out.get("scan_type") or scan_type,
        "brief_used": brief is not None, "brief_text": brief.text if brief else None,
        "brief_decisions": brief.decisions if brief else None,
        "options": options, "gate_dropped": gate_dropped, "quality_check": quality,
        "sections": [x.name for x in sections], "history_inserted": bool(hist_text), "phase1_used": phase1_used,
        "protected": protected,
        "jev_calls": ({"brief": jev_brief - jev0, "post_generation": jev_end - jev_brief}
                      if jev_log is not None else {}),
    })
    return rec


def candidate_record(result: dict, latency_ms: int) -> dict:
    """The quick candidate record's fields (quick_report_api._run_one_generator), plus sections and lat."""
    return {"model": result.get("model_used") or "unknown", "content": result.get("report_content", ""),
            "latency_ms": latency_ms, "generated_at": datetime.now(timezone.utc).isoformat(), "error": None,
            "description": result.get("description"), "options": result.get("options") or [],
            "options_applied": [], "quality_check": result.get("quality_check"),
            "brief": ({"text": result.get("brief_text"), "decisions": result.get("brief_decisions")}
                      if result.get("brief_used") else None),
            "sections": result.get("sections") or [], "lat": result.get("lat") or {}}
