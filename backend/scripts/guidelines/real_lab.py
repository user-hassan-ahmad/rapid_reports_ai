"""Real-dictation lab (library spec §12, "Draft card slice"). Production findings, read only through Metabase,
grouped offline by the stack grouper, matched to library packs by the live library path (matcher.library_cards);
truth from an independent Claude Opus 5.5 subagent holding every pack's sources (the controller dispatches it with the
brief this script writes); Hassan spot-checks the boundary items; the settler is measured. Metrics and
recommendations only: Hassan decides.
Everything stays in the output directory given on the command line, pid in each name; nothing from production is ever
committed, and no clinical text is ever logged.

  export  <dir>                       read-only SQL via Metabase           -> export_<pid>.json
  group   <export.json> <dir> [--per-pack 30 --total 100 --max-cases 400 --concurrency 2]
          [--cases selected.json]   only those export ids, in file order ({"selected": [{"id": ..}]}; --max-cases off)
          [--resume group_cases_<pid>.jsonl]   skip cases already done there, retry errored ones
                                      -> group_cases_<pid>.jsonl (checkpoint, a line per finished case) + cards_<pid>.json
  hassan  <cases.json> <cards.json> <dir> [--source hassan --concurrency 2] [--resume group_cases_<pid>.jsonl]
          dictations appended under a source (default hassan, ids h-<id>; otherwise <source>-<id>, e.g. synthetic)
                                      -> group_cases_<pid>.jsonl (checkpoint) + cards_<pid>.json
  brief   <cards.json> <dir>          the labelling brief for the subagent -> label_brief_<pid>.md
          (the controller dispatches the Opus 5.5 subagent; it writes labels_<pid>.json, once; reused)
  labels  <labels.json> <cards.json>  validate and load the subagent's labels
  run     <cards.json> <dir>          the settler as it stands             -> settler_<pid>.json
  sheet   <cards> <labels> <settler> <dir>                                 -> spotcheck_<pid>.csv
  score   <cards> <labels> <settler> <dir> [--verdicts spotcheck.csv]      -> score_<pid>.json + table
Reported against reference targets (0 wrong values shown as read; median taps to Calculate <= 2), never as a gate.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/real_lab.py <cmd> ..."""
import asyncio
import csv
import dataclasses
import importlib.util
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")    # model keys only, never the app database
load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai.hybrid_stack.copilot import matcher as M  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot import tnm  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library import quantity as Q  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import (  # noqa: E402
    EXAM_CARD, Drafted, _answer, _show, calculate, display_options, exam_presets, finish, preset_values, settle_pack,
    Settlement)
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, InputValue  # noqa: E402

MAX_FILL = 10
GUIDELINES = Path(__file__).resolve().parents[3] / "guidelines"      # absolute: the labeller is another agent
SQL = """select id::text as id,
  coalesce(input_data->'variables'->>'SCAN_TYPE', input_data->>'extracted_scan_type', '') as scan_type,
  coalesce(input_data->'variables'->>'CLINICAL_HISTORY', '') as clinical_history,
  input_data->'variables'->>'FINDINGS' as findings
from reports
where created_at > now() - interval '365 days' and input_data->'variables'->>'FINDINGS' is not null
order by created_at desc limit 2000"""

LABEL_INSTRUCTIONS = """You label radiology dictations against published guidelines, as the ground truth for a test.
For each card in CARDS, open its pack's entry.json and read its sources/ folder (the guideline's own documents) for
what each input means. For the card's FINDING, and for every input of its pack, decide what the dictation itself
states. An input is stated only when the FINDING (lesion inputs) or the CLINICAL HISTORY or DICTATION (patient inputs)
gives it in words; a value that is usual, likely or merely not contradicted is not stated.
For each input give: stated; value (exactly one of the input's listed values when stated, else null); quote (the
shortest verbatim span that states it, else ""); locator (where in the sources the input is defined, as "S<n> p<page>
<section or table>"); assumed (when not stated: the value a radiologist would most likely give from the whole report
and the images it describes, else null); boundary (true when a careful reader could label it differently); note.
Also give lesions (when the FINDING describes more than one lesion of any kind, the shortest verbatim span for each;
else []) and category (when the FINDING states the system's category by name: {label, quote}; else null).
You are read-only on code. Write one file only: the OUTPUT path below, as JSON in the SCHEMA below, with served_by set
to your model and agent id. Label every card; never skip one."""


class LabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str
    stated: bool
    value: str | None
    quote: str
    locator: str
    assumed: str | None
    boundary: bool
    note: str = ""


class LabelCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    quote: str


class CardLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[LabelInput]
    lesions: list[str] = Field(default_factory=list)
    category: LabelCategory | None = None


class LabelFile(BaseModel):
    """What the labelling subagent writes: labels_<pid>.json."""
    model_config = ConfigDict(extra="forbid")
    served_by: str = Field(min_length=1)          # the model and agent id that labelled
    labels: dict[str, CardLabel]                  # card id -> its label


