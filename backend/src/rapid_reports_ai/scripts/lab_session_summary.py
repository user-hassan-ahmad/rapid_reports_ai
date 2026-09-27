"""Summarise decision-first live-lab sessions (work-order step 5 exit).

Input: session exports from the Dictation Lab panel ("Export session", schema
rr-lab-session/1; data only, no text). Per session and overall:
  - polish calls per utterance vs the polish-everything baseline (1.0), Wilson 95 %;
    overall also with a session-clustered bootstrap interval (utterances within a
    session are not independent)
  - undo / edit (≤10 s) / re-dictation rate per route, Wilson 95 %
  - Jev bundle latency p50 / p95 with bootstrap 95 % intervals

Usage:
  PYTHONPATH=src python -m rapid_reports_ai.scripts.lab_session_summary <file-or-dir>... [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bakeoff_stats import bootstrap_quantile_ci, bootstrap_stat_ci, fmt_rate, quantile, rate

SCHEMA = "rr-lab-session/1"
ROUTES = ("fast_append", "command", "polish", "skip", "delete")
KINDS = ("undo", "edit", "redictate")


def load_sessions(paths: list[str]) -> list[tuple[str, dict[str, Any]]]:
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.json")) if p.is_dir() else [p])
    out = []
    for f in files:
        data = json.loads(f.read_text())
        if data.get("schema") != SCHEMA:
            if f in map(Path, paths):  # named explicitly: a mistake worth stopping for
                raise ValueError(f"{f}: not a {SCHEMA} export")
            continue
        out.append((f.name, data))
    return out


def summarise(decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(decisions)
    route_of = {d["id"]: d["route"] for d in decisions}
    hit: dict[str, set[str]] = {}
    for o in outcomes:
        if o["decision_id"] in route_of:
            hit.setdefault(o["decision_id"], set()).add(o["kind"])
    routes: dict[str, Any] = {}
    for r in ROUTES:
        ids = [d["id"] for d in decisions if d["route"] == r]
        row: dict[str, Any] = {"n": len(ids)}
        for k in KINDS:
            row[k] = rate(sum(1 for i in ids if k in hit.get(i, ())), len(ids))
        row["any"] = rate(sum(1 for i in ids if hit.get(i)), len(ids))
        reasons: dict[str, int] = {}
        for d in decisions:
            if d["route"] == r:
                reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
        row["reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))
        routes[r] = row
    polish = rate(sum(1 for d in decisions if d.get("polish_called")), n)
    lat = [int(d["latency_ms"]) for d in decisions if d.get("latency_ms") is not None]
    polish_ms = [int(d["polish_ms"]) for d in decisions if d.get("polish_ms") is not None]
    return {
        "utterances": n,
        "polish_calls": polish,
        "baseline_polish_per_utterance": 1.0,
        "reduction_vs_baseline": None if polish["p"] is None else 1.0 - polish["p"],
        "routes": routes,
        "bundle_ms": {
            "n": len(lat),
            "p50": quantile(lat, 0.5) if lat else None,
            "p95": quantile(lat, 0.95) if lat else None,
            "p50_ci95": list(bootstrap_quantile_ci(lat, 0.5)) if lat else None,
            "p95_ci95": list(bootstrap_quantile_ci(lat, 0.95)) if lat else None,
        },
        "polish_ms_p50": quantile(polish_ms, 0.5) if polish_ms else None,
        "qsets": sorted({d["qset"] for d in decisions if d.get("qset")}),
        "asr": _asr_by_reason(decisions),
        "polish_by_kind": _polish_by_kind(decisions),
    }


def _polish_by_kind(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Polish time and tokens per kind: 'full' (today's rewrite) or 'lean' (raced span).
    Records from before racing carry no kind: they were full polishes."""
    out: dict[str, Any] = {}
    for d in decisions:
        if not d.get("polish_called"):
            continue
        k = d.get("polish_kind") or "full"
        out.setdefault(k, []).append(d)
    res = {}
    for k, ds in sorted(out.items()):
        ms = [int(d["polish_ms"]) for d in ds if d.get("polish_ms") is not None]
        tin = [d["polish_tokens_in"] for d in ds if d.get("polish_tokens_in") is not None]
        tout = [d["polish_tokens_out"] for d in ds if d.get("polish_tokens_out") is not None]
        res[k] = {"n": len(ds), "ms_p50": quantile(ms, 0.5) if ms else None,
                  "tokens_in": sum(tin) if tin else None, "tokens_out": sum(tout) if tout else None}
    return res


# Descriptive only: where Deepgram's lowest word confidence sits for each routing reason.
# 0.8 is a reporting cut, not a band; step 7 sets any gate from outcomes.
ASR_LOW = 0.8


def _asr_by_reason(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[float]] = {}
    for d in decisions:
        if d.get("asr_min_conf") is not None:
            by.setdefault(d["reason"], []).append(float(d["asr_min_conf"]))
    out = {}
    for reason, xs in sorted(by.items()):
        s = sorted(xs)
        mid = len(s) // 2
        median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
        out[reason] = {"n": len(s), "median_min_conf": round(median, 4),
                       "below_0_8": rate(sum(1 for x in s if x < ASR_LOW), len(s))}
    return out


