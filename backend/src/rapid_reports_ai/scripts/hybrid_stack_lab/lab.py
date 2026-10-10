"""Hybrid dictation stack lab: Verbatim's words with Structured's grouping.

One scratchpad text (the verbatim dictation) and a grouper that returns labels only — never
text. Code assembles the grouped view, so the words cannot change by construction. The
grouping unit is the sentence: v2 appends each final onto the open line, so the verbatim text
is running prose, not one finding per line.

Per case: each utterance is spoken by macOS `say`, transcribed by Deepgram batch (nova-3-medical,
the prod parameters), and written into the scratchpad the way the v2 package does (fast-append
as said; the lean span polish when a correction cue is present). After every utterance the
grouper places the new sentences; placed sentences stay put (sticky). At the end a fresh pass
regroups everything from scratch, to see how much the sticky placement depends on order.

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_lab.lab [case_id ...]

Outputs go to $LAB_OUT (default ./hybrid_stack_out): one JSON per case and report.md.
Deviations from prod: no Jev band router (code decides fast-append vs polish by the cue), no
two-pass ASR, no case keyterms (core keyterms only), the whole text is the polish span.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(".env")

from rapid_reports_ai.canvas_routes import (  # noqa: E402
    LEAN_FALLBACK_MODEL, LEAN_MODEL, LEAN_SETTINGS, SECTIONS_SYSTEM_PROMPT, SECTIONS_USER_PROMPT_TEMPLATE,
    CanvasIncrementalResponse, SectionGenerateResponse, _run_canvas_with_fallback,
)
from rapid_reports_ai.case_keyterms import merge_with_core  # noqa: E402
from rapid_reports_ai.deepgram_spelling import UK_SPELLING  # noqa: E402
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG  # noqa: E402
from rapid_reports_ai.fast_append import clean_verbatim  # noqa: E402
from rapid_reports_ai.scripts.hybrid_stack_lab.conclusion_boundary_lab import ask_boundary  # noqa: E402
from rapid_reports_ai.spoken_format import heading_only  # noqa: E402
from rapid_reports_ai.lean_fidelity import CORRECTION_CUE, fidelity_violation, verbatim_append  # noqa: E402
from rapid_reports_ai.lean_polish import LEAN_SYSTEM_PROMPT, LEAN_USER_TEMPLATE  # noqa: E402

HERE = Path(__file__).parent
OUT = Path(os.environ.get("LAB_OUT", "hybrid_stack_out"))
AUDIO_CACHE = OUT / "audio"
EXTRA_FIRST = ["Technique"]
EXTRA_LAST = ["General", "Conclusion"]
GROUPER_SETTINGS = {"temperature": 0.0, "max_tokens": 4000, "reasoning_effort": "none"}
GROUPER_ENDPOINTS = [
    ("https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY", "qwen-3.8-27b"),
    ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", "qwen/qwen3.8-27b"),
]

# --- speech -----------------------------------------------------------------------------


def speak(text: str, voice: str) -> bytes:
    """macOS TTS → 16 kHz mono WAV, cached by voice and text."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    key = "v2_" + re.sub(r"\W+", "_", f"{voice}_{text}")[:120] + f"_{abs(hash((voice, text))) % 10**8}.wav"
    path = AUDIO_CACHE / key
    if not path.exists():
        with tempfile.TemporaryDirectory() as d:
            aiff = Path(d) / "u.aiff"
            # Leading and trailing silence: without it Deepgram drops the first word ("No", "Impression").
            subprocess.run(["say", "-v", voice, "-r", "175", "-o", str(aiff), f"[[slnc 600]] {text} [[slnc 400]]"],
                           check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(path)],
                           check=True)
    return path.read_bytes()


