"""Findings-triggered rows lab (spec 2026-10-13-findings-triggered-rows-design, "Lab first"). Reported, not gated:
it prints tables and writes JSON under the private folder; Hassan decides (TRIGGER_MIN, TRIGGER_WORDING).

From a frozen checkout's backend/ (the code under test never changes mid-run):

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab propose [--run 1|2] [--only a,b]
    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab trigger [--run 1|2] [--sets sets|heldout] [--wording A|B]
    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.triggered_rows_lab report --stage propose|trigger [--sets ...] [--run 1|2] [--wording A|B]

<dir> (--root) defaults to ~/Code/rr-template-conversion-private/synthetic/triggered_rows (never the repo).
The trigger report gives: precision / recall per dictation variant (met, not met, negated, hedged, other region, two
findings, real) at TRIGGER_MIN and accuracy across thresholds; the silent 0.35-0.5 band rate (Hassan H2);
already-answered accuracy; rows per session against the caps (how often a generic row is pushed out). The proposal
report gives precision / recall and the share of quotes verified.
Proposal sets <dir>/propose/<slug>.json:
  {"slug", "scan_type", "examples": [str], "truth": {"habits": [{"id", "paragraph", "condition", "reports": [int]}]}}
Proposal labels (a Claude subagent; never the model under test) <dir>/labels/propose/run<k>/<slug>.json:
  {"<index into the run's habits>": "<truth id>" | null}
Trigger sets <dir>/<sets>/<slug>.json (sets: synthetic; heldout: real dictations):
  {"slug", "scan_type", "sheet", "dictations": [{"id", "category", "text", "met": [condition], "answered": {condition: "yes"|"no"},
   "generic": [region]}]}
Outputs <dir>/runs/<stage>/<sets>/run<k>[-<wording>]/<slug>.json and <dir>/REPORT_<stage>_<sets>.md. A runner skips any
output file that already exists (eval economy)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
DEFAULT_ROOT = Path.home() / "Code" / "rr-template-conversion-private" / "synthetic" / "triggered_rows"
CATEGORIES = ("met", "not_met", "negated", "hedged", "other_region", "two_findings", "real")


def md_table(head: List[str], rows: List[list]) -> str:
    out = ["| " + " | ".join(str(h) for h in head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 3) if b else None


def load(root: Path, sub: str, only: Optional[List[str]] = None) -> List[dict]:
    sets = [json.loads(p.read_text()) for p in sorted((root / sub).glob("*.json"))]
    return [s for s in sets if not only or s["slug"] in only]


# ── proposal lab ─────────────────────────────────────────────────────────────────────────────────────────────────

def score_propose(s: dict, payload: dict, labels: Dict[str, Optional[str]]) -> dict:
    """One set: proposals matched (by the labeller) to planted habits. A habit planted in 2+ reports is real; one
    planted in a single report must not be proposed."""
    truth = {h["id"]: h for h in s["truth"].get("habits", [])}
    real = {k for k, h in truth.items() if len(set(h["reports"])) >= 2}
    proposed = payload.get("habits", [])
    matched = [labels.get(str(i)) for i in range(len(proposed))]
    tp = sum(1 for m in matched if m in real)
    return {"slug": s["slug"], "proposed": len(proposed), "tp": tp, "fp": len(proposed) - tp,
            "single_proposed": sum(1 for m in matched if m in truth and m not in real), "real": len(real),
            "found": len({m for m in matched if m in real}), "raw_quotes": payload.get("raw_quotes", 0),
            "verified_quotes": payload.get("verified_quotes", 0)}


def summarise_propose(rows: List[dict]) -> dict:
    tot = {k: sum(r[k] for r in rows) for k in ("proposed", "tp", "real", "found", "raw_quotes", "verified_quotes",
                                                "single_proposed")}
    return {"precision": _ratio(tot["tp"], tot["proposed"]), "recall": _ratio(tot["found"], tot["real"]),
            "quotes_verified": _ratio(tot["verified_quotes"], tot["raw_quotes"]),
            "single_proposed": tot["single_proposed"], "sets": len(rows)}


async def _propose_one(s: dict) -> dict:
    from rapid_reports_ai import template_decision_run as tdr
    raw = await tdr._qwen(s["examples"], s.get("scan_type", ""))
    run = tdr.check_quotes(raw, s["examples"])
    return {"slug": s["slug"], "raw_habits": [h.model_dump() for h in raw.habits],
            "habits": [h.model_dump() for h in run.habits],
            "raw_quotes": sum(len(h.quotes) for h in raw.habits),
            "verified_quotes": sum(1 for h in raw.habits for q in h.quotes if tdr.verified(q, s["examples"]))}


async def propose(root: Path, run_no: int, only: Optional[List[str]]) -> None:
    out = root / "runs" / "propose" / "sets" / f"run{run_no}"
    out.mkdir(parents=True, exist_ok=True)
    for s in load(root, "propose", only):
        f = out / f"{s['slug']}.json"
        if f.exists():
            continue
        payload = await _propose_one(s)
        f.write_text(json.dumps(payload, indent=1))
        print(f"{s['slug']}: raw={len(payload['raw_habits'])} kept={len(payload['habits'])}")


# ── trigger lab ──────────────────────────────────────────────────────────────────────────────────────────────────

def score_trigger(s: dict, payload: dict) -> List[dict]:
    """One row per (dictation, condition): the planted truth, Jev's score, and the stated scores of an ask habit."""
    rows = []
    for d in s["dictations"]:
        for cond, p in (payload["scores"].get(d["id"]) or {}).items():
            rows.append({"id": d["id"], "category": d["category"], "condition": cond, "truth": cond in d.get("met", []),
                         "score": p, "answered": (d.get("answered") or {}).get(cond),
                         "stated": (payload.get("stated", {}).get(d["id"]) or {}).get(cond)})
    return rows


