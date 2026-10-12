"""Real-dictation lab (library spec §12, "Draft card slice"). Production findings, read only through Metabase,
grouped offline by the stack grouper, matched to library packs (matcher naming + pack gate); truth from an independent
Claude Opus 5.5 subagent holding every pack's sources (the controller dispatches it with the brief this script writes);
Hassan spot-checks the boundary items; the settler is measured. Metrics and recommendations only: Hassan decides.
Everything stays in the output directory given on the command line, pid in each name; nothing from production is ever
committed, and no clinical text is ever logged.

  export  <dir>                       read-only SQL via Metabase           -> export_<pid>.json
  group   <export.json> <dir> [--per-pack 30 --total 100 --max-cases 400]  -> cards_<pid>.json
  hassan  <hassan_cases.json> <cards.json> <dir>   Hassan's own dictations, appended -> cards_<pid>.json
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
from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB  # noqa: E402
from rapid_reports_ai.hybrid_stack.copilot.library.pack_preview import (  # noqa: E402
    _answer, _show, display_options, finish, settle_pack, Settlement)
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, InputValue  # noqa: E402

MAX_FILL = 10
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


@dataclasses.dataclass
class _Drafted:
    """A stored non-'read' draft, rebuilt for scoring (same attributes as the settler's Drafted)."""
    value: InputValue
    quote: str
    tier: str


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
        raw = await M._call(M._prompt(case["scan_type"], case["clinical_history"], [M.Finding(**f) for f in fs], ""))
        lib, out = LB.get(), []
        for rf in raw.findings:
            f = next((x for x in fs if x["id"] == M._rid(rf.id)), None)
            for s in rf.systems if f else []:
                pack = lib.find(s.name, s.version) or lib.find(s.name)
                if pack is None or pack.tier != 1:
                    continue
                score = await M._pgate(f["text"], pack, case["clinical_history"])
                if score is not None and score >= M.PACK_GATE_MIN:
                    out.append({"id": f"{case['id']}:{f['id']}:{pack.key}", "case": case["id"], "pack": pack.key,
                                "source": case.get("source", "prod"), "scan_type": case["scan_type"],
                                "clinical_history": case["clinical_history"], "findings": case["findings"],
                                "finding": f["text"]})
        return out


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


async def _gather_cards(cases: list[dict]) -> list[dict]:
    """Cards for every case; a case that raises is skipped, logged by exception type only (never clinical text)."""
    sem = asyncio.Semaphore(4)
    results = await asyncio.gather(*(_cards_for(c, sem) for c in cases), return_exceptions=True)
    out = []
    for c, r in zip(cases, results):
        if isinstance(r, BaseException):
            print(f"skipped case {c['id']}: {type(r).__name__}", file=sys.stderr)
        else:
            out += r
    return out


async def group(src: Path, out_dir: Path, per_pack: int = 30, total: int = 100, max_cases: int = 400) -> Path:
    cases = cases_from_export(json.loads(src.read_text()))
    random.Random(13).shuffle(cases)                     # fixed seed: the same cases every run
    cases = cases[:max_cases]
    cards = await _gather_cards(cases)
    p = _pid(out_dir, "cards", "json")
    p.write_text(json.dumps(sample_cards(cards, per_pack, total), indent=1))
    print(f"{len(cases)} dictations, {len(cards)} pack cards -> {p} ({dict(Counter(c['pack'] for c in cards))})")
    return p


async def hassan(src: Path, cards_path: Path, out_dir: Path) -> Path:
    cases = [{**c, "source": "hassan", "id": f"h-{c['id']}"} for c in json.loads(src.read_text())]
    cards = json.loads(cards_path.read_text()) + await _gather_cards(cases)
    p = _pid(out_dir, "cards", "json")
    p.write_text(json.dumps(cards, indent=1))
    print(f"{len(cards)} cards -> {p} ({dict(Counter((c['source'], c['pack']) for c in cards))})")
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
        parts.append(f"{pack_text(e)}\nENTRY: guidelines/{e.id}/entry.json\nMANIFEST: guidelines/{e.id}/manifest.json\n"
                     f"SOURCES: guidelines/{e.id}/sources/")
    return "\n\n".join(parts)


def parse_label(e: Entry, raw: dict, served_by: str) -> dict:
    """The label keyed by input; every pack input present (an unlabelled one: not stated, boundary); a value the
    pack cannot take becomes a boundary item with no value."""
    got = {x["input"]: x for x in raw.get("inputs", []) if e.input(x["input"]) is not None}
    out = {}
    for i in e.inputs:
        x = dict(got.get(i.id) or {"stated": False, "value": None, "quote": "", "locator": "", "assumed": None,
                                   "boundary": True, "note": "not labelled"})
        for k in ("value", "assumed"):
            if x.get(k) is not None and _answer(e, i, str(x[k])) is None:
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

def drafts(s) -> dict[str, tuple[InputValue, str, str]]:
    """input -> (value, quote, tier). Today's settler has no tiers: every settled value is shown as read."""
    out = {}
    for k, v in s.values.items():
        if isinstance(v, tuple):
            out[k] = (v[0], v[1], "read")
        else:                                   # the later Drafted shape
            out[k] = (v.value, v.quote, v.tier)
    return out


def _same(e: Entry, k: str, v: InputValue, label_value: str | None) -> bool:
    if label_value is None:
        return False
    t = _answer(e, e.input(k), label_value)
    return t is not None and _show(e, e.input(k), t) == _show(e, e.input(k), v)


def verdicts(e: Entry, s, label: dict) -> dict[str, str]:
    """ok: drafted and true; wrong: drafted but not stated, or not what was stated; asked: not drafted."""
    d = drafts(s)
    out = {}
    for i in e.inputs:
        lab = label["inputs"][i.id]
        if i.id not in d:
            out[i.id] = "asked"
        else:
            out[i.id] = "ok" if lab["stated"] and _same(e, i.id, d[i.id][0], lab["value"]) else "wrong"
    return out


def _truth(label: dict) -> dict[str, str | None]:
    return {k: (x["value"] if x["stated"] else x["assumed"]) for k, x in label["inputs"].items()}


def taps(e: Entry, s, label: dict, patient: dict, picked: bool = False) -> tuple[int, str | None]:
    """Taps to an outcome (spec §12): one per asked input the engine needs (truth, else assumed), one per wrong
    drafted value (corrected to truth), one for the lesion pick if shown. Calculate is not counted. A wrong draft is
    dropped from a copy of the settlement, so the engine never sees it; the original is untouched."""
    truth, d = _truth(label), drafts(s)
    wrong = [k for k, (v, _, _) in d.items()
             if not (label["inputs"][k]["stated"] and _same(e, k, v, label["inputs"][k]["value"]))]
    s = dataclasses.replace(s, values={k: v for k, v in s.values.items() if k not in wrong})
    answered: dict[str, str] = {k: truth[k] for k in wrong if truth[k] is not None}
    n = (1 if picked else 0) + len(wrong)
    p = finish(e, s, answered, patient)
    for _ in range(MAX_FILL):
        new = {k: truth[k] for k in p.missing if k not in answered and truth.get(k) is not None}
        if not new:
            break
        answered.update(new)
        n += len(new)
        p = finish(e, s, answered, patient)
    return n, (p.trace or {}).get("outcome")


def spot_rows(e: Entry, card: dict, s, label: dict) -> list[dict]:
    """Boundary items for Hassan: the labeller's own flags and every disagreement with the settler."""
    d, v = drafts(s), verdicts(e, s, label)
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
        e = lib.lookup(c["pack"])
        t0 = time.perf_counter()
        s = await settle_pack(e, c["findings"], c["clinical_history"], c["finding"])      # cold: no cache
        ms = round((time.perf_counter() - t0) * 1000)
        p = finish(e, s, {})
        do = _draft_outcome(p)
        out.append({"card": c["id"], "ms": ms, "degraded": bool(getattr(s, "failed", False)),
                    "missing": p.missing, "draft_outcome": do.model_dump(mode="json") if do is not None else None,
                    "draft_outcome_id": (p.trace or {}).get("outcome"),
                    "drafts": {k: {"value": v.model_dump(mode="json"), "quote": q, "tier": t}
                               for k, (v, q, t) in drafts(s).items()}})
    path = _pid(out_dir, "settler", "json")
    path.write_text(json.dumps(out, indent=1))
    print(f"{len(out)} cards settled -> {path}")
    return path


def _settlement(rec: dict) -> Settlement:
    vals = {}
    for k, d in rec["drafts"].items():
        v = InputValue.model_validate(d["value"])
        vals[k] = (v, d["quote"]) if d["tier"] == "read" else _Drafted(v, d["quote"], d["tier"])
    return Settlement(values=vals, failed=rec["degraded"])


def _apply_overrides(labels: dict[str, dict], sheet: Path | None) -> int:
    n = 0
    if sheet is None:
        return n
    for r in csv.DictReader(sheet.open()):
        v = (r.get("hassan_value") or "").strip()
        lab = labels.get(r["case"], {}).get("inputs", {}).get(r["input"])
        if v and lab is not None:
            gone = v.lower() in ("none", "not stated")
            lab["value"], lab["stated"], lab["boundary"] = (None if gone else v), not gone, False
            n += 1
    return n


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
        if c["id"] in labels and c["id"] in st:
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


def score(cards_p: Path, labels_p: Path, settler_p: Path, out_dir: Path, verdicts_csv: Path | None = None) -> Path:
    lib, cards, labels, st = _load(cards_p, labels_p, settler_p)
    overrides = _apply_overrides(labels, verdicts_csv)
    rows, ms = [], []
    for c in cards:
        if c["id"] not in labels or c["id"] not in st:
            continue
        e, s, lab = lib.lookup(c["pack"]), _settlement(st[c["id"]]), labels[c["id"]]
        n, outcome = taps(e, s, lab, {})
        d = drafts(s)
        rows.append({"card": c["id"], "pack": c["pack"], "taps": n, "verdicts": verdicts(e, s, lab),
                     "tiers": {k: t for k, (_, _, t) in d.items()}, "degraded": st[c["id"]]["degraded"],
                     "outcome": outcome, "draft_outcome": st[c["id"]].get("draft_outcome_id")})
        ms.append(st[c["id"]]["ms"])
    cats = Counter(c["pack"] for c in cards if (labels.get(c["id"]) or {}).get("category"))
    q = statistics.quantiles(ms, n=20) if len(ms) > 1 else ms * 2
    result = {**metrics(rows), "outcome_agreement": outcome_agreement(rows),
              "wrong_prefill_total": wrong_prefill_total(rows), "category_dictated_by_pack": dict(cats),
              "hassan_overrides": overrides, "latency_ms": {"p50": statistics.median(ms) if ms else None,
                                                            "p95": q[-1] if q else None},
              "time_to_first_paint": "not measured offline", "checker": "n/a", "lesions": "n/a"}
    path = _pid(out_dir, "score", "json")
    path.write_text(json.dumps(result, indent=1))
    print("| metric | measured | reference |\n|---|---|---|")
    print(f"| cards scored | {result['cards']} | |")
    print(f"| wrong values shown as read | {len(result['wrong_read'])} | 0 |")
    print(f"| median taps to Calculate | {result['median_taps']} | <= 2 |")
    print(f"| taps distribution | {result['taps_distribution']} | |")
    print(f"| wrong pre-filled values | {result['wrong_prefill_total']} | |")
    print(f"| outcome agreement | {result['outcome_agreement']} | |")
    print(f"| degraded cards | {len(result['degraded'])} | |")
    print(f"| latency p50 / p95 ms | {result['latency_ms']['p50']} / {result['latency_ms']['p95']} | |")
    print("| time to first paint | not measured offline | |\n| checker, lesions | n/a | |")
    return path


def main(argv: list[str]) -> None:
    def opt(name: str, default: int) -> int:
        return int(argv[argv.index(name) + 1]) if name in argv else default

    cmd = argv[1]
    if cmd == "export":
        print(export(Path(argv[2])))
    elif cmd == "group":
        asyncio.run(group(Path(argv[2]), Path(argv[3]), opt("--per-pack", 30), opt("--total", 100),
                          opt("--max-cases", 400)))
    elif cmd == "hassan":
        asyncio.run(hassan(Path(argv[2]), Path(argv[3]), Path(argv[4])))
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