async def deepgram(c: httpx.AsyncClient, wav: bytes, keyterms: list[str]) -> str:
    params = [("model", "nova-3-medical"), ("language", "en-GB"), ("smart_format", "true"), ("numerals", "true"),
              ("measurements", "true"), ("mip_opt_out", "true")] + [("keyterm", k) for k in keyterms] \
             + [("replace", f"{a}:{b}") for a, b in UK_SPELLING.items()]
    r = await c.post("https://api.deepgram.com/v1/listen", params=params, content=wav,
                     headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"})
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


# --- the verbatim scratchpad (v2-like) ------------------------------------------------------


async def write_utterance(text: str, heard: str, scan_type: str) -> tuple[str, str]:
    """Returns (new text, route). Fast-append as said; the lean polish when a correction cue
    is present, falling back to as-said on a fidelity violation (as prod)."""
    new = clean_verbatim(heard).strip()
    if not new:
        return text, "empty"
    if not CORRECTION_CUE.search(new):
        return verbatim_append(text, new), "fast_append"
    try:
        out = await _run_canvas_with_fallback(
            LEAN_MODEL, LEAN_FALLBACK_MODEL, output_type=CanvasIncrementalResponse,
            system_prompt=LEAN_SYSTEM_PROMPT,
            user_prompt=LEAN_USER_TEMPLATE.format(scan_type=scan_type, context="", span=text, new=new),
            model_settings=LEAN_SETTINGS, use_thinking=False, label="lab.polish")
    except Exception:
        return verbatim_append(text, new), "polish_failed"
    if fidelity_violation(text, new, out.active_scratchpad, out.committed_edits or []):
        return verbatim_append(text, new), "polish_fidelity_fallback"
    return out.active_scratchpad.strip(), "polish"


_SPLIT = re.compile(r"(?<=[.?!])\s+(?=\S)|\n+")


def sentences(text: str) -> list[str]:
    """Sentence units: break at . ? ! followed by whitespace (so decimals stay whole) and at line breaks."""
    return [s.strip() for s in _SPLIT.split(text or "") if s.strip()]


# --- the grouper ------------------------------------------------------------------------------

GROUPER_SYSTEM = """You organise a radiologist's dictation into report groups. You never write or change text: you only give each sentence a label. Code places the radiologist's own sentences under your labels.

Input: the scan type, the ordered list of GROUPS, the sentences already PLACED (with their groups; context only, fixed), and the NEW sentences to place, each with an id.

For each NEW sentence return:
- group: exactly one name from GROUPS.
- attach_to: the id of an earlier sentence (placed or new) when this sentence cannot stand on its own because it continues that sentence's observation: it refers back to it ("it", "this", "the lesion") or only adds a further attribute of the same observation (size, behaviour on another sequence or phase, effect it causes). A fragment with no verb of its own that completes the sentence just before it attaches to that sentence. Otherwise null. An attached sentence takes its parent's group; give the parent's group.
- new_group: normally empty. Only when the sentence is about a specific structure or space and no group in GROUPS is anatomically close, give a short uppercase name for a new group (the structure's usual report heading) and put the same name in group. Check NEW groups created earlier in PLACED before making another.
- parts: only when one sentence joins independent clauses about structures that belong to different groups, each clause with its own subject and its own predicate (two statements run together in one breath). Give each part as an exact, unaltered, contiguous piece of the sentence, in order, each with its own group. The parts together must cover the whole sentence: keep joining words and punctuation on the neighbouring part. Every part must read as a complete statement on its own. Two statements run together because a full stop is missing count as two clauses. Never split structures that share one predicate (a list of structures followed by a single "are normal" / "are intact" / "are clear"): that sentence stays whole, in the group of its first structure, or General when it covers many groups. A single observation that involves several structures (a finding extending into, invading or compressing a neighbour) is one claim: never split it. Leave parts empty otherwise.

Placement rules:
- One home: the group of the structure the observation is about — where the abnormality is, not what it touches or affects.
- Interpretation attached to a single observation ("in keeping with", "likely", a classification of that one finding) stays with that observation.
- Conclusion: once the radiologist has begun the conclusion (a spoken cue, or a closing summary), every following sentence belongs to Conclusion too, including short restatements of single findings, until the radiologist clearly returns to describing the images in detail. A sentence that is only the cue word itself also belongs to Conclusion.
- Conclusion also takes: the radiologist's overall summary, diagnosis across findings, differential, staging summary, recommendation or advice, and anything introduced by a spoken summary cue (impression, conclusion, in summary, overall, so). Also a sentence that restates findings already placed as a closing summary, even without a cue.
- Technique: protocol, sequences, contrast, phases, image quality, limitations, and which prior studies were compared.
- General: only a sweeping statement that names no specific structure ("no other abnormality", "the rest is normal"), or a list of structures in several groups sharing one predicate. A statement about one named structure or space never goes to General: use its anatomical group, the closest one, or a new group.
- A comparison with a prior study about one finding belongs with that finding's structure.
- Never split structures that share one predicate; such a sentence goes to the group of its first structure when its structures sit in one or two neighbouring groups, General when they span many.

Return one entry per NEW sentence, in order."""

GROUPER_SYSTEM_SCHEMA = GROUPER_SYSTEM.replace(
    """- new_group: normally empty. Only when the sentence is about a specific structure or space and no group in GROUPS is anatomically close, give a short uppercase name for a new group (the structure's usual report heading) and put the same name in group. Check NEW groups created earlier in PLACED before making another.""",
    """- structure: the specific structure the sentence is about, in a few words (for example the organ, vessel, level or space); empty for Technique, General and Conclusion.

- covers: the regions (names from GROUPS, never Technique, General or Conclusion) about which the sentence makes a definitive claim — a finding, a measurement, a qualifier or an explicit normality statement. Count a region when the claim is direct (its structure is the subject, the location, or the modifier of the claim) or collective (a definitive claim over a recognisable anatomical group, such as several named organs or a named organ system, that the region's structures genuinely belong to). Do not count: a bare mention with nothing asserted; a structure only touched or affected by a finding about another structure; a vague statement with no anatomical scope ("no other abnormality", "otherwise normal"); a group the region does not clearly belong to. Usually the sentence's own region; several for a collective; empty when nothing qualifies. Fill covers for every sentence, including Conclusion sentences.

GROUPS are broad regions of a fixed schema; each lists what it includes. Match the structure to the region whose list covers it, or the anatomically closest region; use the "Other findings" region only when no region is close.""").replace(
    "A statement about one named structure or space never goes to General: use its anatomical group, the closest one, or a new group.",
    "A statement about one named structure or space never goes to General: use its region.")
assert GROUPER_SYSTEM_SCHEMA != GROUPER_SYSTEM

GROUPER_USER = """Scan type: {scan_type}

GROUPS (in report order):
{groups}

PLACED (fixed, context only):
{placed}

NEW:
{new}"""


class Part(BaseModel):
    text: str
    group: str


class Placement(BaseModel):
    id: int
    group: str
    structure: str | None = None
    covers: list[str] = Field(default_factory=list)
    new_group: str | None = None
    attach_to: int | None = None
    parts: list[Part] = Field(default_factory=list)


class GrouperOut(BaseModel):
    placements: list[Placement]


# Lab variant of the prod sections prompt (canvas_routes.SECTIONS_USER_PROMPT_TEMPLATE): two structural
# additions, inserted before the output rules. Prod is untouched until this is measured.
SECTIONS_ADDITIONS = """6. **Unknown patient-specific anatomy**: when the field of view contains organs that differ between patients (for example by sex) and the scan type and clinical history do not say which apply, use one neutral section for that compartment rather than guessing.

7. **Regions reported unit by unit**: when a region is conventionally reported as a sequence of repeated units (levels, segments, compartments), list those units as sections in order, plus one section for what spans them.

"""
SECTIONS_VARIANT = os.environ.get("LAB_SECTIONS", "v2")  # "prod" for the unmodified prompt


def sections_prompt(scan_type: str, history: str) -> str:
    base = SECTIONS_USER_PROMPT_TEMPLATE.format(scan_type=scan_type, clinical_history=history)
    if SECTIONS_VARIANT == "prod":
        return base
    return base.replace("## OUTPUT RULES", SECTIONS_ADDITIONS + "## OUTPUT RULES")


# Uppercase output with reasoning on corrupted names on Cerebras Qwen ("MEDIASTINUM" -> "MEDIUMIUM" in
# 11/12 lists); Title Case did not (0/12). Code uppercases afterwards.
TITLE_CASE = ('\n\nOverride for this reply: write each section name in Title Case (e.g. "Lungs And Pleura"), '
              'not uppercase.')


async def _sections_reasoned(scan_type: str, history: str) -> list[str]:
    """The sections call with reasoning on (the prompt's pre-output analysis needs it), plain JSON mode."""
    body = {"model": "qwen-3.8-27b", "temperature": 0.1, "max_tokens": 6000, "reasoning_effort": "medium",
            "messages": [{"role": "system", "content": SECTIONS_SYSTEM_PROMPT},
                         {"role": "user", "content": sections_prompt(scan_type, history) + TITLE_CASE
                          + '\n\nReply as JSON: {"sections": [...]}'}],
            "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=90) as c:
        for attempt in range(4):
            r = await c.post("https://api.cerebras.ai/v1/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {os.environ['CEREBRAS_API_KEY']}"})
            if r.status_code == 429:
                await asyncio.sleep(2 + 3 * attempt)
                continue
            r.raise_for_status()
            data = json.loads(r.json()["choices"][0]["message"]["content"])
            secs = data if isinstance(data, list) else next(v for v in data.values() if isinstance(v, list))
            if secs and all(isinstance(x, str) for x in secs):
                return secs
            raise ValueError("no section list")
    raise RuntimeError("rate limited")


async def section_groups(scan_type: str, history: str) -> list[str]:
    """The section list (the coverage call), bracketed by the fixed extra groups. LAB_SECTIONS=prod
    runs today's call (reasoning off); otherwise the reasoned v2 call, falling back to today's."""
    secs = None
    if SECTIONS_VARIANT != "prod":
        try:
            secs = await _sections_reasoned(scan_type, history)
        except Exception as e:
            print(f"[sections] reasoned call failed ({type(e).__name__}); prod call", file=sys.stderr)
    if secs is None:
        out = await _run_canvas_with_fallback(
            MODEL_CONFIG["CANVAS_SECTIONS"], MODEL_CONFIG["CANVAS_SECTIONS_FALLBACK"],
            output_type=SectionGenerateResponse, system_prompt=SECTIONS_SYSTEM_PROMPT,
            user_prompt=sections_prompt(scan_type, history),
            model_settings={"temperature": 0.1, "max_tokens": 1000, "reasoning_effort": "none"}, label="lab.sections")
        secs = out.sections
    low = {g.lower() for g in EXTRA_FIRST + EXTRA_LAST} | {"findings", "impression", "background"}
    anat, seen = [], set()
    for x in secs:  # dedupe (a looping list was seen) and drop non-anatomical headings
        k = x.strip().upper()
        if k and k.lower() not in low and k not in seen:
            seen.add(k)
            anat.append(k)
    return EXTRA_FIRST + anat + EXTRA_LAST


# --- visual schema groups ----------------------------------------------------------------------

GROUP_MODE = os.environ.get("LAB_GROUPS", "schema")  # "schema" (fixed visual regions) | "sections" (the /sections call)
SCHEMAS = json.loads((HERE / "schemas.json").read_text())


def family_regions(family: str) -> list[tuple[str, str]]:
    """(name, includes) for a family, levels expanded."""
    out = []
    for key in SCHEMAS["families"][family]["regions"]:
        if key.startswith("@"):
            out += [(lvl, SCHEMAS["level_includes"]) for lvl in SCHEMAS["levels"][key[1:]]]
        else:
            r = SCHEMAS["regions"][key]
            out.append((r["name"], r["includes"]))
    return out


NONE_FAMILY = "none"


async def choose_family(scan_type: str, history: str) -> tuple[str, float]:
    """Jev maps the free-text scan type to a schema family (distinct options: Jev's strength), or
    "none" when no family describes it. Confidence alone did not flag a missing family (cardiac MRI
    went to "chest" at 1.0), hence the explicit option."""
    from rapid_reports_ai.jev_client import JEV_MODEL, jev_post
    crit = {k: v["description"] for k, v in SCHEMAS["families"].items()}
    crit[NONE_FAMILY] = ("None of the other options describes this examination: a different body part, joint, "
                         "organ-specific or specialist examination that the options do not name.")
    q = {"type": "choice", "instructions": "Which kind of examination is this?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"Scan type: {scan_type}\nClinical history: {history}",
                        "questions": {"family": q}}, os.environ["OPENROUTER_API_KEY"], 10.0)
    r.raise_for_status()
    a = r.json()["answers"]["family"]
    return a["choice"], float(a.get("confidence") or 0.0)