def _coverage_lab():
    spec = importlib.util.spec_from_file_location("coverage_lab", Path(__file__).with_name("coverage_lab.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lib() -> LB.Library:
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _pid(d: Path, stem: str, ext: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stem}_{os.getpid()}.{ext}"


# ── export ──────────────────────────────────────────────────────────────────────────────────────────────────────

def export(out_dir: Path) -> Path:
    """Read-only SQL through Metabase /api/dataset (database 2). If Cloudflare refuses the script (1010), run SQL in
    the Chrome session's Metabase and save the JSON response as export_<pid>.json yourself."""
    import httpx
    r = httpx.post(os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
                   headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8",
                            "Content-Type": "application/json"},
                   json={"database": 2, "type": "native", "native": {"query": SQL}}, timeout=180)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise SystemExit(body["error"])
    p = _pid(out_dir, "export", "json")
    p.write_text(json.dumps(body))
    return p


# ── group ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def _cards_for(case: dict, sem: asyncio.Semaphore) -> list[dict]:
    from rapid_reports_ai.hybrid_stack import service as S
    async with sem:
        schema = await S.resolve_schema(case["scan_type"], case["clinical_history"], None, None)
        g = await S.group_update(case["scan_type"], case["findings"], schema.regions, [])
        fs = _coverage_lab().findings([u.model_dump() for u in g.units])
        if not fs:
            return []
        # The live path itself (matcher.library_cards, as /match runs it): the case request, one request per finding,
        # and the shared card builder (exam cards, TNM, modality filter, merge, caps). The case's whole findings text
        # is the dictation, as the client sends it; library_cards caps it at DICTATION_MAX, as live.
        cards = await M.library_cards(case["scan_type"], case["clinical_history"], [M.Finding(**f) for f in fs],
                                      dictation=case["findings"])
        lib, out, seen = LB.get(), [], set()
        texts = {f["id"]: f["text"] for f in fs}

        def emit(c, pack: str, via: str | None = None) -> None:
            fid = c.finding_id
            cid = f"{case['id']}:{fid}:{pack}"
            if cid not in seen:
                seen.add(cid)
                out.append({"id": cid, "case": case["id"], "pack": pack, "source": case.get("source", "prod"),
                            "scan_type": case["scan_type"], "clinical_history": case["clinical_history"],
                            "findings": case["findings"], "finding": c.finding or texts.get(fid, ""),
                            "via_sibling_of": via, "trigger": "exam" if fid == "exam" else "finding",
                            "needs_modality": c.needs_modality})

        # Tier 1 cards are settled and labelled; a tier 2 card used a cap slot live but gets no lab card. TNM cards are
        # recorded as "tnm:<site>" (counted, never settled or labelled); so are cards marked needs_modality (an
        # off-modality "redirect" pack: read-only live, so never settled, labelled or counted as asked). Siblings are columns on the hit's card live:
        # emitted here as their own cards (each is settled and labelled) after the hits, never counted toward the caps.
        for c in cards:
            site = tnm.site_for(c.key) if tnm.is_tnm(c.key) else None
            if site:
                emit(c, f"tnm:{site}")
            elif (e := lib.lookup(c.key)) is not None and e.tier == 1:
                emit(c, e.key)
        for c in cards:
            for k in c.siblings:
                sib = lib.lookup(k)
                if sib is not None and sib.tier == 1:
                    emit(c, sib.key, c.key)
        return out


def settleable(cards: list[dict]) -> list[dict]:
    """The cards the lab settles and labels: library packs, not TNM and not needs_modality (those are only counted)."""
    return [c for c in cards if not str(c["pack"]).startswith("tnm:") and not c.get("needs_modality")]


def sample_cards(cards: list[dict], per_pack: int, total: int, seed: int = 13) -> list[dict]:
    """At most per_pack cards of each pack, at most total overall, spread round-robin across packs; seeded."""
    rng = random.Random(seed)
    by: dict[str, list[dict]] = defaultdict(list)
    for c in sorted(cards, key=lambda c: c["id"]):
        by[c["pack"]].append(c)
    for v in by.values():
        rng.shuffle(v)
    pools = {k: v[:per_pack] for k, v in sorted(by.items())}
    out: list[dict] = []
    while len(out) < total and any(pools.values()):
        for k in sorted(pools):
            if pools[k] and len(out) < total:
                out.append(pools[k].pop(0))
    return out


def cases_from_export(body: dict, source: str = "prod") -> list[dict]:
    cols = [c["name"] for c in body["data"]["cols"]]
    seen, out = set(), []
    for row in body["data"]["rows"]:
        r = dict(zip(cols, row))
        text = (r.get("findings") or "").strip()
        if text and text not in seen:                    # unique dictations only
            seen.add(text)
            out.append({"id": r["id"], "scan_type": r.get("scan_type") or "", "source": source,
                        "clinical_history": r.get("clinical_history") or "", "findings": text})
    return out


def _read_checkpoint(path: Path | None) -> dict:
    """Cases already recorded WITHOUT error in a checkpoint file -> their cards. Errored cases are left out (retried)."""
    done: dict = {}
    if path is None:
        return done
    bad = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if "error" in rec:
                _ = rec["case"]
            else:
                done[rec["case"]] = rec["cards"]
        except (ValueError, KeyError, TypeError):        # truncated or malformed line: that case is retried
            bad += 1
    if bad:
        print(f"{bad} unreadable checkpoint lines skipped", file=sys.stderr)
    return done


async def _gather_cards(cases: list[dict], ckpt: Path | None = None, done: dict | None = None,
                        concurrency: int = 2) -> list[dict]:
    """Cards for every case. Each finished case is appended at once to the checkpoint (one JSON line: cards, or the
    exception type only, never clinical text). Cases in `done` are reused, not rerun; a case that raises is skipped."""
    sem = asyncio.Semaphore(concurrency)
    done = done or {}
    fh = ckpt.open("a") if ckpt else None

    def record(rec: dict) -> None:
        if fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()

    async def one(c: dict):
        if c["id"] in done:
            record({"case": c["id"], "cards": done[c["id"]]})
            return done[c["id"]]
        try:
            r = await _cards_for(c, sem)
        except Exception as e:
            record({"case": c["id"], "error": type(e).__name__})
            raise
        record({"case": c["id"], "cards": r})
        return r

    try:
        results = await asyncio.gather(*(one(c) for c in cases), return_exceptions=True)
    finally:
        if fh:
            fh.close()
    out = []
    for c, r in zip(cases, results):
        if isinstance(r, BaseException):
            print(f"skipped case {c['id']}: {type(r).__name__}", file=sys.stderr)
        else:
            out += r
    return out


def select_cases(cases: list[dict], selected: dict) -> list[dict]:
    """Only the cases whose id is in selected["selected"], in the selection's order; unknown ids counted on stderr."""
    by = {c["id"]: c for c in cases}
    ids = [x["id"] for x in selected["selected"]]
    missing = sum(1 for i in ids if i not in by)
    if missing:
        print(f"{missing} selected ids not in the export", file=sys.stderr)
    return [by[i] for i in ids if i in by]


async def group(src: Path, out_dir: Path, per_pack: int = 30, total: int = 100, max_cases: int = 400,
                cases_file: Path | None = None, resume: Path | None = None, concurrency: int = 2) -> Path:
    cases = cases_from_export(json.loads(src.read_text()))
    if cases_file is not None:
        cases = select_cases(cases, json.loads(cases_file.read_text()))
    else:
        random.Random(13).shuffle(cases)                 # fixed seed: the same cases every run
        cases = cases[:max_cases]
    ckpt = _pid(out_dir, "group_cases", "jsonl")
    cards = await _gather_cards(cases, ckpt, _read_checkpoint(resume), concurrency)
    p = _pid(out_dir, "cards", "json")
    p.write_text(json.dumps(sample_cards(settleable(cards), per_pack, total), indent=1))
    print(f"{len(cases)} dictations, {len(cards)} cards -> {p} ({dict(Counter(c['pack'] for c in cards))}); "
          f"checkpoint {ckpt}")
    return p


def tag_cases(raw: list[dict], source: str) -> list[dict]:
    """Cases stamped with their source; ids prefixed h- for hassan, else <source>-, unless already prefixed."""
    pre = "h-" if source == "hassan" else f"{source}-"
    return [{**c, "source": source, "id": c["id"] if str(c["id"]).startswith(pre) else f"{pre}{c['id']}"}
            for c in raw]


async def hassan(src: Path, cards_path: Path, out_dir: Path, concurrency: int = 2, source: str = "hassan",
                 resume: Path | None = None) -> Path:
    cases = tag_cases(json.loads(src.read_text()), source)
    ckpt = _pid(out_dir, "group_cases", "jsonl")
    cards = json.loads(cards_path.read_text()) + await _gather_cards(cases, ckpt, _read_checkpoint(resume),
                                                                      concurrency)
    p = _pid(out_dir, "cards", "json")
    p.write_text(json.dumps(settleable(cards), indent=1))
    print(f"{len(cards)} cards -> {p} ({dict(Counter((c['source'], c['pack']) for c in cards))}; tnm counted, not "
          f"written); checkpoint {ckpt}")
    return p


# ── label ───────────────────────────────────────────────────────────────────────────────────────────────────────

def pack_text(e: Entry) -> str:
    rows = [f"- {i.id} [{i.scope}{', eligibility' if i.role == 'eligibility' else ''}]: {i.label}; "
            f"values: {' | '.join(display_options(e, i)) or 'a number in ' + (i.unit or 'its unit')}; "
            f"definition: {i.how_stated or i.label}" for i in e.inputs]
    return f"PACK: {e.display} ({e.issuer} {e.edition})\nINPUTS:\n" + "\n".join(rows)


def write_brief(lib, cards: list[dict], cards_path: Path, labels_path: Path) -> str:
    """The labelling brief: instructions, the output path and schema, and for each pack in the sample its inputs and
    where its entry and sources live. The cards file carries the dictations. Nothing from the settler is named."""
    packs = sorted({c["pack"] for c in cards})
    parts = [LABEL_INSTRUCTIONS, f"CARDS: {cards_path}", f"OUTPUT: {labels_path}",
             "SCHEMA:\n" + json.dumps(LabelFile.model_json_schema(), indent=1)]
    for k in packs:
        e = lib.lookup(k)
        parts.append(f"{pack_text(e)}\nENTRY: {GUIDELINES}/{e.id}/entry.json\nMANIFEST: {GUIDELINES}/{e.id}/manifest.json\n"
                     f"SOURCES: {GUIDELINES}/{e.id}/sources/")
    return "\n\n".join(parts)


def parse_label(e: Entry, raw: dict, served_by: str) -> dict:
    """The label keyed by input; every pack input present (an unlabelled one: not stated, boundary); a value the
    pack cannot take becomes a boundary item with no value. A number labelled as a band or bound ("under 1 cm",
    ">8 mm") is a value: _same compares a drafted number with it as the engine bands it."""
    got = {x["input"]: x for x in raw.get("inputs", []) if e.input(x["input"]) is not None}
    out = {}
    for i in e.inputs:
        x = dict(got.get(i.id) or {"stated": False, "value": None, "quote": "", "locator": "", "assumed": None,
                                   "boundary": True, "note": "not labelled"})
        for k in ("value", "assumed"):
            if (x.get(k) is not None and _answer(e, i, str(x[k])) is None
                    and not (i.type == "number" and _interval(e, i, str(x[k])) is not None)):
                x["boundary"], x["note"], x[k] = True, f"{k} {x[k]!r} is not a value of the pack", None
        if x["value"] is None:
            x["stated"] = False
        out[i.id] = x
    return {"inputs": out, "lesions": raw.get("lesions", []), "category": raw.get("category"),
            "served_by": served_by}


def load_labels(lib, cards: list[dict], raw: dict) -> tuple[dict[str, dict], list[str]]:
    """(labels by card id, problems). Problems: served_by missing, a card not labelled, a label for no card, or a
    card label that fails the schema. A card with a problem gets no label."""
    problems: list[str] = []
    if not str(raw.get("served_by") or "").strip():
        problems.append("served_by is not recorded")
    labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    ids = {c["id"] for c in cards}
    problems += [f"{k} is not a card" for k in labels if k not in ids]
    out: dict[str, dict] = {}
    for c in cards:
        if c["id"] not in labels:
            problems.append(f"{c['id']} is not labelled")
            continue
        try:
            got = CardLabel.model_validate(labels[c["id"]])
        except ValidationError as ex:
            problems.append(f"{c['id']}: schema: {ex.errors()[0]['msg']}")
            continue
        out[c["id"]] = parse_label(lib.lookup(c["pack"]), got.model_dump(), str(raw.get("served_by") or ""))
    return out, problems


# ── run / score ─────────────────────────────────────────────────────────────────────────────────────────────────

def card_presets(e: Entry, card: dict) -> dict[str, str]:
    """The exam presets live gives this card: an exam card's (finding_id EXAM_CARD), else none (same helper)."""
    return exam_presets(e, EXAM_CARD if card.get("trigger") == "exam" else "")


def drafts(s, e: Entry | None = None, presets: dict[str, str] | None = None) -> dict[str, tuple[InputValue, str, str]]:
    """input -> (value, quote, tier). A stored settlement from before value states (tuples) has every value read. An
    exam preset the settlement leaves open is pre-filled (no quote), exactly as live `finish` fills it."""
    out = {}
    for k, v in s.values.items():
        if isinstance(v, tuple):
            out[k] = (v[0], v[1], "read")
        else:                                   # the later Drafted shape
            out[k] = (v.value, v.quote, v.tier)
    for k, v in (preset_values(e, presets) if e is not None else {}).items():
        out.setdefault(k, (v, "", "prefilled"))
    return out


# a labeller's band or bound for a number ("under 1 cm", "35 years or over", ">8 mm", "1 cm to under 4 cm"): an interval
_BOUNDS = [(re.compile(r"^(?:under|below|less than|<)\s*(.+)$"), "lt"),
           (re.compile(r"^(?:up to|at most|≤|<=)\s*(.+)$"), "le"),
           (re.compile(r"^(.+?)\s*or (?:less|under|below|smaller)$"), "le"),
           (re.compile(r"^(?:over|above|more than|greater than|>)\s*(.+)$"), "gt"),
           (re.compile(r"^(?:at least|≥|>=)\s*(.+)$"), "ge"),
           (re.compile(r"^(.+?)\s*or (?:over|more|above|greater|older)$"), "ge")]
_SPAN = re.compile(r"^(.+?)\s*(to under|to less than|to|-|–|—)\s*(.+)$")


def _norm_label(s: str) -> str:
    return " ".join(s.lower().replace("–", "-").replace("—", "-").split())


def _reading(i, text: str, unit_hint: str = "") -> float | None:
    """One number from a label part, in the input's unit (a bare number borrows the other part's unit, else the
    input's own)."""
    xs = Q.readings(text, i.unit, i.dims)
    if not xs and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", text):
        xs = Q.readings(f"{text.strip()} {unit_hint or i.unit}", i.unit, i.dims)
    return xs[0] if len(xs) == 1 else None


def _interval(e: Entry, i, label: str):
    """(lo, lo_inclusive, hi, hi_inclusive) for a band label of this input on any band step, or a bound or span the
    labeller wrote; None when the label is neither."""
    n = _norm_label(label)
    for s in e.logic:
        if getattr(s, "ref", None) == i.id and hasattr(s, "bands"):
            for b in s.bands:
                if _norm_label(b.label) == n:
                    return (b.min, b.min_inclusive, b.max, b.max_inclusive)
    for rx, kind in _BOUNDS:
        m = rx.match(n)
        if m and (x := _reading(i, m.group(1))) is not None:
            return {"lt": (None, True, x, False), "le": (None, True, x, True),
                    "gt": (x, False, None, False), "ge": (x, True, None, False)}[kind]
    m = _SPAN.match(n)
    if m:
        unit = re.sub(r"[\d.\s]", "", m.group(3)) or ""
        lo, hi = _reading(i, m.group(1), unit), _reading(i, m.group(3))
        if lo is not None and hi is not None:
            return (lo, True, hi, m.group(2) not in ("to under", "to less than"))
    return None


def _inside(x: float, iv) -> bool:
    lo, lo_inc, hi, hi_inc = iv
    ok_lo = lo is None or (x >= lo - 1e-9 if lo_inc else x > lo + 1e-9)
    ok_hi = hi is None or (x <= hi + 1e-9 if hi_inc else x < hi - 1e-9)
    return ok_lo and ok_hi


def _same(e: Entry, k: str, v: InputValue, label_value: str | None) -> bool:
    """The drafted value agrees with the label. A number is compared numerically in the input's unit; against a band
    label (the pack's own, from any band step reading it) or a labeller's bound or span, it agrees when it falls inside
    that interval, as the engine would band it. A genuine mismatch stays a mismatch."""
    if label_value is None:
        return False
    i = e.input(k)
    t = _answer(e, i, label_value)
    if t is not None and _show(e, i, t) == _show(e, i, v):
        return True
    if i.type != "number" or v.state != "present" or v.value is None:
        return False
    x = float(v.value)
    if t is not None and t.state == "present" and t.value is not None:
        return abs(float(t.value) - x) <= 1e-9 * max(1.0, abs(x))
    iv = _interval(e, i, label_value)
    return iv is not None and _inside(x, iv)


def _agrees_by_band(e: Entry, k: str, v: InputValue, label_value: str | None) -> bool:
    """_same holds only because the number falls inside a band or bound, not because it equals the truth: reported
    apart, since a number that also feeds a formula is not verified by its band (review M-b)."""
    if label_value is None:
        return False
    i = e.input(k)
    t = _answer(e, i, label_value)
    if t is not None and (_show(e, i, t) == _show(e, i, v) or (t.state == "present" and t.value is not None)):
        return False
    return _same(e, k, v, label_value)


def _truth(label: dict) -> dict[str, str | None]:
    return {k: (x["value"] if x["stated"] else x["assumed"]) for k, x in label["inputs"].items()}


def _right(e: Entry, k: str, v: InputValue, tier: str, label: dict) -> bool:
    """A read draft must be stated and match; an exam preset claims no quote, so it must match the truth (stated,
    else assumed)."""
    lab = label["inputs"][k]
    if tier == "prefilled":
        return _same(e, k, v, _truth(label)[k])
    return lab["stated"] and _same(e, k, v, lab["value"])


def verdicts(e: Entry, s, label: dict, presets: dict[str, str] | None = None) -> dict[str, str]:
    """ok: drafted and true; wrong: drafted but not stated, or not what was stated (a preset: not the truth); asked:
    not drafted."""
    d = drafts(s, e, presets)
    return {i.id: "asked" if i.id not in d else "ok" if _right(e, i.id, d[i.id][0], d[i.id][2], label) else "wrong"
            for i in e.inputs}


def taps(e: Entry, s, label: dict, patient: dict, picked: bool = False,
         presets: dict[str, str] | None = None) -> tuple[int, str | None]:
    """Taps to an outcome (spec §12): one per asked input the engine needs (truth, else assumed), one per wrong
    drafted value (corrected to truth), one per eligibility value the card assumed in scope that the truth
    contradicts (corrected to truth), one for the lesion pick if shown. Calculate is not counted. A wrong draft is
    dropped from a copy of the settlement, so the engine never sees it; the original is untouched."""
    truth, d = _truth(label), drafts(s, e, presets)
    wrong = [k for k, (v, _, t) in d.items() if not _right(e, k, v, t, label)]
    s = dataclasses.replace(s, values={k: v for k, v in s.values.items() if k not in wrong})
    presets = {k: x for k, x in (presets or {}).items() if k not in wrong}
    answered: dict[str, str] = {k: truth[k] for k in wrong if truth[k] is not None}
    n = (1 if picked else 0) + len(wrong)
    p = finish(e, s, answered, patient, presets=presets)
    for _ in range(MAX_FILL):
        new = {k: truth[k] for k in p.missing if k not in answered and truth.get(k) is not None}
        shown = {d.input: d.value for d in p.draft}
        new.update({k: truth[k] for k in (a.input for a in p.assumptions) if k not in answered and truth.get(k) is not None
                    and not _same(e, k, _answer(e, e.input(k), shown[k]) or InputValue(state="unknown"), truth[k])})
        if not new:
            break
        answered.update(new)
        n += len(new)
        p = finish(e, s, answered, patient, presets=presets)
    # the Calculate tap: the engine over every value the card shows (a pre-filled scope doubt the truth agrees with is
    # confirmed by it and excludes, as live Calculate would)
    shown = {d.input: d.value for d in p.draft if d.value}
    return n, calculate(e, s, shown, patient, [], "", presets=presets).outcome


def spot_rows(e: Entry, card: dict, s, label: dict) -> list[dict]:
    """Boundary items for Hassan: the labeller's own flags and every disagreement with the settler."""
    pre = card_presets(e, card)
    d, v = drafts(s, e, pre), verdicts(e, s, label, pre)
    rows = []
    for i in e.inputs:
        lab = label["inputs"][i.id]
        if not (lab["boundary"] or v[i.id] == "wrong"):
            continue
        val, q, tier = d.get(i.id, (None, "", "asked"))
        rows.append({"case": card["id"], "pack": card["pack"], "input": i.id, "label_value": lab["value"] or "",
                     "label_quote": lab["quote"], "locator": lab["locator"], "label_note": lab["note"],
                     "settler_value": _show(e, i, val) if val is not None else "", "settler_tier": tier,
                     "settler_quote": q, "hassan_value": "", "hassan_note": ""})
    return rows


def metrics(rows: list[dict]) -> dict:
    """rows: one per card with card, pack, taps, verdicts (input -> ok|wrong|asked), tiers (input -> read|prefilled)
    and degraded. Measured and reported, never judged: Hassan decides."""
    wrong_read = [f"{r['card']}:{k}" for r in rows for k, v in r["verdicts"].items()
                  if v == "wrong" and r["tiers"].get(k) == "read"]
    pf: dict[str, dict] = defaultdict(lambda: {"wrong": 0, "prefilled": 0})
    for r in rows:
        for k, t in r["tiers"].items():
            if t == "prefilled":
                key = f"{r['pack']}.{k}"
                pf[key]["prefilled"] += 1
                pf[key]["wrong"] += r["verdicts"][k] == "wrong"
    return {"cards": len(rows), "wrong_read": wrong_read,
            "median_taps": statistics.median(r["taps"] for r in rows) if rows else None,
            "taps_distribution": dict(sorted(Counter(r["taps"] for r in rows).items())),
            "prefill_error": {k: {**v, "rate": v["wrong"] / v["prefilled"]} for k, v in sorted(pf.items())},
            "degraded": [r["card"] for r in rows if r.get("degraded")]}


HEADLINE_SOURCES = ("prod", "hassan")          # real dictations; synthetic is only ever reported on its own


def headline_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("source", "prod") in HEADLINE_SOURCES]


