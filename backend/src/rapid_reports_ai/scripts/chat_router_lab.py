"""Chat-edit router lab (spec "Testing", labs). Reported, not gated: Hassan reads the reports and decides.

Data, never in the repo: ~/Code/rr-template-conversion-private/synthetic/chat_router/
  sheets/<slug>.md              the sheet an item edits
  items/<id>.json               {"id","seed","set":"synthetic"|"real","category","sheet","instruction","context",
                                 "labels":{kind: 0|1 for every chat_router_jev.KINDS},"truth":[...]}
  lines/<id>.json               {"id","set","line","requires": 0|1}   (the rule-in-disguise question)
  sequences/<id>.json           {"id","sheet","touches":[heading or paragraph names],"turns":[{"instruction","truth"}]}
  runs/<stage>/run<k>/<id>.json raw outputs (a runner skips ids it already has)
Truth entries: {"kind","key","choice"} for a ledger write (a new FIXED / NORMAL / NEGATIVE line too) |
  {"kind":"layout","op":{apply_op dict}} | {"kind":<k>,"expect":"card"} | {"kind":"style"}.

  python -m rapid_reports_ai.scripts.chat_router_lab tag|requires|calls|e2e --root R --run K
  python -m rapid_reports_ai.scripts.chat_router_lab score --root R --stage tag|requires|calls|e2e --runs 1 2"""
from __future__ import annotations

import os

# The lab needs no database: a frozen checkout run with PYTHONPATH=src must not reach for the app's Postgres.
os.environ.setdefault("DATABASE_URL", "sqlite://")

import argparse
import asyncio
import difflib
import json
import statistics
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_jev as J
from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import chat_router_sheet as sh
from rapid_reports_ai import chat_router_views as V

DEFAULT_ROOT = Path.home() / "Code/rr-template-conversion-private/synthetic/chat_router"
THRESHOLDS = (0.3, 0.35, 0.4, 0.5, 0.6, 0.7)
CONCURRENCY = 4


# ── pure scoring ────────────────────────────────────────────────────────────────────────────────────────────────
def prf(pairs: Iterable) -> dict:
    pairs = list(pairs)
    tp = sum(1 for t, p in pairs if t and p)
    fp = sum(1 for t, p in pairs if not t and p)
    fn = sum(1 for t, p in pairs if t and not p)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"p": prec, "r": rec, "f1": f1, "n": len(pairs), "tp": tp, "fp": fp, "fn": fn}


def tag_table(items: List[dict], scores: Dict[str, dict], thresholds: Sequence[float] = THRESHOLDS) -> dict:
    """kind -> threshold -> prf over the items with a score."""
    have = [it for it in items if isinstance(scores.get(it["id"]), dict) and "error" not in scores[it["id"]]]
    return {k: {thr: prf((bool(it["labels"][k]), scores[it["id"]][k] >= thr) for it in have) for thr in thresholds}
            for k in J.KINDS}


def band(items: List[dict], scores: Dict[str, dict], lo: float, hi: float) -> dict:
    """kind -> {"pos", "neg"}: items scored in [lo, hi), by their label (what the card band would catch)."""
    out = {k: {"pos": 0, "neg": 0} for k in J.KINDS}
    for it in items:
        s = scores.get(it["id"])
        if not isinstance(s, dict) or "error" in s:
            continue
        for k in J.KINDS:
            if lo <= s[k] < hi:
                out[k]["pos" if it["labels"][k] else "neg"] += 1
    return out


def habit_confusion(items: List[dict], scores: Dict[str, dict]) -> dict:
    """Placeholder for item 5 (findings-triggered rows): items planted as a reporting habit ("when X is abnormal,
    also say Y", category "habit") and how often Jev tags them as a normal-finding change. Reported, not used."""
    habit = [it for it in items if it.get("category") == "habit" and isinstance(scores.get(it["id"]), dict)
             and "error" not in scores[it["id"]]]
    tagged = [it for it in habit if scores[it["id"]]["normal"] >= J.TAG_MIN]
    return {"habit_items": len(habit), "tagged_normal": len(tagged),
            "labelled_normal": sum(bool(it["labels"]["normal"]) for it in habit),
            "tagged_normal_but_not_labelled": sum(not it["labels"]["normal"] for it in tagged)}


