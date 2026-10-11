"""Checklist lab (spec 2026-10-11-scratchpad-checklist-design §10): item writers, the expected-answer judge and
today's sheet path, on blind cases (tests/fixtures/hybrid_stack/checklist_cases.json). Sonnet 5.5 grades every
sentence once per case, blind to the arm.

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.checklist_lab [run|judge|report] [case ids...]
    LAB_OUT=<dir> (default ./checklist_lab_out), LAB_TAG=<run name>
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv(".env")
from pydantic import BaseModel  # noqa: E402

from rapid_reports_ai.enhancement_utils import _run_agent_with_model  # noqa: E402
from rapid_reports_ai.hybrid_stack.jev_stack import CONTRA_MIN, STATED_MIN, ask_checks, chip_state  # noqa: E402
from rapid_reports_ai.jev_client import JEV_MODEL, jev_post  # noqa: E402
from rapid_reports_ai.report_reconcile import (_qwen, _qwen_complete, dictated_negatives,  # noqa: E402
                                               duplicates_negative, split_findings)

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hybrid_stack" / "checklist_cases.json"
OUT = Path(os.environ.get("LAB_OUT", "checklist_lab_out"))
TAG = os.environ.get("LAB_TAG", "r1")
QWEN = "qwen-3.8-27b"
QSET = {"temperature": 0, "max_tokens": 3000, "reasoning_effort": "none"}
OPEN_CAP = 2

# ── writers ───────────────────────────────────────────────────────────────────
_CORE = """You are a radiology decision-support assistant reading a radiologist's dictation while they report the scan, with the images in front of them. For each dictated abnormal finding, decide what a consultant checks on THIS scan once that finding is reported, and write the statements they make when those checks are normal.

THRESHOLD: write an item only when all apply:
- a dictated finding implies a related structure, extension, spread or complication that this scan shows;
- its presence or absence changes the diagnosis, urgency, stage or next management step;
- the dictation has not already assessed it (a structure named with a qualifier, a measurement or a "no X" is assessed).

ONE ITEM PER ROOT FINDING: all checks stemming from one finding form one item; separate findings get separate items. Findings that together imply one check, in the same or different regions, form one item.

MODALITY: only what this exact scan type and protocol can show; never an enhancement, phase or sequence the scan lacks.

Order items by clinical urgency, most critical first. Return no items when nothing meets the threshold."""

D_FIELDS = """

NEVER deny anything dictated, its expected consequence, or a feature of a dictated diagnosis (its typical signs, or its expected effect on neighbouring structures): those are already implied.

Each item:
- source_text: the shortest verbatim phrase of the triggering finding (3-6 words, an exact substring of the dictation)
- region: the region of that finding, from REGIONS
- question: at most 12 words, the check directed at the images, ending with "?"
- rationale: 1-2 sentences: why this check matters for this finding on this scan
- negatives: 1-3 pertinent negatives, the most decisive first; each one short report sentence that names one absent finding and nothing else: no reason clause, never the word "or", no list."""

D1_FIELDS = """

Each item, in this order:
- source_text: the shortest verbatim phrase of the triggering finding (3-6 words, an exact substring of the dictation)
- region: the region of that finding, from REGIONS
- implied: at most 15 words listing imaging features the dictated finding already implies or leaves open: its typical signs, its expected effect on neighbouring structures, and any extent, relationship or certainty the radiologist left undecided (a lesion that "abuts" a structure). Features only, never differential diagnoses. Write "none" when nothing applies.
- question: at most 12 words, the check directed at the images, ending with "?"
- why: one short line: why this check matters for this finding
- answers: 1-3 statements the report makes when the check is normal, the most decisive first. Each is one short report sentence naming one absent finding: no reason clause, never the word "or", no list. Never deny, limit or decide anything listed in implied, and never deny anything dictated."""

REFERRAL_LINE = """