def card_kinds(rows: list[dict]) -> dict:
    """Per source: hit cards (the matcher's own) against sibling cards (columns of a hit, emitted separately)."""
    out: dict[str, dict] = {}
    for r in rows:
        k = out.setdefault(r.get("source", "prod"), {"hit": 0, "sibling": 0})
        k["sibling" if r.get("sibling") else "hit"] += 1
    return dict(sorted(out.items()))


def by_source(rows: list[dict]) -> dict:
    """Metrics per source present in the rows, plus "prod+hassan" (the real-dictation view) when both exist.
    Production stays the headline; synthetic is only ever reported on its own, never folded in."""
    groups = {src: [r for r in rows if r.get("source", "prod") == src]
              for src in sorted({r.get("source", "prod") for r in rows})}
    if "prod" in groups and "hassan" in groups:
        groups["prod+hassan"] = groups["prod"] + groups["hassan"]
    return {src: {**metrics(g), "outcome_agreement": outcome_agreement(g), "wrong_prefill_total": wrong_prefill_total(g)}
            for src, g in groups.items()}


def outcome_agreement(rows: list[dict]) -> dict:
    """Per card: the outcome reached on truth-corrected values (outcome) against the settler's own draft outcome
    (draft_outcome). none: the settler reached no outcome (or neither did); disagreeing cards are named."""
    agree, disagree, none = 0, [], 0
    for r in rows:
        if r.get("draft_outcome") is None:
            none += 1
        elif r.get("outcome") == r["draft_outcome"]:
            agree += 1
        else:
            disagree.append(r["card"])
    return {"agree": agree, "disagree": len(disagree), "none": none, "disagreeing_cards": disagree}