def dedupe_cumulative(sessions: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    """An export taken without clearing the panel repeats earlier decisions. Backend ids
    (uuid hex) are unique across sessions: each is kept in the first file it appears in,
    and its outcomes from any file follow it there (an undo can land after an export).
    local-<n> ids (request failed) restart per page load, so they stay per file."""
    owner: dict[str, int] = {}
    for k, (_, s) in enumerate(sessions):
        for d in s["decisions"]:
            if not d["id"].startswith("local-"):
                owner.setdefault(d["id"], k)
    decs: list[list[dict[str, Any]]] = [[] for _ in sessions]
    outs: list[list[dict[str, Any]]] = [[] for _ in sessions]
    for k, (_, s) in enumerate(sessions):
        decs[k] = [d for d in s["decisions"] if owner.get(d["id"], k) == k]
        for o in s["outcomes"]:
            outs[owner.get(o["decision_id"], k)].append(o)
    return [(name, {**s, "decisions": decs[k], "outcomes": outs[k]}) for k, (name, s) in enumerate(sessions)]


def report(sessions: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    # export order, not file name: a browser re-download "x (1).json" sorts before "x.json"
    ordered = sorted(sessions, key=lambda ns: (ns[1].get("exported_at") or 0, ns[0]))
    sessions = [ns for ns in dedupe_cumulative(ordered) if ns[1]["decisions"]]
    per = [{"file": name, **summarise(s["decisions"], s["outcomes"])} for name, s in sessions]
    # ids are unique within a session only: namespace them before pooling
    all_dec = [{**d, "id": f"{name}:{d['id']}"} for name, s in sessions for d in s["decisions"]]
    all_out = [{**o, "decision_id": f"{name}:{o['decision_id']}"} for name, s in sessions for o in s["outcomes"]]
    groups = [name for name, s in sessions for _ in s["decisions"]]
    overall = summarise(all_dec, all_out)
    overall["sessions"] = len(sessions)
    overall["polish_per_utterance_session_ci95"] = (
        [round(x, 4) for x in bootstrap_stat_ci(
            [bool(d.get("polish_called")) for d in all_dec],
            lambda xs: sum(xs) / len(xs), groups=groups)]
        if len(sessions) >= 2 else None  # one cluster resamples to itself: [p, p]
    )
    return {"sessions": per, "overall": overall}


def _fmt_summary(title: str, s: dict[str, Any]) -> list[str]:
    lines = [f"== {title}: {s['utterances']} utterances, qset {', '.join(s['qsets']) or '—'}"]
    red = s["reduction_vs_baseline"]
    lines.append(f"  polish calls / utterance  {fmt_rate(s['polish_calls'])}  vs baseline 1.000"
                 + (f"  (−{red:.0%})" if red is not None else ""))
    if "polish_per_utterance_session_ci95" in s:
        if s["polish_per_utterance_session_ci95"]:
            lo, hi = s["polish_per_utterance_session_ci95"]
            lines.append(f"    session-clustered 95 % [{lo:.2f}, {hi:.2f}] over {s['sessions']} sessions")
        else:
            lines.append(f"    session-clustered interval needs ≥ 2 sessions (have {s['sessions']})")
    b = s["bundle_ms"]
    if b["n"]:
        lines.append(f"  bundle p50 {b['p50']} ms [{b['p50_ci95'][0]}, {b['p50_ci95'][1]}]"
                     f"  p95 {b['p95']} ms [{b['p95_ci95'][0]}, {b['p95_ci95'][1]}]  (n={b['n']})")
    if s["polish_ms_p50"] is not None:
        lines.append(f"  polish call p50 {s['polish_ms_p50']} ms")
    for r in ROUTES:
        row = s["routes"][r]
        if not row["n"]:
            continue
        lines.append(f"  {r:<12} n={row['n']:<4} undo {fmt_rate(row['undo'])}  edit {fmt_rate(row['edit'])}"
                     f"  re-dictated {fmt_rate(row['redictate'])}")
        lines.append(f"  {'':<12} reasons {row['reasons']}")
    for kind, p in s.get("polish_by_kind", {}).items():
        lines.append(f"  polish {kind:<5} n={p['n']:<4} p50 {p['ms_p50']} ms  tokens in/out {p['tokens_in']}/{p['tokens_out']}")
    for reason, a in s.get("asr", {}).items():
        lines.append(f"  asr {reason:<34} n={a['n']:<4} median min word conf {a['median_min_conf']:.2f}"
                     f"  below {ASR_LOW}: {fmt_rate(a['below_0_8'])}")
    return lines


def format_report(r: dict[str, Any]) -> str:
    lines: list[str] = []
    for s in r["sessions"]:
        lines += _fmt_summary(s["file"], s)
    lines += _fmt_summary("OVERALL", r["overall"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="session export files or directories of them")
    ap.add_argument("--json", help="also write the full report as JSON here")
    args = ap.parse_args(argv)
    sessions = load_sessions(args.paths)
    if not sessions:
        print("no rr-lab-session/1 exports found", file=sys.stderr)
        return 1
    r = report(sessions)
    print(format_report(r))
    if args.json:
        Path(args.json).write_text(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