# --- reconciler: a family for a scan type no family describes ----------------------------------

RECONCILE_SYSTEM = """You build the region list for a radiology examination's visual schema. Regions are broad zones a radiologist reports one by one; each region lists what it includes."""

RECONCILE_USER = """Scan type: {scan_type}
Clinical history: {history}

FAMILIES (key — what it is for — its regions):
{families}

REGION LIBRARY (key — name — includes):
{library}

If one family above already gives this examination a useful region list as it stands (its regions match what this examination reports, at the right level of detail), reply {{"family": "<family key>"}}.

Otherwise build the ordered region list for this examination, in the order a radiologist reports it:
- Reuse a library region (by its key) wherever it fits this examination as it is.
- Add a new region only for a structure or compartment this examination reports separately and no library region covers. Give it a short name and an includes list in the same style.
- Keep regions broad: one region per structure or compartment the radiologist would report on its own line, typically 6 to 12 regions. Include structures incidentally in the field of view as one region.
- When anatomy differs between patients and the scan type does not say which applies, use one neutral region.
- Do not add Technique, Conclusion, General, Other or Incidental regions: they always exist, and incidental findings outside the listed regions go to "Other findings".
- Write names in Title Case.

Reply as JSON: either {{"family": "<family key>"}} or {{"regions": [{{"key": "<library key>"}} or {{"name": "<new name>", "includes": "<what it includes>"}}]}}"""