def wrong_prefill_total(rows: list[dict]) -> int:
    """How many pre-filled values were wrong, across all cards (spec §12 'Also reported')."""
    return sum(1 for r in rows for k, v in r["verdicts"].items() if v == "wrong" and r["tiers"].get(k) == "prefilled")


# ── commands that need the model / disk ─────────────────────────────────────────────────────────────────────────

def _draft_outcome(p):
    """The settler's own draft outcome: draft_outcome once it exists, else today's proposal."""
    return getattr(p, "draft_outcome", None) or p.proposal


async def run(cards_path: Path, out_dir: Path) -> Path:
    cards, lib, out = json.loads(cards_path.read_text()), _lib(), []
    for c in cards:
        try:
            e = lib.lookup(c["pack"])
            t0 = time.perf_counter()
            s = await settle_pack(e, c["findings"], c["clinical_history"], c["finding"])      # cold: no cache
            ms = round((time.perf_counter() - t0) * 1000)
            pre = card_presets(e, c)
            p = finish(e, s, {}, presets=pre)
            do = _draft_outcome(p)
            out.append({"card": c["id"], "ms": ms, "degraded": bool(getattr(s, "failed", False)),
                        "missing": p.missing,
                        "draft_outcome": do.model_dump(mode="json") if do is not None else None,
                        "draft_outcome_id": (p.trace or {}).get("outcome"),
                        "drafts": {k: {"value": v.model_dump(mode="json"), "quote": q, "tier": t,
                                       "why": list(getattr(s.values[k], "why", []))}
                                   for k, (v, q, t) in drafts(s).items()},     # settled only: score re-adds
                        "presets": pre})                                           # the card's presets live's way
        except Exception as ex:                       # one bad card must not lose the run; type only, no text
            print(f"card {c['id']} errored: {type(ex).__name__}", file=sys.stderr)
            out.append({"card": c["id"], "error": type(ex).__name__})
    path = _pid(out_dir, "settler", "json")
    path.write_text(json.dumps(out, indent=1))
    print(f"{len(out)} cards settled -> {path}")
    return path