def _norm_obj(x):
    if isinstance(x, str):
        return sh.norm(x).rstrip(".")
    if isinstance(x, dict):
        return {k: _norm_obj(v) for k, v in x.items() if v not in ("", [], None)}
    if isinstance(x, list):
        return [_norm_obj(v) for v in x]
    return x


def _concept_view(choice: Optional[dict]):
    state, d, w, cond = L.concept_state(choice or {})
    return state, _norm_obj(d), _norm_obj(w), cond


def _concept_match(rec: dict, truth: dict) -> bool:
    """A concept compares by state and wordings; a truth "condition" (a state name or the text) must match too."""
    if rec.get("action") not in ("ledger", "edit") or _norm_obj(rec.get("key")) != _norm_obj(truth.get("key")):
        return False
    tc = truth.get("choice") or {}
    rs, rd, rw, rc = _concept_view(rec.get("choice"))
    ts, tdf, tw, _ = _concept_view(tc)
    cond_ok = not tc.get("condition") or L.condition_for(truth["key"], tc["condition"]) == rc
    return (rs, rd, rw) == (ts, tdf, tw) and cond_ok


def match(rec: dict, truth: dict) -> bool:
    if rec.get("kind") != truth.get("kind"):
        return False
    if truth["kind"] == "concept" and truth.get("expect") != "card":
        return _concept_match(rec, truth)
    if truth.get("expect") == "card":
        return rec.get("action") == "card"
    if truth["kind"] == "style":
        return rec.get("action") == "style"
    if truth["kind"] == "layout":
        return rec.get("action") == "edit" and _norm_obj(rec.get("op")) == _norm_obj(truth.get("op"))
    return (rec.get("action") in ("ledger", "edit") and _norm_obj(rec.get("key")) == _norm_obj(truth.get("key"))
            and _norm_obj(rec.get("choice")) == _norm_obj(truth.get("choice")))


def score_changes(truth: List[dict], records: List[dict]) -> dict:
    used = set()
    correct = 0
    for t in truth:
        hit = next((i for i, r in enumerate(records) if i not in used and match(r, t)), None)
        if hit is not None:
            used.add(hit)
            correct += 1
    extra = [r for i, r in enumerate(records) if i not in used and r.get("action") in ("ledger", "edit")]
    return {"truth": len(truth), "correct": correct, "missing": len(truth) - correct, "extra_applied": len(extra),
            "cards": sum(r.get("action") == "card" for r in records),
            "rejected": sum(r.get("action") == "reject" for r in records),
            "asked": sum(r.get("action") == "ask" for r in records),
            "invented": sum(bool(r.get("invented")) for r in records)}


def _allowed(line: sh.Line, allowed: set) -> bool:
    return sh.norm(line.heading) in allowed or bool(line.paragraph and sh.norm(line.paragraph) in allowed)


def unrelated_changes(start: str, end: str, touches: List[str]) -> int:
    """Non-blank lines changed (either side) outside the headings / paragraphs a sequence may touch."""
    allowed = {sh.norm(t) for t in touches}
    a, b = start.splitlines(), end.splitlines()
    wa, wb = sh.walk(start), sh.walk(end)
    n = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        n += sum(1 for i in range(i1, i2) if a[i].strip() and not _allowed(wa[i], allowed))
        n += sum(1 for j in range(j1, j2) if b[j].strip() and not _allowed(wb[j], allowed))
    return n


def unsure_counts(records: List[dict], truth: List[dict]) -> dict:
    """Changes applied for a kind tagged in the unsure band (route llm_unsure, decision D-R2), and how many match no
    planted truth: the lab's stand-in for "later undone"."""
    unsure = [r for r in records if r.get("route") == "llm_unsure" and r.get("action") in ("ledger", "edit", "style")]
    return {"unsure": len(unsure), "unsure_wrong": sum(1 for r in unsure if not any(match(r, t) for t in truth))}


def verdict_record(v: CH.Verdict) -> dict:
    return {"kind": v.kind, "action": v.action, "key": v.key, "choice": v.choice, "op": v.op, "route": v.route,
            "invented": v.invented, "reason": v.reason, "detail": v.detail}