MAX_NEW_REGIONS = 8
_RECONCILED: dict[str, list[tuple[str, str]]] = {}  # cache by normalised scan type (lab: per process)


async def reconcile_family(scan_type: str, history: str) -> tuple[list[tuple[str, str]], dict]:
    """(regions, log): reused library regions plus new ones, validated in code, cached by scan type."""
    key = re.sub(r"\s+", " ", scan_type.strip().lower())
    if key in _RECONCILED:
        return _RECONCILED[key], {"cached": True}
    lib = "\n".join(f"{k} — {v['name']} — {v['includes']}" for k, v in SCHEMAS["regions"].items() if k != "other")
    fams = "\n".join(f"{k} — {v['description']} — {', '.join(n for n, _ in family_regions(k))}"
                      for k, v in SCHEMAS["families"].items())
    body = {"model": "qwen-3.8-27b", "temperature": 0.1, "max_tokens": 8000, "reasoning_effort": "medium",
            "messages": [{"role": "system", "content": RECONCILE_SYSTEM},
                         {"role": "user", "content": RECONCILE_USER.format(scan_type=scan_type, history=history, library=lib, families=fams)}],
            "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=120) as c:
        for attempt in range(4):
            r = await c.post("https://api.cerebras.ai/v1/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {os.environ['CEREBRAS_API_KEY']}"})
            if r.status_code != 429:
                break
            await asyncio.sleep(2 + 3 * attempt)
        r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    if out.get("family") in SCHEMAS["families"]:
        _RECONCILED[key] = family_regions(out["family"])
        return _RECONCILED[key], {"cached": False, "family": out["family"]}
    items = out["regions"]
    regions, seen, reused, new, dropped = [], set(), [], [], []
    for it in items:
        if it.get("key") in SCHEMAS["regions"] and it["key"] != "other":
            name, inc = SCHEMAS["regions"][it["key"]]["name"], SCHEMAS["regions"][it["key"]]["includes"]
            reused.append(it["key"])
        elif it.get("name") and it.get("includes") and len(new) < MAX_NEW_REGIONS:
            name, inc = it["name"].strip(), it["includes"].strip()
            new.append(name)
        else:
            dropped.append(it)
            continue
        if name.lower() in seen or name.lower() in {"technique", "conclusion", "general", "other findings",
                                                     "incidental findings", "other", "incidental"}:
            dropped.append(it)
            continue
        seen.add(name.lower())
        regions.append((name, inc))
    regions.append((SCHEMAS["regions"]["other"]["name"], SCHEMAS["regions"]["other"]["includes"]))
    _RECONCILED[key] = regions
    return regions, {"cached": False, "reused": reused, "new": new, "dropped": dropped}


