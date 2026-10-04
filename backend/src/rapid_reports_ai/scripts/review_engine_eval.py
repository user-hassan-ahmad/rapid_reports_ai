"""Live evaluation harness for the review engine (spec §13), and the Gate F shadow read.

    # run the engine on recent production reports (no storage), 2 runs max, outputs reused:
    RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval run --limit 20 --runs 2
    # per-report and aggregate markdown summary of one or more run outputs:
    RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval summary <eval_*.jsonl> ...
    # hand-read page over stored shadow items (Gate F):
    RR_LAB_OUT=<scratchpad> .venv/bin/python -m rapid_reports_ai.scripts.review_engine_eval shadow-page --days 3

`run` takes the shadow path without the database: `engine.run_review`, then the Gate D log, then `shadow_items`
(exactly what `_run_and_store` persists), one report at a time so per-report and per-stage latency is what one
shadow run costs. Production text stays in RR_LAB_OUT (Hassan's standing read permission); nothing is written to
production."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Set

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[3]
MAX_RUNS = 2
REPORT_TIMEOUT_S = 300.0
STAGES = ("jev_ms", "lanes_ms", "adjudicator_ms", "verifier_ms", "negatives_wait_ms", "total", "gate_d_ms",
          "shadow_total_ms")


def cap_runs(n: int) -> int:
    return max(1, min(n, MAX_RUNS))


def out_path(stem: str, ext: str = "jsonl") -> Path:
    root = os.environ.get("RR_LAB_OUT")
    if not root:
        raise SystemExit("set RR_LAB_OUT to a scratchpad directory")
    d = Path(root) / "review_eval"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stem}_{os.getpid()}.{ext}"


def _rows(files: Iterable[Path]) -> List[dict]:
    out = []
    for f in files:
        for line in Path(f).read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def done_ids(files: Iterable[Path], run: int) -> Set[str]:
    """Reports already reviewed in `run` by an earlier output (a row that raised is not done)."""
    return {r["report_id"] for r in _rows(files) if r.get("run") == run and not r.get("exception")}


SQL_RECENT = """select id::text as id, report_type, input_data, candidate_reports->0 as cand, enhancement_json
from reports where candidate_reports is not null and created_at >= now() - interval '{days} days'
and coalesce(candidate_reports->0->>'error', '') = '' order by created_at desc limit {limit}"""

SQL_SHADOW = """select i.id::text as id, i.report_id::text as report_id, i.lane, i.kind, i.cls, i.label, i.reason,
       i.edit, i.verified, i.source_line, i.anchor, r.report_type,
       r.candidate_reports->0->>'content' as content, r.input_data