def turn_records(t: R.Turn) -> List[dict]:
    """What a routed turn did, in the scorer's record form."""
    out = []
    for r in t.records:
        if r["type"] == "ledger":
            new = r["change"].get("new")
            out.append({"kind": r["change"]["kind"], "action": "ledger", "key": r["change"]["key"],
                        "choice": new.get("choice") if isinstance(new, dict) and "choice" in new else new, "op": None,
                        "route": r.get("route", "")})
        elif r["type"] == "edit":
            out.append({"kind": r["kind"], "action": "edit", "key": "", "choice": None, "op": r["op"],
                        "route": r.get("route", "")})
        elif r["type"] == "style":
            out.append({"kind": "style", "action": "style", "route": r.get("route", "")})
    for c in t.cards:
        out.append({"kind": c.get("ledger_kind") or (c.get("apply") or {}).get("kind"), "action": "card",
                    "key": c.get("key", ""), "choice": None, "op": None})
    return out


def md_table(header: List[str], rows: List[list]) -> str:
    def cell(v):
        if v is None:
            return "–"
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


# ── data ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _load(root: Path, sub: str) -> List[dict]:
    return [json.loads(p.read_text()) for p in sorted((Path(root) / sub).glob("*.json"))]


def load_items(root: Path) -> List[dict]:
    items = _load(root, "items")
    for it in items:
        missing = [k for k in J.KINDS if k not in (it.get("labels") or {})]
        if missing:
            raise ValueError(f"{it.get('id')}: labels missing {missing}")
    return items


def _sheet(root: Path, slug: str) -> str:
    return (Path(root) / "sheets" / f"{slug}.md").read_text()


def _out(root: Path, stage: str, run: int) -> Path:
    d = Path(root) / "runs" / stage / f"run{run}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _runs(root: Path, stage: str, run: int) -> Dict[str, dict]:
    d = Path(root) / "runs" / stage / f"run{run}"
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.exists() else {}


# ── runners (call Jev / Qwen; run by the controller) ────────────────────────────────────────────────────────────
async def _each(rows: List[dict], out: Path, fn) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(row):
        dest = out / f"{row['id']}.json"
        if dest.exists():
            return
        async with sem:
            t0 = time.monotonic()
            try:
                res = await fn(row)
            except Exception as e:
                res = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            res["ms"] = int((time.monotonic() - t0) * 1000)
        dest.write_text(json.dumps({"id": row["id"], **res}, indent=1))
    await asyncio.gather(*(one(r) for r in rows))


async def run_tag(root: Path, run: int) -> None:
    async def fn(it):
        sheet = _sheet(root, it["sheet"])
        return {"scores": await J.tag(it["instruction"], sh.scan_type(sheet), it.get("context", ""))}
    await _each(load_items(root), _out(root, "tag", run), fn)


async def run_requires(root: Path, run: int) -> None:
    async def fn(row):
        return {"score": (await J.requires([row["line"]]))[0]}
    await _each(_load(root, "lines"), _out(root, "requires", run), fn)


async def run_calls(root: Path, run: int) -> None:
    """The targeted calls for the planted kinds (not Jev's tags): call accuracy on its own."""
    async def fn(it):
        sheet = _sheet(root, it["sheet"])
        ctx = CH.Ctx(sheet, [], it["instruction"])
        records, questions, errors = [], [], []
        for k in [k for k in R.WORK_KINDS if it["labels"].get(k)]:
            try:
                res = await C.call_kind(k, it["instruction"], V.view(k, sheet, []), it.get("context", ""))
            except Exception as e:
                errors.append(f"{k}: {type(e).__name__}")
                continue
            if res.question:
                questions.append(res.question)
            if k == "style":
                edited = sh.splice(sheet, {b.id: b.text for b in res.blocks})
                records.append({"kind": "style", "action": "style" if res.blocks else "none",
                                "units_unchanged": sh.units_unchanged(sheet, edited), "blocks": len(res.blocks)})
            else:
                records += [verdict_record(CH.validate(k, c, ctx)) for c in res.changes]
        return {"records": records, "questions": questions, "errors": errors}
    await _each(load_items(root), _out(root, "calls", run), fn)


