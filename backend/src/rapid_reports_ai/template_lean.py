"""Lean templated reports (arm E, owner decision 2026-10-01): today's generator, unchanged, on the template's
stored sheet; the post-generation check; Phase 1 used ONLY for options.

    prepare:  Phase 1 (case_analyser) on the stored sheet: grammar summary, or the sheet's own prose when the
              grammar parse is unusable (old-format sheets) -> case units, stored by template_pipeline's plumbing.
    generate: TemplateManager._generate_report_skill_sheet_guided (brief_text None)  ||  case_options
              (Jev presence, Qwen contradicted / expected, impression plan, device guard, dedupe, cap) -> write_options
           -> run_quality_check on the report alone (sections from its own headers)  ||  vet_options (contradiction
              + uniqueness) -> signature last. The report returns after the check and never waits for options:
              routing / writing / vetting finish in the background (the returned `options_job`).

Nothing from Phase 1 is written into the report: its targeted exclusion negatives, If-present negatives for
dictated findings and recommendations whose trigger is dictated are only offered. No conversion, no grammar
requirement, no brief. The heavy path (template_pipeline.generate_template_report) is parked, not deleted.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from . import report_reconcile as rc
from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from .report_reconcile import write_options
from .report_review import CONTRA_FLAG, Q_CONTRA, ReportSection, run_quality_check
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


_FILLER = frozenset(("AND", "THE", "WITHIN", "SEPARATE", "PARAGRAPH", "SECTION", "FINDINGS", "FINDING", "OTHER"))


def option_section(option: dict, sections: List[ReportSection]) -> str:
    """Where an option goes in this report: an impression / recommendation item in the impression section; a
    finding-linked negative in the section named as its Phase-1 paragraph, else the first findings section whose
    name says FINDINGS, else the first findings section."""
    if option.get("kind") != "finding_negative":
        return next((s.name for s in sections if s.role == "impression"), option.get("section") or "IMPRESSION")
    want = (option.get("section") or "").strip().upper()
    found = [s for s in sections if s.role == "findings"]
    headed = [s for s in found if s.header] or found  # the implicit preface only when nothing else is a findings section
    words = lambda t: {w for w in re.findall(r"[A-Z0-9]+", t.upper()) if len(w) >= 3 and w not in _FILLER}  # noqa: E731
    return (next((s.name for s in found if s.name == want), None)
            or next((s.name for s in headed if words(s.name) & words(want)), None)
            or next((s.name for s in headed if "FINDING" in s.name), None)
            or (headed[0].name if headed else IMPLICIT))


def _block(sheet: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$([\s\S]*?)(?=^##\s|\Z)", sheet or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def _split_report(report: str, sections: List[ReportSection], name: str) -> str:
    from .report_review import section_spans
    return next((report[a:b].strip() for s, a, b in section_spans(report, sections) if s.name == name), "")


# ─────────────────────────────────────────────────────────────────────────────
# Device / prior-procedure guard and the option cap
# ─────────────────────────────────────────────────────────────────────────────

# An option that presupposes a device or prior intervention ("No contrast within the aneurysm sac" is endoleak
# framing) is offered only when the dictation or the history reports it. Two Jev questions per candidate, in one
# call whose state carries the history (Jev reads history quoted inside a question poorly: EVAR in the history
# scored 0.12 there, 0.95 in the state). Probe: scratchpad device_probe/probe3.json. A single combined question
# ("reports it, or presupposes none") passed the native-aneurysm sac at 0.53 / 0.56, so it is not used.
# Wording "C" and the thresholds come from the wide probe (scratchpad device_probe_wide/, results_C_68238.json):
# 124 items (DEV + HOLD), two reps, 0 errors in both directions (no device option kept without the device, no
# native option dropped), every item at least 0.12 from the deciding threshold. Drop when dv >= 0.4 AND dr < 0.6.
# The 0.6 was chosen with the holdout in view, so it is not an unseen-data estimate; it leans on dropping being
# the safe direction (an option is never needed, a wrongly offered device negative is a false statement).
_DEVICE_EG = ("for example a stent graft, stent, bypass graft, valve prosthesis, closure or occluder device, pacemaker "
              "lead, line, catheter, drain, endotracheal or feeding tube, mesh, stoma, joint replacement, fixation "
              "hardware, sternal wires, a surgical anastomosis, a resection cavity or a radiotherapy field")
DEVICE_PRESUPPOSES = 0.4   # dv at or above: the negative presupposes a device, procedure or treatment
DEVICE_REPORTED = 0.6      # dr at or above: the case reports it


def device_state(scan_type: str, history: str, findings: str) -> str:
    return f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\nDICTATED FINDINGS:\n{findings}"


def device_questions(k, text: str) -> dict:
    """dv<k>: the negative presupposes a device, procedure or treatment; dr<k>: the case reports it."""
    return {
        f"dv{k}": {"type": "noul",
                   "instructions": f'This negative only makes sense for a patient who has a device or has had a prior '
                                   f'procedure or treatment: "{text}"',
                   "criteria": {"true": f"It is about a device, or the result of a prior procedure or treatment "
                                        f"({_DEVICE_EG}): its position, patency, migration, leak or complication, or a "
                                        "change that can only occur after it, such as contrast in a treated aneurysm "
                                        "sac.",
                                "false": "It is about native anatomy or disease that can occur in a patient who has "
                                         "never had a device, procedure or treatment."}},
        f"dr{k}": {"type": "noul",
                   "instructions": f'The dictated findings or the clinical history report the same device, prior '
                                   f'procedure or treatment that this negative presupposes: "{text}"',
                   "criteria": {"true": "The dictated findings or the clinical history mention that device, procedure "
                                        "or treatment, or the procedure that placed the device, in any wording, synonym "
                                        "or abbreviation.",
                                "false": "Neither the dictated findings nor the clinical history mention that device, "
                                         "procedure or treatment; a different kind of device, procedure or treatment "
                                         "does not count."}},
    }


def device_keep(answers: dict, k) -> bool:
    """False when the negative presupposes a device or procedure the case does not report; an unreadable answer
    drops it (conservative: an option is never needed)."""
    try:
        dv, dr = float(answers[f"dv{k}"]["noul"]), float(answers[f"dr{k}"]["noul"])
    except Exception:  # noqa: BLE001
        return False
    return not (dv >= DEVICE_PRESUPPOSES and dr < DEVICE_REPORTED)


MAX_FINDING_NEGATIVES = 3
MAX_TOTAL_OPTIONS = 5
_RANK = {("finding_negative", "if_present"): 0, ("finding_negative", "exclusion"): 1, ("recommendation", None): 2,
         ("impression", None): 3}


def _rank(o: dict) -> int:
    kind = o.get("kind")
    return _RANK.get((kind, o.get("origin") if kind == "finding_negative" else None), _RANK.get((kind, None), 4))


def cap_options(options: List[dict]) -> Tuple[List[dict], List[dict]]:
    """(kept, capped): at most MAX_FINDING_NEGATIVES finding negatives and MAX_TOTAL_OPTIONS in all, by usefulness:
    finding-linked If-present, then case exclusions, then recommendations, then impression items (stable within)."""
    kept, capped, n_fn = [], [], 0
    for o in sorted(options, key=_rank):
        fn = o.get("kind") == "finding_negative"
        if len(kept) >= MAX_TOTAL_OPTIONS or (fn and n_fn >= MAX_FINDING_NEGATIVES):
            capped.append(o)
            continue
        n_fn += fn
        kept.append(o)
    return kept, capped


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 units -> options (shared routing; never written into the report)
# ─────────────────────────────────────────────────────────────────────────────

async def case_options(case: Optional[dict], findings: str, scan_type: str, history: str, *,
                       findings_section: str = "FINDINGS", impression_section: str = "IMPRESSION",
                       section_names: Optional[List[str]] = None, inclusion_logic: str = "") -> Tuple[List[dict], dict]:
    """(raw options for write_options, decisions). Phase-1 units are routed as the heavy brief routes them:
    - IF_PRESENT: Jev finding presence (rc.q_finding) + Qwen contradicted / expected + rc.route_finding;
      "stated" and "offered" are both offered (stated first);
    - targeted NEGATIVE: dropped when its differential is reported (rc.q_present + rc.route_differential) or Qwen
      finds it contradicted / expected; otherwise offered;
    - either kind is dropped when it presupposes a device or prior procedure the case does not report (Jev, one
      parallel call whose state carries the history);
    - RECOMMEND: Jev condition met (rc.Q_REC_MET) + the impression plan (rc.route_recommendation) -> offered.
    Plus the plan's optional impression items, as before; then cap_options. Fails closed: a Jev or Qwen error offers
    no Phase-1 negative or recommendation (the plan's impression items still go)."""
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
    dev_texts = list(dict.fromkeys(u["text"] for u in units))
    dqs = {k: q for i, t in enumerate(dev_texts) for k, q in device_questions(i, t).items()}
    options: List[dict] = []
    excl: List[dict] = []
    dev_t = asyncio.ensure_future(rc._jev(device_state(scan_type, history, findings), dqs)) if dqs else None
    try:
        sc = _scores(await rc._jev(state, qs), qs) if qs else {}
        dev = await dev_t if dev_t else {}
        dev_ok = lambda t: device_keep(dev, dev_texts.index(t))  # noqa: E731
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
        offered = [x for x in order if dev_ok(x[0]["text"])]
        for u, pf, r in routed:
            out = ("offered" if any(u is o[0] for o in offered) else
                   "device_not_reported" if r in ("stated", "offered") else r)
            dec["finding_negatives"].append({"finding": u.get("key"), "text": u["text"], "present": round(pf, 3),
                                             "qwen": label.get(_key(u["text"])), "route": r, "outcome": out})
        options += [{"kind": "finding_negative", "origin": "if_present", "section": section_of(u), "text": u["text"],
                     "finding": u.get("key", ""), "reason": "finding reported" if r == "stated" else f"finding reported (p={pf:.2f})"}
                    for u, pf, r in offered]

        # Targeted exclusions (never stated): offered unless the branch is reported or the dictation contradicts
        for u in negs:
            k = _key(u["text"])
            why = ("differential_present" if k in omit else
                   "qwen_" + label[k] if label.get(k) in ("contradicted", "expected") else
                   "device_not_reported" if not dev_ok(u["text"]) else None)
            if why:
                dec["case_exclusions"].append({"text": u["text"], "differential": u.get("key"), "outcome": why})
            else:
                excl.append({"kind": "finding_negative", "origin": "exclusion", "section": section_of(u), "text": u["text"],
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
        if dev_t and not dev_t.done():
            dev_t.cancel()
        plan = await plan_t

    # The plan's optional impression items (as the heavy path and quick), in the room left
    if plan and items:
        carry = {items[i] for i in plan.impression if 0 <= i < len(items)}
        room = max(0, rc.MAX_OPTIONS - sum(o["kind"] != "finding_negative" for o in options))
        opt = [items[i] for i in dict.fromkeys(plan.optional_impression)
               if 0 <= i < len(items) and items[i] not in carry][:room]
        options += [{"kind": "impression", "section": impression_section, "text": t, "reason": ""} for t in opt]
        dec["impression_plan"] = {"carry": sorted(carry), "optional": opt}

    # De-duplicate against the dictation's own negatives and each other; then the cap, by usefulness
    options, dup = rc.dedupe_options(options, [], findings)
    kept, dup2 = rc.dedupe_options(excl, [o["text"] for o in options if o["kind"] == "finding_negative"], findings)
    options += kept
    options, capped = cap_options(options)
    for o in excl:
        out = "duplicate_dropped" if o not in kept else ("capped" if o in capped else "offered")
        dec["case_exclusions"].append({"text": o["text"], "differential": o["finding"], "outcome": out})
    dec["duplicates_dropped"] = dup + dup2
    dec["capped"] = [{"kind": o["kind"], "text": o["text"]} for o in capped]
    return options, dec


# ─────────────────────────────────────────────────────────────────────────────
# Generate (arm E)
# ─────────────────────────────────────────────────────────────────────────────

async def vet_options(options: List[dict], report: str, impression: str, findings: str, scan_type: str
                      ) -> Tuple[List[dict], List[dict]]:
    """(kept, dropped). The post-generation check's option rules, asked beside it: an option sentence the dictation
    contradicts is dropped (Q_CONTRA, CONTRA_FLAG), and so is one the report already states (the uniqueness gate:
    finding negatives against the report, impression items against the conclusion). Three Jev calls in parallel;
    each fails open, as in the check."""
    if not options:
        return [], []
    contra_qs = {f"u{i}": {"type": "noul", "instructions": Q_CONTRA + (o.get("sentence") or o.get("text") or "")}
                 for i, o in enumerate(options)}
    gate_qs = rc.gate_questions(options)
    contra, in_report, in_imp = await asyncio.gather(
        rc.gate_scores(f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        rc.gate_scores(f"REPORT:\n{report}", gate_qs["report"]),
        rc.gate_scores(f"CONCLUSION:\n{impression}", gate_qs["impression"]))
    conveys = {**in_report, **in_imp}
    kept, dropped = [], []
    for i, o in enumerate(options):
        c, u = contra.get(f"u{i}"), conveys.get(f"u{i}")
        if c is not None and c >= CONTRA_FLAG:
            dropped.append({**o, "outcome": "contradicted", "score": round(c, 3)})
        elif u is not None and u >= rc.ALREADY_DROP:
            dropped.append({**o, "outcome": "already_in_report", "score": round(u, 3)})
        else:
            kept.append(o)
    return kept, dropped


async def generate_template_report_lean(*, sheet: str, scan_type: str, findings: str, history: str,
                                        case: "Optional[dict] | Callable[[], Awaitable[Optional[dict]]]",
                                        signature: Optional[str]) -> dict:
    """Today's single-pass generator on the stored sheet, then the post-generation check (sections from the
    report's own headers). Returns as soon as the check has finished: the report never waits for options.
    Phase-1 options are routed and written beside the generator and vetted (vet_options) after it, in the
    returned `options_job` (an asyncio task the caller finishes in the background; it resolves to
    {"options", "gate_dropped", "options_raw", "case_decisions", "phase1_used", "lat"} and may raise).
    `case` is the stored Phase 1 case_result (template_pipeline.phase1_record), None, or an async callable
    returning it: then Phase 1 is resolved inside the options job (no prepare: Phase 1 runs on and is stored)."""
    rec: dict = {"lat": {}}
    t_start = time.time()
    style = "\n".join(x for x in (_block(sheet, "Impression Construction Rules") or _block(sheet, "Impression Construction"),
                                  _block(sheet, "Terminology Rules")) if x)

    async def gen():
        t0 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history})
        rec["lat"]["generator_s"] = round(time.time() - t0, 1)
        return out

    job: dict = {"phase1_used": False, "lat": {}}   # the options job's own record (never the report's)

    async def opts():
        t0 = time.time()
        resolved = await case() if callable(case) else case
        job["phase1_used"] = bool(resolved)
        job["lat"]["phase1_wait_s"] = round(time.time() - t0, 1)
        raw, dec = await case_options(resolved, findings, scan_type, history, findings_section="FINDINGS",
                                      impression_section="IMPRESSION", inclusion_logic=style)
        t1 = time.time()
        written = await write_options(raw, findings, scan_type, model=MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"],
                                      runner=_run_agent_with_model, style=style, impression_section="IMPRESSION",
                                      require_service=True)
        job["lat"]["route_s"], job["lat"]["options_s"] = round(t1 - t0, 1), round(time.time() - t1, 1)
        return written, raw, dec

    opts_t = asyncio.ensure_future(opts())
    try:
        out = await gen()
    except BaseException:
        opts_t.cancel()
        raise
    report = out["report_content"]
    rec["report_generated"] = report

    # Sections come from the generated report; options are placed in its findings / impression sections
    sections = report_sections(report, sheet)
    imp = next((s.name for s in sections if s.role == "impression"), None)
    impression = _split_report(report, sections, imp) if imp else ""

    async def checked():
        t0 = time.time()
        res = await run_quality_check(report, findings, scan_type, [], sections=sections, protected=[],
                                      suppressed=[], history=None)
        rec["lat"]["check_s"] = round(time.time() - t0, 1)
        return res

    async def vetted() -> dict:
        written, raw, dec = await opts_t
        for o in written:
            o["section"] = option_section(o, sections)
        t0 = time.time()
        kept, dropped = await vet_options(written, report, impression, findings, scan_type)
        job["lat"]["vet_s"] = round(time.time() - t0, 2)
        job["lat"]["options_ready_s"] = round(time.time() - t_start, 1)   # from generate start
        return {"options": kept, "gate_dropped": dropped, "options_raw": raw, "case_decisions": dec,
                "phase1_used": job["phase1_used"], "lat": dict(job["lat"])}

    vet_t = asyncio.ensure_future(vetted())
    try:
        final, checked_opts, quality = await checked()
    except BaseException:
        vet_t.cancel()
        opts_t.cancel()
        raise
    if signature:
        final = final.rstrip() + "\n\n" + signature
    rec["lat"]["generate_s"] = round(time.time() - t_start, 1)
    rec.update({
        "report_content": final, "model_used": out.get("model_used"), "description": out.get("description"),
        "scan_type": out.get("scan_type") or scan_type, "brief_used": False, "brief_text": None,
        "brief_decisions": None, "case_decisions": None, "options_raw": [], "options": [],
        "gate_dropped": [], "options_pending": True, "options_job": vet_t, "quality_check": quality,
        "sections": [s.name for s in sections], "phase1_used": False, "history_inserted": False,
        "signature": signature or "",
    })
    return rec