def _settlement(rec: dict) -> Settlement:
    vals = {}
    for k, d in rec["drafts"].items():
        v = InputValue.model_validate(d["value"])
        vals[k] = Drafted(v, d["quote"], d["tier"], list(d.get("why", [])))
    return Settlement(values=vals, failed=rec["degraded"])


def _apply_overrides(lib, cards: list[dict], labels: dict[str, dict], sheet: Path | None) -> tuple[int, list[str]]:
    """Hassan's corrections, validated against the card's pack as parse_label does: one the pack cannot take is
    reported and skipped, never applied."""
    n, problems = 0, []
    if sheet is None:
        return n, problems
    pack = {c["id"]: c["pack"] for c in cards}
    for r in csv.DictReader(sheet.open()):
        v = (r.get("hassan_value") or "").strip()
        lab = labels.get(r["case"], {}).get("inputs", {}).get(r["input"])
        if not v or lab is None:
            continue
        gone = v.lower() in ("none", "not stated")
        e = lib.lookup(pack[r["case"]])
        if not gone and _answer(e, e.input(r["input"]), v) is None:
            problems.append(f"override {r['case']}:{r['input']} {v!r} is not a value of the pack; skipped")
            continue
        lab["value"], lab["stated"], lab["boundary"] = (None if gone else v), not gone, False
        n += 1
    return n, problems