def _norm_group(g: str, groups: list[str]) -> str | None:
    for x in groups:
        if x.lower() == (g or "").strip().lower():
            return x
    return None


def valid_parts(sentence: str, parts: list[Part]) -> bool:
    """Parts are exact pieces of the sentence that together cover all of it, in order (only
    whitespace between them): nothing the radiologist said can fall between two parts."""
    pos = 0
    for p in parts:
        if not p.text.strip():
            return False
        i = sentence.find(p.text, pos)
        if i < 0 or sentence[pos:i].strip():
            return False
        pos = i + len(p.text)
    return len(parts) >= 2 and not sentence[pos:].strip()


async def group_new(scan_type: str, groups: list[str], units: list[dict], new_ids: list[int],
                    includes: dict[str, str] | None = None) -> tuple[list[Placement], float, str | None]:
    placed = "\n".join(f"[{u['id']}] ({u['group']}) {u['text']}" for u in units if u["id"] not in new_ids) or "(none)"
    new = "\n".join(f"[{u['id']}] {u['text']}" for u in units if u["id"] in new_ids)
    listing = "\n".join(f"{g} — includes: {includes[g]}" if includes and g in includes else g for g in groups)
    user = GROUPER_USER.format(scan_type=scan_type, groups=listing, placed=placed, new=new)
    system = GROUPER_SYSTEM_SCHEMA if includes else GROUPER_SYSTEM
    t0, err = time.perf_counter(), None
    for url, key, model in GROUPER_ENDPOINTS:  # pydantic-ai tool output fails on this nested schema with Qwen
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, headers={"Authorization": f"Bearer {os.environ[key]}"}, json={
                    "model": model, **GROUPER_SETTINGS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_schema", "json_schema": {
                        "name": "placements", "schema": GrouperOut.model_json_schema()}}})
                r.raise_for_status()
                out = GrouperOut.model_validate_json(r.json()["choices"][0]["message"]["content"])
            return out.placements, time.perf_counter() - t0, err
        except Exception as e:
            err = f"{model}: {type(e).__name__}: {e}"
    return [], time.perf_counter() - t0, err