def trigger_table(rows: List[dict], thresholds: Sequence[float] = THRESHOLDS) -> Dict[str, dict]:
    """Accuracy per category (and "all") at each threshold."""
    out: Dict[str, dict] = {}
    for cat in [*sorted({r["category"] for r in rows}), "all"]:
        sel = [r for r in rows if cat == "all" or r["category"] == cat]
        out[cat] = {"n": len(sel), **{t: _ratio(sum((r["score"] >= t) == r["truth"] for r in sel), len(sel))
                                      for t in thresholds}}
    return out


def prf_table(rows: List[dict], threshold: float) -> Dict[str, dict]:
    """Precision / recall of "met" per dictation variant (and "all") at the cut-off. None where undefined."""
    out: Dict[str, dict] = {}
    for cat in [*sorted({r["category"] for r in rows}), "all"]:
        sel = [r for r in rows if cat == "all" or r["category"] == cat]
        tp = sum(r["score"] >= threshold and r["truth"] for r in sel)
        fp = sum(r["score"] >= threshold and not r["truth"] for r in sel)
        fn = sum(r["score"] < threshold and r["truth"] for r in sel)
        out[cat] = {"n": len(sel), "tp": tp, "fp": fp, "fn": fn, "p": _ratio(tp, tp + fp), "r": _ratio(tp, tp + fn)}
    return out


def band_table(rows: List[dict], lo: float = 0.35, hi: float = 0.5) -> dict:
    """Hassan H2: a score in [lo, hi) stays silent. How often that band occurs, and how many of its rows were truly
    met (rows the scratchpad does not ask although the finding was there)."""
    band = [r for r in rows if lo <= r["score"] < hi]
    return {"n": len(rows), "in_band": len(band), "in_band_met": sum(r["truth"] for r in band),
            "rate": _ratio(len(band), len(rows))}


def answered_table(rows: List[dict], stated_min: float) -> dict:
    """Already-answered folding on met ask habits: folded when either sentence is stated at stated_min."""
    sel = [r for r in rows if r["truth"] and r["stated"] is not None]
    pred = [max(r["stated"]) >= stated_min for r in sel]
    truth = [r["answered"] in ("yes", "no") for r in sel]
    return {"n": len(sel), "correct": sum(p == t for p, t in zip(pred, truth)),
            "false_fold": sum(p and not t for p, t in zip(pred, truth)),
            "missed": sum(t and not p for p, t in zip(pred, truth))}


def cap_pressure(template_regions: List[str], generic_regions: List[str], per_region: int = 0, total: int = 0) -> dict:
    """The spec's ranking simulated: template rows first, then generic finding rows, within the same caps (2 per
    region, 4 in all). generic_pushed: generic rows shown without the template rows but not with them."""
    from rapid_reports_ai.hybrid_stack.items import MAX_ROWS, MAX_ROWS_PER_REGION
    per_region, total = per_region or MAX_ROWS_PER_REGION, total or MAX_ROWS

    def fit(rows):
        shown, count = [], {}
        for kind, region in rows:
            if count.get(region, 0) >= per_region or len(shown) >= total:
                continue
            count[region] = count.get(region, 0) + 1
            shown.append(kind)
        return shown
    alone = fit([("finding", r) for r in generic_regions])
    both = fit([*(("template", r) for r in template_regions), *(("finding", r) for r in generic_regions)])
    return {"template_rows": both.count("template"), "template_capped": len(template_regions) - both.count("template"),
            "generic_pushed": len(alone) - both.count("finding")}


def session_caps(s: dict, payload: dict, threshold: float) -> List[dict]:
    asks = {h["condition"]: h["region"] for h in payload["habits"] if h["mode"] == "ask"}
    out = []
    for d in s["dictations"]:
        sc = payload["scores"].get(d["id"]) or {}
        regions = [asks[c] for c, p in sc.items() if c in asks and p >= threshold]
        out.append({"id": d["id"], **cap_pressure(regions, d.get("generic", []))})
    return out