REFERRAL QUESTION: the clinical history may ask about a diagnosis the dictated findings do not answer. When the dictation does not address it, add one separate item for it (never merged into a finding's item) even though no dictated finding implies it: source_text empty, region the region it belongs to (it may be outside REGIONS), answers the statements that answer it when normal. Only the diagnosis asked about and its complications that change management; never an alternative diagnosis the history does not raise."""

REF_SYS = """From the scan type and clinical history alone, before any findings, list what the report must answer for the referral question: the diagnosis the history asks about, and any complication of it that changes management. Name an alternative diagnosis only when the history itself raises it. Only checks this scan type can show. When the history asks no diagnostic question (for example staging of a known diagnosis, or follow-up of a known finding), return no items.

Each item: region (the report region it belongs to); question (at most 12 words, directed at the images, ending with "?"); answer_if_normal (one short report sentence stating the normal answer in the simplest form, "<structure> is normal." or "No <finding>.", one finding only, never the word "or"); why (one short line). 0-3 items, most important first."""


class DItem(BaseModel):
    source_text: str = ""
    region: str = ""
    question: str = ""
    rationale: str = ""
    negatives: List[str] = []


class DItems(BaseModel):
    items: List[DItem]


class D1Item(BaseModel):
    source_text: str = ""
    region: str = ""
    implied: str = ""
    question: str = ""
    why: str = ""
    answers: List[str]


class D1Items(BaseModel):
    items: List[D1Item]


class RefItem(BaseModel):
    region: str = ""
    question: str
    answer_if_normal: str
    why: str = ""


class RefItems(BaseModel):
    items: List[RefItem]


def user_prompt(c: dict, ref: list | None = None) -> str:
    s = (f"SCAN TYPE: {c['scan_type']}\nCLINICAL HISTORY: {c['history']}\nREGIONS: {', '.join(c['regions'])}\n\n"
         f"DICTATION:\n{c['dictation']}")
    if ref:
        s += "\n\nREFERRAL ITEMS (already asked of the radiologist; never repeat them):\n" + "\n".join(
            f"- {r['question']}" for r in ref)
    return s


async def qwen(sys_p, user, out, timeout=25):
    r = await asyncio.wait_for(_run_agent_with_model(model_name=QWEN, output_type=out, system_prompt=sys_p,
                                                     user_prompt=user, api_key="", model_settings=dict(QSET)), timeout)
    return r.output


# ── judges ───────────────────────────────────────────────────────────────────
def _said(c):
    return dictated_negatives(split_findings(c["dictation"]))


async def judge_j1(c, answers):
    """Jev pair: stated >= STATED_MIN -> answered; contradicted >= CONTRA_MIN -> open; else assumed."""
    sc = await ask_checks(c["dictation"], [a["text"] for a in answers])
    out = []
    for a, (st, co) in zip(answers, sc):
        out.append("answered" if st >= STATED_MIN else "open" if co >= CONTRA_MIN else "assumed")
    return out, [(round(st, 2), round(co, 2)) for st, co in sc]


J2_MAP = {"dictated": "answered", "contradicted": "open", "expected": "open", "implicated": "open",
          "keep": "assumed", "default": "assumed"}


async def judge_j2(c, answers):
    """The production negatives classifier (QWEN_SYS_FULL)."""
    state = f"SCAN TYPE: {c['scan_type']}\nDICTATED FINDINGS:\n{c['dictation']}"
    qw = await _qwen_complete(state, [a["text"] for a in answers], [], [],
                              ask=lambda *a: _qwen(*a, full=True))
    by = {d.index: d.action for d in qw.negatives}
    labels = [by.get(i, "keep") for i in range(len(answers))]
    return [J2_MAP.get(lab, "assumed") for lab in labels], labels


def implied_question(text: str, implied: str) -> dict:
    return {"type": "noul", "instructions": (
        "The STATEMENT denies, limits or decides something that the dictated finding implies or leaves open, as "
        f"listed here: {implied}\nSTATEMENT: {text}")}


async def judge_j3(c, answers):
    """J1 plus a Jev check of each answer against its item's `implied`."""
    j1, raw = await judge_j1(c, answers)
    qs = {f"i{k}": implied_question(a["text"], a["implied"]) for k, a in enumerate(answers)
          if a.get("implied") and a["implied"].strip().lower() not in ("none", "")}
    flags = {}
    if qs:
        r = await jev_post({"model": JEV_MODEL, "state": f"DICTATION:\n{c['dictation']}", "questions": qs},
                           os.environ.get("OPENROUTER_API_KEY", ""), 4.0, None)
        r.raise_for_status()
        ans = r.json().get("answers") or {}
        flags = {int(k[1:]): float((v or {}).get("noul") or 0.0) for k, v in ans.items()}
    return j1, {"j1": raw, "implied": {k: round(v, 2) for k, v in flags.items()}}


JUDGES = {"J1": judge_j1, "J2": judge_j2, "J3": judge_j3}
J3_THRESHOLDS = (0.5, 0.7)


def settle(c, items: list[dict], states: list[str]) -> dict:
    """Per-answer states -> item states, the friction cap, and what reaches the report by default."""
    k = 0
    assumed, open_, dropped, answered = [], [], [], []
    open_per_region: dict = {}
    for it in items:
        st = states[k:k + len(it["answers"])]
        k += len(it["answers"])
        live = [(a, s) for a, s in zip(it["answers"], st) if s != "answered"]
        rec = {"region": it["region"], "question": it["question"], "src": it["src"],
               "answers": [a["text"] for a, _ in live], "why": it.get("why", "")}
        if not live:
            answered.append(rec)
        elif it["src"] == "referral":
            open_.append(rec)
        elif any(s == "open" for _, s in live):
            n = open_per_region.get(it["region"], 0)
            if n < OPEN_CAP:
                open_per_region[it["region"]] = n + 1
                open_.append(rec)
            else:
                dropped.append(rec)
        else:
            assumed += [{"region": it["region"], "text": a["text"]} for a, _ in live]
    return {"assumed": assumed, "open": open_, "dropped": dropped, "answered": answered}


def prefilter(c, items: list[dict]) -> list[dict]:
    """Code filters every arm shares: answers duplicating a dictated negative count as answered; duplicates drop."""
    said, seen = _said(c), []
    for it in items:
        keep = []
        for a in it["answers"]:
            t = a["text"].strip()
            if not t or duplicates_negative(t, seen):
                continue
            seen.append(t)
            keep.append({**a, "text": t, "dictated": duplicates_negative(t, said)})
        it["answers"] = keep
    return [it for it in items if it["answers"]]


async def judged(c, items):
    """All three judges on one item list; dictated answers are answered whatever the judge says."""
    flat = [a for it in items for a in it["answers"]]
    out = {}
    for name, fn in JUDGES.items():
        t0 = time.perf_counter()
        try:
            states, raw = await fn(c, flat) if flat else ([], [])
        except Exception as e:  # fail-safe: nothing is assumed when the judge fails
            states, raw = ["open"] * len(flat), f"{type(e).__name__}: {str(e)[:150]}"
        states = ["answered" if a["dictated"] else s for a, s in zip(flat, states)]
        ms = int((time.perf_counter() - t0) * 1000)
        if name != "J3":
            out[name] = {**settle(c, items, states), "raw": raw, "ms": ms}
            continue
        flags = raw.get("implied", {}) if isinstance(raw, dict) else {}
        for th in J3_THRESHOLDS:
            st = [("open" if s == "assumed" and flags.get(k, 0.0) >= th else s) for k, s in enumerate(states)]
            out[f"J3@{th}"] = {**settle(c, items, st), "raw": raw, "ms": ms}
    return out


# ── arms ─────────────────────────────────────────────────────────────────────
async def arm_d(c):
    t0 = time.perf_counter()
    out = await qwen(_CORE + D_FIELDS + REFERRAL_LINE, user_prompt(c), DItems)
    ms = int((time.perf_counter() - t0) * 1000)
    items = prefilter(c, [{"src": "referral" if not it.source_text.strip() else "finding", "region": it.region,
                           "question": it.question, "why": it.rationale,
                           "answers": [{"text": n, "implied": ""} for n in it.negatives]} for it in out.items])
    flat = [a for it in items for a in it["answers"]]
    sc = await ask_checks(c["dictation"], [a["text"] for a in flat]) if flat else []
    assumed, opt = [], []
    for a, it, (st, co) in zip(flat, [it for it in items for _ in it["answers"]], sc):
        s = "gone" if a["dictated"] else chip_state(st, co)
        if s == "included":
            assumed.append({"region": it["region"], "text": a["text"]})
        elif s == "optional":
            opt.append({"region": it["region"], "question": it["question"], "src": it["src"], "answers": [a["text"]]})
    return {"D": {"assumed": assumed, "open": opt, "dropped": [], "answered": [], "ms": ms}}


async def arm_d1(c):
    t0 = time.perf_counter()
    out = await qwen(_CORE + D1_FIELDS + REFERRAL_LINE, user_prompt(c), D1Items)
    ms = int((time.perf_counter() - t0) * 1000)
    items = prefilter(c, [{"src": "referral" if not it.source_text.strip() else "finding", "region": it.region,
                           "question": it.question, "why": it.why, "implied": it.implied,
                           "answers": [{"text": a, "implied": it.implied} for a in it.answers]} for it in out.items])
    res = await judged(c, items)
    return {f"D1+{j}": {**v, "writer_ms": ms, "items": items} for j, v in res.items()}


async def arm_d1ref(c):
    t0 = time.perf_counter()
    ref = await qwen(REF_SYS, f"SCAN TYPE: {c['scan_type']}\nCLINICAL HISTORY: {c['history']}", RefItems)
    ref_ms = int((time.perf_counter() - t0) * 1000)
    refd = [r.model_dump() for r in ref.items]
    t1 = time.perf_counter()
    out = await qwen(_CORE + D1_FIELDS, user_prompt(c, refd), D1Items)
    ms = int((time.perf_counter() - t1) * 1000)
    items = [{"src": "referral", "region": r["region"], "question": r["question"], "why": r["why"],
              "answers": [{"text": r["answer_if_normal"], "implied": ""}]} for r in refd]
    items += [{"src": "finding", "region": it.region, "question": it.question, "why": it.why,
               "answers": [{"text": a, "implied": it.implied} for a in it.answers]} for it in out.items]
    res = await judged(c, prefilter(c, items))
    return {f"D1ref+{j}": {**v, "writer_ms": ms, "ref_ms": ref_ms, "ref": refd} for j, v in res.items()}


D2_FIELDS = """

NEVER deny anything dictated, its expected consequence, or a feature of a dictated diagnosis (its typical signs, or its expected effect on neighbouring structures): those are already implied.

Each item:
- source_text: the shortest verbatim phrase of the triggering finding (3-6 words, an exact substring of the dictation)
- region: the region of that finding, from REGIONS
- question: at most 12 words, the check directed at the images, ending with "?"
- rationale: 1-2 sentences: why this check matters for this finding on this scan
- answers: 1-3 statements the report makes when the check is normal, the most decisive first. For each, first its kind, then its text:
  - kind "complication": the absence of a separate complication, spread or associated finding (in another structure or space);
  - kind "same_finding": it limits or decides the dictated finding's own extent, size, character, relationship to a neighbouring structure or certainty;
  - kind "referral": it answers the referral question.
  text: one short report sentence that names one absent finding and nothing else: no reason clause, never the word "or", no list."""


class Answer(BaseModel):
    kind: str = "complication"
    text: str


class D2Item(BaseModel):
    source_text: str = ""
    region: str = ""
    question: str = ""
    rationale: str = ""
    answers: List[Answer]


class D2Items(BaseModel):
    items: List[D2Item]


def bundled(t: str) -> bool:
    import re
    return bool(re.search(r"\bor\b", t)) or "," in t


async def arm_d2(c):
    """D's writer with a kind per answer: same_finding answers are never assumed (open, capped); bundles drop."""
    t0 = time.perf_counter()
    out = await qwen(_CORE + D2_FIELDS + REFERRAL_LINE.replace("answers the statements", "answers (kind referral) the statements"),
                     user_prompt(c), D2Items)
    ms = int((time.perf_counter() - t0) * 1000)
    items = []
    for it in out.items:
        src = "referral" if not it.source_text.strip() or any(a.kind == "referral" for a in it.answers) else "finding"
        ans = [{"text": a.text, "implied": "", "kind": a.kind} for a in it.answers if not bundled(a.text)]
        items.append({"src": src, "region": it.region, "question": it.question, "why": it.rationale, "answers": ans})
    items = prefilter(c, items)
    flat = [a for it in items for a in it["answers"]]
    res = {}
    for name in ("J1", "J2"):
        t1 = time.perf_counter()
        try:
            states, raw = await JUDGES[name](c, flat) if flat else ([], [])
        except Exception as e:
            states, raw = ["open"] * len(flat), f"{type(e).__name__}: {str(e)[:150]}"
        states = ["answered" if a["dictated"] else ("open" if a["kind"] == "same_finding" and s == "assumed" else s)
                  for a, s in zip(flat, states)]
        res[f"D2+{name}"] = {**settle(c, items, states), "raw": raw, "writer_ms": ms, "items": items,
                             "ms": int((time.perf_counter() - t1) * 1000)}
    return res


async def arm_s(c):
    """Today's production path: the analyser's sheet for this case, compiled by the brief (non-stack)."""
    from rapid_reports_ai.quick_report_analyser import generate_ephemeral_skill_sheet
    from rapid_reports_ai.quick_report_brief import compile_brief
    t0 = time.perf_counter()
    sh = await generate_ephemeral_skill_sheet(c["scan_type"], c["history"], api_key=os.environ.get("CEREBRAS_API_KEY", ""))
    sheet = sh.get("skill_sheet", "")
    b = await compile_brief(sheet, c["scan_type"], c["dictation"], c["history"])
    d = b.decisions
    stated = [n["text"] for n in d.get("negatives", []) if n.get("action") in ("keep", "implicated", "default")]
    stated += [f["text"] for f in d.get("finding_negatives", []) if f.get("outcome") == "stated"
               and f["text"] not in stated]
    offered = [o["text"] for o in d.get("options", []) if o.get("kind") == "finding_negative"]
    return {"S": {"assumed": [{"region": "", "text": t} for t in stated],
                  "open": [], "offered": offered, "dropped": [], "answered": [],
                  "ms": int((time.perf_counter() - t0) * 1000), "sheet": sheet}}


async def retry(fn, c):
    err = ""
    for k in range(3):
        try:
            return await fn(c)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
            await asyncio.sleep(1 + k)
    return {f"{fn.__name__}:error": {"error": err, "assumed": [], "open": [], "dropped": [], "answered": []}}


async def run(cases):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"runs_{TAG}.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    sem = asyncio.Semaphore(4)

    async def one(c):
        async with sem:
            fns = [globals()[f] for f in os.environ.get("LAB_ARMS", "arm_d,arm_d1,arm_d1ref,arm_s").split(",")]
            parts = await asyncio.gather(*(retry(f, c) for f in fns))
            arms = {k: v for p in parts for k, v in p.items()}
            arms = {**res.get(c["id"], {}), **arms}
            print(f"  {c['id']}: " + " ".join(f"{k}[a{len(v['assumed'])} o{len(v['open'])}]" for k, v in arms.items()),
                  flush=True)
            return c["id"], arms
    for cid, arms in await asyncio.gather(*(one(c) for c in cases)):
        res[cid] = arms
    path.write_text(json.dumps(res, indent=1))


# ── grading ──────────────────────────────────────────────────────────────────
JUDGE_SYS = """You are a consultant radiologist grading statements a reporting assistant proposes for a report. You get the case, a gold list (M = must, a consultant would state it; N = nice to have) and numbered statements.

Label every statement with exactly one of:
- a gold id (M1, N2, ...) when it states that gold negative (same structure and same finding; a narrower or broader wording of the same check counts);
- "extra_ok": a clinically pertinent statement for this case that is not in the gold;
- "low_value": true-sounding but routine or not pertinent to these findings or the referral question;
- "wrong": it would be false or unsafe to state without checking, because it contradicts or duplicates the dictation, denies an expected consequence or typical sign of a dictated finding, decides an extent or relationship the radiologist left open, is not assessable on this scan type, or is not one absent finding in one sentence.
Give a very short reason for each "wrong"."""


class Label(BaseModel):
    id: str
    label: str
    reason: str = ""


class Labels(BaseModel):
    labels: List[Label]


def sentences(arm: dict) -> list[str]:
    s = [a["text"] for a in arm.get("assumed", [])]
    for grp in ("open", "dropped"):
        for it in arm.get(grp, []):
            s += it["answers"]
    return s + list(arm.get("offered", []))


async def grade_case(c, arms):
    uniq = list(dict.fromkeys(t for a in arms.values() for t in sentences(a)))
    random.Random(c["id"]).shuffle(uniq)
    gold = "\n".join([f"M{i+1}. {g}" for i, g in enumerate(c["must"])] + [f"N{i+1}. {g}" for i, g in enumerate(c["nice"])])
    user = (f"SCAN TYPE: {c['scan_type']}\nHISTORY: {c['history']}\nDICTATION: {c['dictation']}\n\nGOLD:\n{gold or '(none)'}\n\n"
            "STATEMENTS:\n" + "\n".join(f"s{i}: {t}" for i, t in enumerate(uniq)) + "\n\nReturn one label per statement id.")
    r = await _run_agent_with_model(model_name="claude-sonnet-5-5", output_type=Labels, system_prompt=JUDGE_SYS,
                                    user_prompt=user, api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                                    model_settings={"temperature": 0, "max_tokens": 6000})
    lab = {}
    for x in r.output.labels:
        i = x.id.lstrip("s")
        if i.isdigit() and int(i) < len(uniq):
            lab[uniq[int(i)]] = (x.label, x.reason)
    return lab


async def grade(cases):
    runs = json.loads((OUT / f"runs_{TAG}.json").read_text())
    sem = asyncio.Semaphore(4)

    async def one(c):
        async with sem:
            return c["id"], await grade_case(c, runs[c["id"]])
    labels = dict(await asyncio.gather(*(one(c) for c in cases if c["id"] in runs)))
    (OUT / f"labels_{TAG}.json").write_text(json.dumps(labels, indent=1))


def report(cases, verbose: bool):
    runs = json.loads((OUT / f"runs_{TAG}.json").read_text())
    labels = json.loads((OUT / f"labels_{TAG}.json").read_text())
    byid = {c["id"]: c for c in cases}
    arms = sorted({k for a in runs.values() for k in a if ":error" not in k})
    tot = {k: {"m": 0, "surf": 0, "dflt": 0, "leak": 0, "caught": 0, "low": 0, "open": [], "assumed": 0, "ms": []} for k in arms}
    leaks = []
    for cid, ar in runs.items():
        c, lab = byid[cid], labels.get(cid, {})
        L = lambda t: (lab.get(t) or ["?"])[0]
        if verbose:
            print(f"\n== {cid}  ({c['history']})\n   {c['dictation']}")
        for k in arms:
            a = ar.get(k)
            if not a:
                continue
            t = tot[k]
            t["m"] += len(c["must"])
            assumed = [x["text"] for x in a["assumed"]]
            surfaced = assumed + [s for it in a["open"] for s in it["answers"]]
            gold_d = {L(s) for s in assumed if L(s).startswith("M")}
            gold_s = {L(s) for s in surfaced if L(s).startswith("M")}
            t["dflt"] += len(gold_d); t["surf"] += len(gold_s)
            t["leak"] += sum(L(s) == "wrong" for s in assumed)
            t["low"] += sum(L(s) == "low_value" for s in assumed)
            t["caught"] += sum(L(s) == "wrong" for it in a["open"] + a.get("dropped", []) for s in it["answers"])
            t["open"].append(len(a["open"])); t["assumed"] += len(assumed)
            t["ms"].append(a.get("writer_ms", a.get("ms", 0)))
            for s in assumed:
                if L(s) == "wrong":
                    leaks.append((k, cid, s, (lab.get(s) or ["", ""])[1]))
            if verbose:
                print(f"  {k:<9} must {len(gold_d)}→{len(gold_s)}/{len(c['must'])} | open: " +
                      "; ".join(f"[{it['src'][0]}] {it['question']}" for it in a["open"]) +
                      " | assumed: " + "; ".join(f"[{L(s)}] {s}" for s in assumed))
                if k == "S" and a.get("offered"):
                    print("            offered: " + "; ".join(f"[{L(s)}] {s}" for s in a["offered"]))
    print("\n== totals   must-haves: in report by default → surfaced (assumed + open questions)")
    for k in arms:
        t = tot[k]
        o = sorted(t["open"]) or [0]
        print(f"  {k:<9} must {t['dflt']:>2}→{t['surf']:>2}/{t['m']}  leaks {t['leak']}  caught {t['caught']}  "
              f"low {t['low']}  assumed {t['assumed']}  open/case median {statistics.median(o)} max {max(o)}  "
              f"writer p50 {int(statistics.median(t['ms'] or [0]))} ms")
    print("\n== leaks (assumed and graded wrong)")
    for k, cid, s, why in leaks:
        print(f"  {k:<9} {cid}: {s} — {why}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    cases = json.loads(FIX.read_text())
    if sys.argv[2:]:
        cases = [c for c in cases if c["id"] in sys.argv[2:]]
    if cmd in ("run", "all"):
        asyncio.run(run(cases))
    if cmd in ("judge", "all"):
        asyncio.run(grade(cases))
    if cmd in ("report", "all", "verbose"):
        report(cases, verbose=(cmd == "verbose"))