def apply_placements(units: list[dict], placements: list[Placement], new_ids: list[int], groups: list[str],
                     new_groups: list[str]) -> list[str]:
    """Writes group/attach/parts onto the new units (may add a group to `groups`); returns problems."""
    problems, by_id = [], {u["id"]: u for u in units}
    got = {p.id: p for p in placements if p.id in new_ids}
    for i in new_ids:
        u, p = by_id[i], got.get(i)
        if p is None:
            u.update(group="General", attach_to=None, parts=None)
            problems.append(f"[{i}] no placement")
            continue
        if GROUP_MODE == "schema":
            p.new_group = None  # the schema has an "Other findings" region instead
        if p.new_group and _norm_group(p.new_group, groups) is None:  # an escape for gaps in the list
            groups.insert(groups.index("General"), p.new_group.strip().upper())
            new_groups.append(f"[{i}] {p.new_group.strip().upper()}")
        g = _norm_group(p.new_group or p.group, groups) or _norm_group(p.group, groups)
        if g is None:
            problems.append(f"[{i}] unknown group {p.group!r}")
            g = "General"
        att = p.attach_to if p.attach_to in by_id and p.attach_to != i and p.attach_to < i else None
        if p.attach_to is not None and att is None:
            problems.append(f"[{i}] bad attach_to {p.attach_to}")
        parts = None
        if p.parts:
            pg = [(_norm_group(x.group, groups) or "General") for x in p.parts]
            if valid_parts(u["text"], p.parts) and len(set(pg)) > 1:
                parts = [{"text": x.text, "group": g2} for x, g2 in zip(p.parts, pg)]
            else:
                problems.append(f"[{i}] rejected parts {[x.text for x in p.parts]}")
        u.update(group=by_id[att]["group"] if att is not None else g, attach_to=att, parts=parts,
                 model_group=g, structure=p.structure,
                 covers=[c for c in (_norm_group(x, groups) for x in p.covers)
                         if c and c not in ("Technique", "General", "Conclusion")])
    return problems


BOUNDARY_MIN_CONF = 0.6  # lab: wrong answers were all below 0.6 (0.24, 0.56) on conclusion_boundary.json


async def conclusion_gate(units: list[dict], new_ids: list[int]) -> list[dict]:
    """Once the conclusion has begun, Jev decides whether each new sentence after it is part of the
    conclusion or a return to the images. Below BOUNDARY_MIN_CONF, or on failure, the grouper's
    placement stands. Returns the decisions for the log."""
    started, asks = False, []
    for k, u in enumerate(units):
        if u["id"] in new_ids and started and not heading_only(u["text"]):
            asks.append((k, u))
        if u.get("group") == "Conclusion":
            started = True
    if not asks:
        return []

    async def one(k, u):
        try:
            return u, *(await ask_boundary([x["text"] for x in units[:k]], u["text"]))
        except Exception as e:
            return u, f"error {type(e).__name__}", 0.0
    log = []
    for u, choice, conf in await asyncio.gather(*(one(k, u) for k, u in asks)):
        before = u["group"]
        if conf >= BOUNDARY_MIN_CONF and choice == "summary" and before != "Conclusion":
            u.update(group="Conclusion", attach_to=None, parts=None)
        elif conf >= BOUNDARY_MIN_CONF and choice == "images" and before == "Conclusion":
            u.update(group="General", attach_to=None, parts=None)  # no anatomical label to hand: logged
        log.append({"id": u["id"], "choice": choice, "conf": round(conf, 2), "from": before, "to": u["group"]})
    return log


def render(units: list[dict], groups: list[str]) -> str:
    """The grouped view, in group order; sentences in dictated order; attached sentences under their parent."""
    rows: dict[str, list[str]] = {g: [] for g in groups}
    children: dict[int, list[dict]] = {}
    for u in units:
        if u.get("attach_to") is not None:
            children.setdefault(u["attach_to"], []).append(u)
    for u in units:
        if u.get("attach_to") is not None or heading_only(u["text"]):  # a cue word is the heading itself
            continue
        if u.get("parts"):
            for p in u["parts"]:
                rows[p["group"]].append(f"- {p['text']}  ⟨part of [{u['id']}]⟩")
        else:
            rows[u["group"]].append(f"- {u['text']}" + (f"  · {u['structure']}" if u.get("structure") else ""))
        for ch in children.get(u["id"], []):
            rows[u["group"] if not u.get("parts") else u["parts"][0]["group"]].append(f"    ↳ {ch['text']}")
    return "\n".join(f"{g.upper()}\n" + "\n".join(r) + "\n" for g, r in rows.items() if r)


# --- one case ---------------------------------------------------------------------------------