async def _trigger_one(s: dict, wording: str) -> dict:
    from rapid_reports_ai import template_sheet_grammar as tsg
    from rapid_reports_ai.hybrid_stack import habits as H
    from rapid_reports_ai.hybrid_stack import jev_stack as J
    habits = H.template_habits(tsg.parse_sheet(s["sheet"]).structure, None, all_habits=True)   # hand-written sheets
    conds = list(dict.fromkeys(h.condition for h in habits))
    asks = [h for h in habits if h.mode == "ask"]
    out = {"slug": s["slug"], "wording": wording, "habits": [h.model_dump() for h in habits], "scores": {}, "stated": {}}
    for d in s["dictations"]:
        sc = await H.ask_triggers(s.get("scan_type", ""), d["text"], conds, wording=H.TRIGGER_WORDINGS[wording])
        out["scores"][d["id"]] = dict(zip(conds, sc))
        checks = await J.ask_rows(d["text"], [x for h in asks for x in (h.yes, h.no)], [], contra=False)
        out["stated"][d["id"]] = {h.condition: [checks[2 * k].stated, checks[2 * k + 1].stated]
                                  for k, h in enumerate(asks)}
    return out


async def trigger(root: Path, run_no: int, sets: str, wording: str, only: Optional[List[str]]) -> None:
    out = root / "runs" / "trigger" / sets / f"run{run_no}-{wording}"
    out.mkdir(parents=True, exist_ok=True)
    for s in load(root, sets, only):
        f = out / f"{s['slug']}.json"
        if f.exists():
            continue
        f.write_text(json.dumps(await _trigger_one(s, wording), indent=1))
        print(f"{s['slug']}: {len(s['dictations'])} dictations")


# ── reports (tables only; the controller writes the prose) ───────────────────────────────────────────────────────

def report(root: Path, stage: str, sets: str, run_no: int, wording: str) -> str:
    parts = [f"# Triggered rows lab: {stage} ({sets}, run {run_no})"]
    if stage == "propose":
        rows = []
        for s in load(root, "propose"):
            f = root / "runs" / "propose" / "sets" / f"run{run_no}" / f"{s['slug']}.json"
            lf = root / "labels" / "propose" / f"run{run_no}" / f"{s['slug']}.json"
            if f.exists() and lf.exists():
                rows.append(score_propose(s, json.loads(f.read_text()), json.loads(lf.read_text())))
        parts.append(md_table(list(rows[0]) if rows else ["slug"], [list(r.values()) for r in rows]))
        parts.append(md_table(["metric", "value"], [[k, v] for k, v in summarise_propose(rows).items()]))
    else:
        from rapid_reports_ai.hybrid_stack.habits import TRIGGER_MIN
        from rapid_reports_ai.hybrid_stack.jev_stack import STATED_MIN
        rows, caps = [], []
        for s in load(root, sets):
            f = root / "runs" / "trigger" / sets / f"run{run_no}-{wording}" / f"{s['slug']}.json"
            if not f.exists():
                continue
            payload = json.loads(f.read_text())
            rows += score_trigger(s, payload)
            caps += session_caps(s, payload, TRIGGER_MIN)
        table = trigger_table(rows)
        prf = prf_table(rows, TRIGGER_MIN)
        parts.append(f"## Trigger precision / recall by variant at TRIGGER_MIN {TRIGGER_MIN} (wording {wording})\n"
                     + md_table(["variant", "n", "tp", "fp", "fn", "precision", "recall"],
                                [[c, v["n"], v["tp"], v["fp"], v["fn"], v["p"], v["r"]] for c, v in prf.items()]))
        parts.append(f"## Trigger accuracy by category (wording {wording})\n"
                     + md_table(["category", "n", *THRESHOLDS], [[c, v["n"], *(v[t] for t in THRESHOLDS)]
                                                                for c, v in table.items()]))
        parts.append(f"## Silent band [0.35, {TRIGGER_MIN}) (Hassan H2: never asked)\n"
                     + md_table(["metric", "value"], [[k, v] for k, v in band_table(rows, 0.35, TRIGGER_MIN).items()]))
        parts.append(f"## Already answered (STATED_MIN {STATED_MIN})\n"
                     + md_table(["metric", "value"], [[k, v] for k, v in answered_table(rows, STATED_MIN).items()]))
        n = len(caps)
        parts.append(f"## Rows per session against the caps (TRIGGER_MIN {TRIGGER_MIN})\n" + md_table(
            ["sessions", "with a template row", "template rows capped", "sessions pushing out a generic row"],
            [[n, sum(c["template_rows"] > 0 for c in caps), sum(c["template_capped"] for c in caps),
              sum(c["generic_pushed"] > 0 for c in caps)]]))
    text = "\n\n".join(parts) + "\n"
    (root / f"REPORT_{stage}_{sets}.md").write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["propose", "trigger", "report"])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--sets", default="sets")
    ap.add_argument("--wording", default="B", choices=["A", "B"])
    ap.add_argument("--only", default="")
    ap.add_argument("--stage", dest="report_stage", default="trigger")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.stage == "propose":
        asyncio.run(propose(a.root, a.run, only))
    elif a.stage == "trigger":
        asyncio.run(trigger(a.root, a.run, a.sets, a.wording, only))
    else:
        print(report(a.root, a.report_stage, a.sets if a.report_stage == "trigger" else "sets", a.run, a.wording))


if __name__ == "__main__":
    main()