def _load(cards_p: Path, labels_p: Path, settler_p: Path):
    lib, cards = _lib(), json.loads(cards_p.read_text())
    labels, problems = load_labels(lib, cards, json.loads(labels_p.read_text()))
    if problems:
        print("\n".join(problems), file=sys.stderr)
    return lib, cards, labels, {r["card"]: r for r in json.loads(settler_p.read_text())}


def sheet(cards_p: Path, labels_p: Path, settler_p: Path, out_dir: Path) -> Path:
    lib, cards, labels, st = _load(cards_p, labels_p, settler_p)
    rows = []
    for c in cards:
        if c["id"] in labels and c["id"] in st and "error" not in st[c["id"]]:
            rows += spot_rows(lib.lookup(c["pack"]), c, _settlement(st[c["id"]]), labels[c["id"]])
        elif c["id"] not in labels:
            rows.append({"case": c["id"], "pack": c["pack"], "input": "", "label_note": "not labelled",
                         "hassan_value": "", "hassan_note": ""})
    path = _pid(out_dir, "spotcheck", "csv")
    cols = ["case", "pack", "input", "label_value", "label_quote", "locator", "label_note", "settler_value",
            "settler_tier", "settler_quote", "hassan_value", "hassan_note"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} items for Hassan -> {path}")
    return path