from report_review_items i join report_review_runs u on u.id = i.run_id join reports r on r.id = i.report_id
where u.mode = 'shadow' and u.created_at >= now() - interval '{days} days' order by i.report_id, i.created_at"""


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


# ── run ─────────────────────────────────────────────────────────────────────

async def review_one(r: dict, run: int) -> Optional[dict]:
    """The shadow pipeline for one production row, minus the database writes."""
    from rapid_reports_ai.review_engine import engine
    inp = engine.input_from_parts(r["id"], r["report_type"], _j(r["input_data"]), _j(r["cand"]),
                                  _j(r["enhancement_json"]))
    if inp is None:
        return None
    row = {"report_id": r["id"], "run": run, "report_type": r["report_type"], "pathway": inp.pathway,
           "report": inp.artifacts.report, "sections": list(inp.artifacts.sections or [])}
    t0 = time.monotonic()
    try:
        res = await asyncio.wait_for(engine.run_review(inp, run_id=f"eval-{run}"), REPORT_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - recorded, the next report still runs
        row.update(exception=f"{type(e).__name__}: {str(e)[:300]}",
                   timings_ms={"shadow_total_ms": int((time.monotonic() - t0) * 1000)})
        return row
    t = time.monotonic()
    gate_d = await engine._gate_d(inp)
    timings = dict(res.run["timings_ms"], gate_d_ms=int((time.monotonic() - t) * 1000),
                   shadow_total_ms=int((time.monotonic() - t0) * 1000))
    meta = {k: v for k, v in res.run.items() if k not in ("negatives_report", "negatives_post_removal_anchors")}
    row.update(run_meta=meta, timings_ms=timings, gate_d=gate_d, final_report=res.report,
               items=[i.model_dump() for i in engine.shadow_items(res.items)])
    return row


async def _run(rows: List[dict], runs: int, reuse: List[Path]) -> Path:
    """Sequential on purpose: one report at a time is the shadow load (RR_REVIEW_CONCURRENCY=1)."""
    out = out_path("eval")
    with open(out, "w") as fh:
        for run in range(1, runs + 1):
            skip = done_ids(reuse, run)
            for r in rows:
                if r["id"] in skip:
                    continue
                row = await review_one(r, run)
                if row is None:
                    continue
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                t = row.get("timings_ms") or {}
                print(f"run {run} {r['id'][:8]} {t.get('shadow_total_ms')}ms items={len(row.get('items') or [])} "
                      f"errors={sorted((row.get('run_meta') or {}).get('errors') or {}) or row.get('exception')}",
                      flush=True)
    return out


def cmd_run(args) -> None:
    load_dotenv(BACKEND / ".env")
    from rapid_reports_ai.scripts.review_labs.common import metabase
    cache = out_path("cases", "json").with_name("cases.json")
    rows = json.loads(cache.read_text()) if cache.exists() and not args.refresh else []
    if len(rows) < args.limit:           # a smaller earlier fetch (the smoke) is extended, never silently reused
        rows = metabase(SQL_RECENT.format(days=args.days, limit=args.limit))
        cache.write_text(json.dumps(rows, ensure_ascii=False))
    print(asyncio.run(_run(rows[: args.limit], cap_runs(args.runs), [Path(p) for p in args.reuse])))


# ── summary ─────────────────────────────────────────────────────────────────

def pct(xs: List[float], p: float) -> Optional[float]:
    """Linear-interpolated percentile (numpy's default), None when empty."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def item_counts(items: List[dict]) -> dict:
    out = {f: dict(Counter(i.get(f) for i in items)) for f in ("lane", "kind", "cls", "status")}
    out["would_pre_apply"] = sum(1 for i in items if (i.get("evidence") or {}).get("would_pre_apply"))
    return out


def edit_preview(report: str, edit: Optional[dict], sections: Optional[List[str]] = None) -> dict:
    """The changed line(s) before and after `edit` on `report` (after None when it does not apply)."""
    from rapid_reports_ai.review_engine import verifier
    from rapid_reports_ai.review_engine.items import Edit
    if not edit:
        return {"before": "", "after": None}
    new = verifier.apply_edit(report, Edit(**edit), sections)
    if new is None:
        return {"before": edit.get("find") or edit.get("after") or "", "after": None}
    i = 0
    while i < min(len(report), len(new)) and report[i] == new[i]:
        i += 1
    j = 0
    while j < min(len(report), len(new)) - i and report[-1 - j] == new[-1 - j]:
        j += 1
    start = report.rfind("\n", 0, i) + 1
    e_old, e_new = report.find("\n", len(report) - j), new.find("\n", len(new) - j)
    return {"before": report[start:e_old if e_old >= 0 else len(report)].strip(),
            "after": new[start:e_new if e_new >= 0 else len(new)].strip()}


def _errors(row: dict) -> dict:
    errs = dict((row.get("run_meta") or {}).get("errors") or {})
    if row.get("exception"):
        errs["exception"] = row["exception"]
    for lane, st in ((row.get("run_meta") or {}).get("lanes") or {}).items():
        if st == "failed":
            errs.setdefault(lane, "failed")
    return errs


def _fmt_counts(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], str(kv[0])))) or "none"


def questionable(row: dict) -> List[dict]:
    """Items worth a radiologist's hand read: would-pre-apply edits, open actions with a fix, unconfirmed or
    failed verification, accuracy flags on positive statements, and adjudicator fallbacks."""
    out = []
    for i in row.get("items") or []:
        ev, v = i.get("evidence") or {}, i.get("verified") or {}
        why = []
        if ev.get("would_pre_apply"):
            why.append("would pre-apply")
        if i.get("cls") == "action" and i.get("edit") and not ev.get("would_pre_apply"):
            why.append("action with a one-click fix")
        if v.get("unconfirmed") or v.get("failed"):
            why.append(f"verification {'unconfirmed' if v.get('unconfirmed') else ''} {v.get('failed') or ''}".strip())
        if i.get("lane") == "accuracy" and i.get("kind") in ("unsupported", "overstated") and i.get("cls") != "suppress":
            why.append(f"accuracy {i['kind']}")
        if (i.get("reason") or "").startswith("Not reviewed automatically"):
            why.append("adjudicator fallback")
        if why:
            out.append({"report_id": row["report_id"], "item": i, "why": why})
    return out