async def run_e2e(root: Path, run: int) -> None:
    """route_turn over each scripted sequence (real Jev, Qwen and the save function)."""
    async def fn(seq):
        start = sheet = _sheet(root, seq["sheet"])
        ledger: List[dict] = []
        turns = []
        for turn in seq["turns"]:
            try:
                t = await R.route_turn(sheet, ledger, turn["instruction"])
            except R.Fallback as e:
                turns.append({"instruction": turn["instruction"], "fallback": str(e)})
                continue
            sheet, ledger = t.sheet, t.ledger
            recs = turn_records(t)
            turns.append({"instruction": turn["instruction"], "records": recs, "reply": t.reply,
                          "applied": t.applied, "ms": t.evidence.get("ms"), "unsure_kinds": t.evidence.get("unsure", []),
                          "score": {**score_changes(turn.get("truth") or [], recs),
                                    **unsure_counts(recs, turn.get("truth") or [])}})
        return {"turns": turns, "final_sheet": sheet, "unrelated": unrelated_changes(start, sheet, seq["touches"])}
    await _each(_load(root, "sequences"), _out(root, "e2e", run), fn)


# ── reports (tables only; the controller writes the prose report) ───────────────────────────────────────────────
def _sum(dicts: List[dict]) -> dict:
    out: Dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def report_tag(root: Path, runs: List[int]) -> str:
    items = load_items(root)
    parts = []
    for run in runs:
        scores = {k: v.get("scores") or {"error": v.get("error")} for k, v in _runs(root, "tag", run).items()}
        for subset in ("synthetic", "real"):
            its = [it for it in items if it["set"] == subset]
            if not its:
                parts.append(f"### run {run}, {subset}: no items")
                continue
            t = tag_table(its, scores)
            rows = [[k, thr, t[k][thr]["p"], t[k][thr]["r"], t[k][thr]["f1"], t[k][thr]["n"]]
                    for k in J.KINDS for thr in THRESHOLDS]
            parts.append(f"### run {run}, {subset}: precision / recall per kind\n\n"
                         + md_table(["kind", "threshold", "P", "R", "F1", "n"], rows))
            b = band(its, scores, J.TAG_UNSURE, J.TAG_MIN)
            parts.append(f"### run {run}, {subset}: unsure band [{J.TAG_UNSURE}, {J.TAG_MIN}), decided by the call\n\n"
                         + md_table(["kind", "labelled yes", "labelled no"], [[k, b[k]["pos"], b[k]["neg"]] for k in J.KINDS]))
            have = [it for it in its if isinstance(scores.get(it["id"]), dict) and "error" not in scores[it["id"]]]
            in_band = sum(any(J.TAG_UNSURE <= scores[it["id"]][k] < J.TAG_MIN for k in J.KINDS) for it in have)
            parts.append(f"items with any kind in the unsure band: {in_band}/{len(have)}")
            h = habit_confusion(its, scores)
            parts.append(f"### run {run}, {subset}: habit vs normal (item 5 placeholder)\n\n"
                         + md_table(list(h), [list(h.values())]))
            cats = sorted({it["category"] for it in its})
            rows = []
            for cat in cats:
                ci = [it for it in its if it["category"] == cat]
                ct = tag_table(ci, scores, (J.TAG_MIN,))
                rows.append([cat, len(ci)] + [ct[k][J.TAG_MIN]["r"] for k in J.KINDS])
            parts.append(f"### run {run}, {subset}: recall at {J.TAG_MIN} by category\n\n"
                         + md_table(["category", "n", *J.KINDS], rows))
    if len(runs) >= 2:
        a, b2 = (_runs(root, "tag", r) for r in runs[:2])
        same = [(a[i]["scores"][k] >= J.TAG_MIN) == (b2[i]["scores"][k] >= J.TAG_MIN)
                for i in a if i in b2 and "scores" in a[i] and "scores" in b2[i] for k in J.KINDS]
        parts.append(f"### run-to-run agreement at {J.TAG_MIN}: {sum(same)}/{len(same)}")
    errors = sum(1 for run in runs for v in _runs(root, "tag", run).values() if "error" in v)
    ms = [v["ms"] for run in runs for v in _runs(root, "tag", run).values() if "ms" in v]
    parts.append(f"### errors: {errors}; median ms: {statistics.median(ms) if ms else None}")
    return "\n\n".join(parts)