def _draft_now(e: Entry, s, presets: dict[str, str]) -> str | None:
    """The draft outcome the card shows today over the stored settlement (the engine is deterministic), so a score-only
    re-run measures the current card rules, not those of the day the settler ran. None when there is no outcome."""
    return (finish(e, s, {}, presets=presets).trace or {}).get("outcome")


def score(cards_p: Path, labels_p: Path, settler_p: Path, out_dir: Path, verdicts_csv: Path | None = None) -> Path:
    lib, cards, labels, st = _load(cards_p, labels_p, settler_p)
    overrides, op = _apply_overrides(lib, cards, labels, verdicts_csv)
    if op:
        print("\n".join(op), file=sys.stderr)
    rows, skipped = [], []
    for c in cards:
        if c["id"] not in labels or c["id"] not in st or "error" in st[c["id"]]:
            skipped.append(c["id"])
            continue
        e, s, lab = lib.lookup(c["pack"]), _settlement(st[c["id"]]), labels[c["id"]]
        pre = card_presets(e, c)
        n, outcome = taps(e, s, lab, {}, presets=pre)
        d = drafts(s, e, pre)
        ver = verdicts(e, s, lab, pre)
        by_band = [k for k, (val, _, tier) in d.items() if ver[k] == "ok" and _agrees_by_band(
            e, k, val, _truth(lab)[k] if tier == "prefilled" else lab["inputs"][k]["value"])]
        rows.append({"card": c["id"], "pack": c["pack"], "source": c.get("source", "prod"),
                     "sibling": bool(c.get("via_sibling_of")), "ms": st[c["id"]]["ms"], "taps": n, "verdicts": ver, "agrees_by_band": by_band,
                     "tiers": {k: t for k, (_, _, t) in d.items()}, "degraded": st[c["id"]]["degraded"],
                     "outcome": outcome, "draft_outcome": _draft_now(e, s, pre),
                     "draft_outcome_stored": st[c["id"]].get("draft_outcome_id")})
    errored = [k for k, r in st.items() if "error" in r]
    if skipped:
        print(f"skipped {len(skipped)} unlabelled, unsettled or errored cards: {', '.join(skipped)}", file=sys.stderr)
    cats = Counter(c["pack"] for c in cards if (labels.get(c["id"]) or {}).get("category"))
    head = headline_rows(rows)                                          # synthetic never joins the headline
    ms = [r["ms"] for r in head]
    q = statistics.quantiles(ms, n=20) if len(ms) > 1 else ms * 2
    result = {**metrics(head), "headline_sources": list(HEADLINE_SOURCES), "outcome_agreement": outcome_agreement(head),
              "wrong_prefill_total": wrong_prefill_total(head), "by_source": by_source(rows),
              "agrees_by_band": [f"{r['card']}:{k}" for r in head for k in r["agrees_by_band"]],
              "notes": ["taps outcome = the Calculate result over every value the card shows",
                        "outcome agreement uses the draft outcome recomputed under today's card rules over the stored "
                        "settlement (draft_outcome); the settler-time one is draft_outcome_stored per row"],
              "rows": rows,
              "card_kinds_by_source": card_kinds(rows), "category_dictated_by_pack": dict(cats),
              "hassan_overrides": overrides, "override_problems": op, "skipped_cards": skipped,
              "errored_cards": errored, "latency_ms": {"p50": statistics.median(ms) if ms else None,
                                                            "p95": q[-1] if q else None},
              "time_to_first_paint": "not measured offline", "checker": "n/a", "lesions": "n/a"}
    path = _pid(out_dir, "score", "json")
    path.write_text(json.dumps(result, indent=1))
    print(f"headline = {' + '.join(HEADLINE_SOURCES)} only (synthetic is reported on its own below)")
    if not head:
        print("no prod or hassan cards scored: there is no headline")
    else:
        print("| metric | measured | reference |\n|---|---|---|")
        print(f"| cards scored | {result['cards']} | |")
        print(f"| wrong values shown as read | {len(result['wrong_read'])} | 0 |")
        print(f"| median taps to Calculate | {result['median_taps']} | <= 2 |")
        print(f"| taps distribution | {result['taps_distribution']} | |")
        print(f"| wrong pre-filled values | {result['wrong_prefill_total']} | |")
        print(f"| numbers right only by band (reported apart) | {len(result['agrees_by_band'])} | |")
        print(f"| outcome agreement | {result['outcome_agreement']} | |")
        print(f"| errored / skipped cards | {len(errored)} / {len(skipped)} | |")
        print(f"| degraded cards | {len(result['degraded'])} | |")
        print(f"| latency p50 / p95 ms | {result['latency_ms']['p50']} / {result['latency_ms']['p95']} | |")
        print("| time to first paint | not measured offline | |\n| checker, lesions | n/a | |")
        print("\n".join(f"note: {x}" for x in result["notes"]))
    print(f"\ncards by source (hit / sibling): {result['card_kinds_by_source']}")
    for src, m in result["by_source"].items():
        print(f"\n### source: {src}\n| metric | measured |\n|---|---|")
        print(f"| cards scored | {m['cards']} |\n| wrong values shown as read | {len(m['wrong_read'])} |")
        print(f"| median taps to Calculate | {m['median_taps']} |\n| taps distribution | {m['taps_distribution']} |")
        print(f"| wrong pre-filled values | {m['wrong_prefill_total']} |\n| outcome agreement | {m['outcome_agreement']} |")
    return path