async def run_case(c: httpx.AsyncClient, case: dict, keyterms: list[str]) -> dict:
    includes, family = None, None
    if GROUP_MODE == "schema":
        family = await choose_family(case["scan_type"], case["clinical_history"])
        if family[0] == NONE_FAMILY or os.environ.get("LAB_FORCE_RECONCILE") == "1":
            regions, rec_log = await reconcile_family(case["scan_type"], case["clinical_history"])
            family = (family[0], family[1], rec_log)
        else:
            regions = family_regions(family[0])
        groups = EXTRA_FIRST + [n for n, _ in regions] + EXTRA_LAST
        includes = dict(regions)
    else:
        groups = await section_groups(case["scan_type"], case["clinical_history"])
    base_groups, new_groups = list(groups), []
    text, units, steps = "", [], []
    next_id = 0
    for utt in case["utterances"]:
        heard = await deepgram(c, speak(utt, case["voice"]), keyterms)
        text, route = await write_utterance(text, heard, case["scan_type"])
        # Re-key units against the new text: an unchanged sentence keeps its id and placement.
        old = {}
        for u in units:
            old.setdefault(u["text"], []).append(u)
        fresh_units, new_ids = [], []
        for s in sentences(text):
            if old.get(s):
                fresh_units.append(old[s].pop(0))
            else:
                fresh_units.append({"id": next_id, "text": s})
                new_ids.append(next_id)
                next_id += 1
        dropped = [u["text"] for v in old.values() for u in v]  # sentences the polish rewrote away
        units = fresh_units
        for u in units:  # an attach to a dropped sentence is cut
            if u.get("attach_to") is not None and all(x["id"] != u["attach_to"] for x in units):
                u["attach_to"] = None
        placements, dt, err = (await group_new(case["scan_type"], groups, units, new_ids, includes)) if new_ids else ([], 0.0, None)
        problems = apply_placements(units, placements, new_ids, groups, new_groups) if new_ids else []
        gate = await conclusion_gate(units, new_ids) if new_ids else []
        steps.append({"said": utt, "heard": heard, "route": route, "new_ids": new_ids, "dropped": dropped,
                      "grouper_s": round(dt, 2), "error": err, "problems": problems, "gate": gate})
    sticky_view = render(units, groups)

    # Fresh pass: everything regrouped at once, for comparison with the sticky (live) placement.
    fresh = [{"id": u["id"], "text": u["text"]} for u in units]
    fresh_groups, fresh_new = list(base_groups), []
    placements, dt, err = await group_new(case["scan_type"], fresh_groups, fresh, [u["id"] for u in fresh], includes)
    fresh_problems = apply_placements(fresh, placements, [u["id"] for u in fresh], fresh_groups, fresh_new)
    fresh_gate = await conclusion_gate(fresh, [u["id"] for u in fresh])
    disagree = [{"id": a["id"], "text": a["text"], "sticky": a["group"], "fresh": b["group"]}
                for a, b in zip(units, fresh) if a["group"] != b["group"]]

    # Coverage pills: derived from the grouping (union of covers) vs prod's Jev coverage on the same regions.
    coverage = None
    if includes:
        # "Other findings" is a catch-all, not a checklist item: no pill.
        regions = [g for g in base_groups if g not in ("Technique", "General", "Conclusion", "Other findings")]
        derived = sorted({c for u in units for c in (u.get("covers") or [])})
        try:
            from rapid_reports_ai.section_coverage import get_jev_coverage
            d = await get_jev_coverage().classify(text, regions, case["scan_type"])
            jev = sorted(d.covered)
            coverage = {"regions": regions, "derived": derived, "jev": jev, "scores": d.scores,
                        "only_derived": [r for r in derived if r not in jev],
                        "only_jev": [r for r in jev if r not in derived]}
        except Exception as e:
            coverage = {"error": f"{type(e).__name__}: {e}", "derived": derived}

    # Fidelity by construction: the units rebuild the text exactly (splits are checked by valid_parts).
    fidelity_ok = " ".join(u["text"] for u in units) == " ".join(text.split())

    checks = []
    for e in case["expect"]:
        hit = next((u for u in units if e["phrase"].lower() in u["text"].lower()), None)
        if hit is None:
            checks.append({**e, "result": "phrase not found"})
            continue
        grp = hit["group"]
        if hit.get("parts"):
            grp = next((p["group"] for p in hit["parts"] if e["phrase"].lower() in p["text"].lower()), grp)
        if "region" in e:  # strict (held-out): exact region names only
            ok_group = grp.lower() in {x.lower() for x in e["region"]}
        else:
            hay = (grp + " " + (includes or {}).get(grp, "")).lower()
            ok_group = any(s in hay for s in e["group"])
        ok_attach = (hit.get("attach_to") is not None) if e.get("attach") else True
        checks.append({**e, "got_group": grp, "attached": hit.get("attach_to"),
                       "result": "ok" if ok_group and ok_attach else ("wrong group" if not ok_group else "not attached")})
    return {"id": case["id"], "scan_type": case["scan_type"], "groups": groups, "family": family,
            "family_expected": case.get("family"), "coverage": coverage, "text": text, "units": units,
            "steps": steps, "view": sticky_view, "fresh_view": render(fresh, fresh_groups), "new_groups": new_groups, "fresh_new_groups": fresh_new, "fresh_gate": fresh_gate, "fresh_error": err,
            "fresh_problems": fresh_problems, "fresh_disagree": disagree, "fidelity_ok": fidelity_ok,
            "checks": checks}