def report_requires(root: Path, runs: List[int]) -> str:
    lines = {r["id"]: r for r in _load(root, "lines")}
    parts = []
    for run in runs:
        got = _runs(root, "requires", run)
        for subset in ("synthetic", "real"):
            ids = [i for i, r in lines.items() if r["set"] == subset and "score" in got.get(i, {})]
            rows = [[thr, *(lambda m: [m["p"], m["r"], m["f1"], m["n"]])(
                prf((bool(lines[i]["requires"]), got[i]["score"] >= thr) for i in ids))] for thr in THRESHOLDS]
            parts.append(f"### run {run}, {subset}\n\n" + md_table(["threshold", "P", "R", "F1", "n"], rows))
    return "\n\n".join(parts)


def report_calls(root: Path, runs: List[int]) -> str:
    items = {it["id"]: it for it in load_items(root)}
    parts = []
    for run in runs:
        got = _runs(root, "calls", run)
        for subset in ("synthetic", "real"):
            rows = []
            for k in R.WORK_KINDS:
                scores, errors, questions, unit_breaks = [], 0, 0, 0
                for i, out in got.items():
                    it = items.get(i)
                    if not it or it["set"] != subset or not it["labels"].get(k):
                        continue
                    recs = [r for r in out.get("records", []) if r.get("kind") == k]
                    truth = [t for t in it.get("truth", []) if t.get("kind") == k]
                    scores.append(score_changes(truth, recs))
                    errors += sum(e.startswith(k) for e in out.get("errors", []))
                    questions += len(out.get("questions", []))
                    unit_breaks += sum(1 for r in recs if r.get("units_unchanged") is False)
                s = _sum(scores)
                rows.append([k, len(scores), s.get("truth", 0), s.get("correct", 0), s.get("missing", 0),
                             s.get("extra_applied", 0), s.get("cards", 0), s.get("rejected", 0), s.get("asked", 0),
                             s.get("invented", 0), errors, questions, unit_breaks])
            parts.append(f"### run {run}, {subset}\n\n" + md_table(
                ["kind", "items", "truth", "correct", "missing", "extra applied", "cards", "rejected", "asked",
                 "invented", "errors", "questions", "style broke a unit"], rows))
    return "\n\n".join(parts)


def report_e2e(root: Path, runs: List[int]) -> str:
    parts = []
    for run in runs:
        got = _runs(root, "e2e", run)
        rows, ms = [], []
        for i, out in sorted(got.items()):
            turns = out.get("turns", [])
            s = _sum([t["score"] for t in turns if "score" in t])
            ms += [t["ms"] for t in turns if t.get("ms") is not None]
            rows.append([i, len(turns), sum("fallback" in t for t in turns), s.get("truth", 0), s.get("correct", 0),
                         s.get("extra_applied", 0), s.get("cards", 0), sum(bool(t.get("unsure_kinds")) for t in turns),
                         s.get("unsure", 0), s.get("unsure_wrong", 0), out.get("unrelated")])
        parts.append(f"### run {run} (median ms per turn: {statistics.median(ms) if ms else None})\n\n" + md_table(
            ["sequence", "turns", "fallbacks", "truth", "correct", "extra applied", "cards", "turns with an unsure band",
             "unsure-band changes", "of them wrong", "unrelated lines"], rows))
    return "\n\n".join(parts)


REPORTS = {"tag": report_tag, "requires": report_requires, "calls": report_calls, "e2e": report_e2e}
RUNNERS = {"tag": run_tag, "requires": run_requires, "calls": run_calls, "e2e": run_e2e}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=[*RUNNERS, "score"])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--stage", choices=list(REPORTS))
    ap.add_argument("--runs", type=int, nargs="+", default=[1])
    a = ap.parse_args()
    root = a.root.expanduser()
    if a.cmd == "score":
        out = root / f"REPORT_{a.stage}_tables.md"
        out.write_text(REPORTS[a.stage](root, a.runs) + "\n")
        print(out)
        return
    asyncio.run(RUNNERS[a.cmd](root, a.run))


if __name__ == "__main__":
    main()