def main(argv: list[str]) -> None:
    def opt(name: str, default: int) -> int:
        return int(argv[argv.index(name) + 1]) if name in argv else default

    cmd = argv[1]
    if cmd == "export":
        print(export(Path(argv[2])))
    elif cmd == "group":
        def path_opt(name: str) -> Path | None:
            return Path(argv[argv.index(name) + 1]) if name in argv else None

        asyncio.run(group(Path(argv[2]), Path(argv[3]), opt("--per-pack", 30), opt("--total", 100),
                          opt("--max-cases", 400), path_opt("--cases"), path_opt("--resume"),
                          opt("--concurrency", 2)))
    elif cmd == "hassan":
        asyncio.run(hassan(Path(argv[2]), Path(argv[3]), Path(argv[4]), opt("--concurrency", 2),
                           argv[argv.index("--source") + 1] if "--source" in argv else "hassan",
                           Path(argv[argv.index("--resume") + 1]) if "--resume" in argv else None))
    elif cmd == "brief":
        cards_p, d = Path(argv[2]), Path(argv[3])
        p = _pid(d, "label_brief", "md")
        p.write_text(write_brief(_lib(), json.loads(cards_p.read_text()), cards_p, d / f"labels_{os.getpid()}.json"))
        print(p)
    elif cmd == "labels":
        _, problems = load_labels(_lib(), json.loads(Path(argv[3]).read_text()), json.loads(Path(argv[2]).read_text()))
        print("\n".join(problems) or "labels ok")
        sys.exit(1 if problems else 0)
    elif cmd == "run":
        asyncio.run(run(Path(argv[2]), Path(argv[3])))
    elif cmd == "sheet":
        sheet(Path(argv[2]), Path(argv[3]), Path(argv[4]), Path(argv[5]))
    elif cmd == "score":
        v = Path(argv[argv.index("--verdicts") + 1]) if "--verdicts" in argv else None
        score(Path(argv[2]), Path(argv[3]), Path(argv[4]), Path(argv[5]), v)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