def report(results: list[dict]) -> str:
    lines = ["# Hybrid stack lab", ""]
    tot = sum(len(r["checks"]) for r in results)
    ok = sum(1 for r in results for x in r["checks"] if x["result"] == "ok")
    lat = sorted(s["grouper_s"] for r in results for s in r["steps"] if s["new_ids"])
    nunits = sum(len(r["units"]) for r in results)
    lines += [f"- Expectations met: **{ok}/{tot}**",
              (f"- Family (Jev): {sum(1 for r in results if r['family'] and r['family'][0] == r['family_expected'])}"
               f"/{len(results)} as expected" if results[0]["family"] else "- Groups: /sections call"),
              (lambda cov: f"- Coverage pills, derived vs Jev: agree on "
               f"{sum(len(c['regions']) - len(c['only_derived']) - len(c['only_jev']) for c in cov)}"
               f"/{sum(len(c['regions']) for c in cov)} region decisions "
               f"(only derived {sum(len(c['only_derived']) for c in cov)}, only Jev {sum(len(c['only_jev']) for c in cov)})")(
                  [r["coverage"] for r in results if r.get("coverage") and "regions" in r["coverage"]]),
              f"- Fidelity by construction held: {sum(r['fidelity_ok'] for r in results)}/{len(results)} cases",
              f"- Sticky vs fresh disagreements: {sum(len(r['fresh_disagree']) for r in results)}/{nunits} sentences",
              f"- Attached: {sum(1 for r in results for u in r['units'] if u.get('attach_to') is not None)}, "
              f"split: {sum(1 for r in results for u in r['units'] if u.get('parts'))}",
              f"- Grouper latency p50 {lat[len(lat)//2]:.2f}s, max {lat[-1]:.2f}s" if lat else "",
              f"- Polish routes: {sorted({s['route'] for r in results for s in r['steps']})}",
              f"- New groups created: {sum(len(r['new_groups']) for r in results)} live, "
              f"{sum(len(r['fresh_new_groups']) for r in results)} fresh",
              f"- Conclusion gate (Jev): {sum(len(s['gate']) for r in results for s in r['steps'])} asked live, "
              f"{sum(1 for r in results for s in r['steps'] for g in s['gate'] if g['from'] != g['to'])} changed",
              f"- Problems: {sum(len(s['problems']) for r in results for s in r['steps'])} live, "
              f"{sum(len(r['fresh_problems']) for r in results)} fresh", ""]
    for r in results:
        lines += [f"## {r['id']} — {r['scan_type']}", "", "Groups: " + " · ".join(r["groups"]), "",
                  "**Verbatim**", "", "> " + r["text"].replace("\n", "\n> "), "", "**Stack (live, sticky)**", "",
                  "```", r["view"].rstrip(), "```", ""]
        bad = [x for x in r["checks"] if x["result"] != "ok"]
        lines.append(f"Checks {len(r['checks']) - len(bad)}/{len(r['checks'])}" + (":" if bad else ""))
        lines += [f"- `{x['phrase']}` → {x['result']} (got {x.get('got_group')}, want {'/'.join(x.get('region') or x['group'])})" for x in bad]
        if r["new_groups"]:
            lines.append("New groups: " + "; ".join(r["new_groups"]))
        if r["fresh_disagree"]:
            lines.append("Fresh pass disagrees:")
            lines += [f"- [{d['id']}] {d['text'][:80]} — sticky {d['sticky']} / fresh {d['fresh']}" for d in r["fresh_disagree"]]
        asr = [(s["said"], s["heard"]) for s in r["steps"]]
        probs = [p for s in r["steps"] for p in s["problems"]] + [p for s in r["steps"] if s["dropped"] for p in [f"rewritten away: {s['dropped']}"]]
        if probs:
            lines.append("Problems: " + "; ".join(probs))
        lines += ["", "<details><summary>said → heard</summary>", ""] + [f"- {a}\n  → {b}" for a, b in asr] + ["", "</details>", ""]
    return "\n".join(lines)


async def main(argv: list[str]) -> None:
    cases = json.loads(Path(os.environ.get("LAB_CASES", HERE / "cases.json")).read_text())["cases"]
    if argv:
        cases = [c for c in cases if c["id"] in argv]
    OUT.mkdir(parents=True, exist_ok=True)
    keyterms = merge_with_core([])
    async with httpx.AsyncClient(timeout=60) as c:
        sem = asyncio.Semaphore(int(os.environ.get("LAB_CONCURRENCY", "4")))  # near-live grouper latency

        async def one(case: dict) -> dict:
            async with sem:
                return await run_case(c, case, keyterms)
        results = await asyncio.gather(*(one(case) for case in cases))
    for r in results:
        (OUT / f"{r['id']}_{os.getpid()}.json").write_text(json.dumps(r, indent=2))
    md = report(list(results))
    (OUT / f"report_{os.getpid()}.md").write_text(md)
    print(md.split("\n## ")[0])
    print(f"\nreport: {OUT / f'report_{os.getpid()}.md'}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