def summarise(rows: List[dict]) -> str:
    rows = [r for r in rows if r.get("run") is not None]
    L: List[str] = ["# Review engine live eval", ""]
    q: List[dict] = []
    for r in rows:
        items = r.get("items") or []
        t = r.get("timings_ms") or {}
        L += [f"## {r['report_id'][:8]} (run {r['run']}, {r.get('pathway')})", ""]
        errs = _errors(r)
        L.append(f"- latency ms: " + ", ".join(f"{k} {t[k]}" for k in STAGES if k in t))
        L.append(f"- errors/timeouts: {json.dumps(errs) if errs else 'none'}")
        if r.get("exception"):
            L.append("")
            continue
        c = item_counts(items)
        L.append(f"- items {len(items)}; lane: {_fmt_counts(c['lane'])}; cls: {_fmt_counts(c['cls'])}; "
                 f"status: {_fmt_counts(c['status'])}")
        L.append(f"- kind: {_fmt_counts(c['kind'])}")
        gd = r.get("gate_d") or {}
        if gd.get("edits"):
            L.append(f"- gate D: {len(gd['edits'])} edits, option A pre-apply "
                     f"{sum(1 for e in gd['edits'] if e.get('option_a_pre_apply'))}")
        wpa = [i for i in items if (i.get("evidence") or {}).get("would_pre_apply")]
        if wpa:
            L += ["", "Would pre-apply:", ""]
            for i in wpa:
                p = edit_preview(r["report"], i.get("edit"), r.get("sections"))
                L.append(f"- [{i['lane']}/{i['kind']}, {i['edit']['mode'] if i.get('edit') else '-'}] "
                         f"`{p['before']}` → `{p['after']}`")
        L.append("")
        q += questionable(r)
    ok = [r for r in rows if not r.get("exception")]
    L += ["# Aggregate", "", f"- reports {len(rows)} ({len(ok)} completed)"]
    for k in STAGES:
        xs = [(r.get("timings_ms") or {}).get(k) for r in ok]
        xs = [x for x in xs if x is not None]
        if xs:
            L.append(f"- {k}: p50 {pct(xs, 50)}, p90 {pct(xs, 90)}, max {max(xs)}")
    with_err = [r for r in rows if _errors(r)]
    L.append(f"- reports with any error/timeout: {len(with_err)}/{len(rows)}")
    err_kinds = Counter(k.split("_")[0] if k.startswith("adjudicator_") else k for r in rows for k in _errors(r))
    L.append(f"- error keys: {_fmt_counts(dict(err_kinds))}")
    n_items = [len(r.get("items") or []) for r in ok]
    if n_items:
        L.append(f"- items per report: p50 {pct(n_items, 50)}, mean {round(sum(n_items) / len(n_items), 1)}, "
                 f"max {max(n_items)}")
    all_items = [i for r in ok for i in r.get("items") or []]
    c = item_counts(all_items)
    L.append(f"- all items by lane: {_fmt_counts(c['lane'])}; cls: {_fmt_counts(c['cls'])}")
    L.append(f"- by kind: {_fmt_counts(c['kind'])}")
    modes = Counter((i.get("edit") or {}).get("mode") for i in all_items
                    if (i.get("evidence") or {}).get("would_pre_apply"))
    L.append(f"- would pre-apply: {c['would_pre_apply']} (inserts {modes.get('insert', 0)}, removals "
             f"{modes.get('remove', 0)}, replaces {modes.get('replace', 0)})")
    L += ["", "# Questionable items (hand read)", ""]
    for x in q:
        i = x["item"]
        L.append(f"- {x['report_id'][:8]} [{i['lane']}/{i['kind']} → {i['cls']}] {'; '.join(x['why'])}: "
                 f"{i.get('label')!r}; fix {json.dumps(i.get('edit'))}")
    return "\n".join(L) + "\n"


def cmd_summary(args) -> None:
    p = Path(args.out) if args.out else out_path("summary", "md")
    p.write_text(summarise(_rows([Path(f) for f in args.files])))
    print(p)


# ── shadow read page ────────────────────────────────────────────────────────

def cmd_shadow_page(args) -> None:
    load_dotenv(BACKEND / ".env")
    from rapid_reports_ai.scripts.review_labs import label_page
    from rapid_reports_ai.scripts.review_labs.common import metabase
    rows = metabase(SQL_SHADOW.format(days=args.days))
    cards = []
    for r in rows:
        edit, ver = _j(r["edit"]), _j(r["verified"])
        cards.append({"id": r["id"], "title": f"{r['report_id'][:8]} · {r['lane']}/{r['kind']} → {r['cls']}",
                      "meta": r["report_type"],
                      "blocks": [{"label": "Label / reason", "text": f"{r['label']}\n{r['reason'] or ''}"},
                                 {"label": "Fix", "text": json.dumps(edit) + "\nverified: " + json.dumps(ver)},
                                 {"label": "Dictated line", "text": r["source_line"] or ""},
                                 {"label": "Report", "text": r["content"] or "", "collapsed": True},
                                 {"label": "Dictation", "text": ((_j(r["input_data"]) or {}).get("variables") or {})
                                  .get("FINDINGS", ""), "collapsed": True}], "hidden": []})
    fields = [{"key": "verdict", "label": "Correct class", "type": "choice",
               "options": ["action", "minor", "info", "suppress"], "required": True},
              {"key": "fix_ok", "label": "Fix right", "type": "choice", "options": ["yes", "no", "n/a"]},
              {"key": "note", "type": "text", "label": "Note"}]
    p = out_path("shadow_read", "html")
    label_page.write_page(p, "Gate F · shadow read", "gateF-shadow-v1", cards, fields)
    print(p, len(cards))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=20)
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--runs", type=int, default=1)
    r.add_argument("--reuse", nargs="*", default=[])
    r.add_argument("--refresh", action="store_true")
    r.set_defaults(fn=cmd_run)
    m = sub.add_parser("summary")
    m.add_argument("files", nargs="+")
    m.add_argument("--out")
    m.set_defaults(fn=cmd_summary)
    s = sub.add_parser("shadow-page")
    s.add_argument("--days", type=int, default=3)
    s.set_defaults(fn=cmd_shadow_page)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
