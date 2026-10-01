"""Lab: the lean templated path through the production endpoints, locally (LAB ONLY; no prod writes).

    uv run python -m rapid_reports_ai.scripts.template_workflow_check [--case <slug>.<rid>] [--dictation-s 20]

Starts the app in-process (httpx ASGITransport) on a scratch sqlite DB with real models and RR_TEMPLATE_MIRROR=1,
creates a user and skill_sheet_guided templates carrying a production template's STORED sheet as it is (no
grammar structure: SCRATCH/sheet_conversion/data.json), then for one dictation
(SCRATCH/sheet_conversion/smoke_1414/<slug>.<rid>.input.json):
 1. "cached": POST /api/templates/{id}/prepare (as "Set up workspace"), sleep a realistic dictation time, then
    POST /api/templates/{id}/generate (expect phase1_source "cached" and Phase-1 options);
 2. "inline": generate with no prepare, on its own template copy (Phase 1 resolves beside the generator; the
    report must not wait for it: expect options_late or few options, and the Phase 1 row stored afterwards).
Records phase1_source, latencies (generator, route, options, check, vet, total), the report, options, review items.

The guideline prefetch that generate schedules is stubbed out (not part of this flow). Outputs to
SCRATCH/workflow_check_<pid>/: <case>.json + .md, summary.md.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
SCRATCH = Path("/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/"
               "9e672c4e-4eef-41cc-a40f-806516ac58ef/scratchpad")
OUT = SCRATCH / f"workflow_check_{os.getpid()}"
OUT.mkdir(parents=True, exist_ok=True)

# The scratch DB is set BEFORE anything loads backend/.env (which holds the production DATABASE_URL;
# load_dotenv never overrides a variable already set).
os.environ["DATABASE_URL"] = f"sqlite:///{OUT / 'app.db'}"
os.environ["RR_TEMPLATE_MIRROR"] = "1"
os.environ.pop("DATABASE_PUBLIC_URL", None)

from rapid_reports_ai.scripts.case_analyser_lab import _load_env  # noqa: E402

_load_env()
os.environ.pop("DATABASE_PUBLIC_URL", None)
assert os.environ["DATABASE_URL"].startswith("sqlite:///") and str(OUT) in os.environ["DATABASE_URL"]

import httpx  # noqa: E402

from rapid_reports_ai import main as app_main  # noqa: E402
from rapid_reports_ai.auth import create_access_token  # noqa: E402
from rapid_reports_ai.database.connection import SessionLocal, engine  # noqa: E402
from rapid_reports_ai.database.models import (  # noqa: E402
    Base, Report, ReportVersion, Template, TemplateCaseSheet, TemplateVersion, User,
)

assert engine.url.get_backend_name() == "sqlite" and str(OUT) in str(engine.url), engine.url

SC = SCRATCH / "sheet_conversion"
DEFAULT_CASE = "ct_abdomen_and_pelvis_acute_staging.f1890ef9"
MODES = ("cached", "inline")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def setup(slug: str) -> tuple:
    Base.metadata.create_all(bind=engine, tables=[t.__table__ for t in (
        User, Template, TemplateVersion, Report, ReportVersion, TemplateCaseSheet)])
    t = next(t for t in json.loads((SC / "data.json").read_text())["templates"] if t["slug"] == slug)
    db = SessionLocal()
    try:
        import uuid
        user = User(id=uuid.uuid4(), email="workflow-check@local.test", password_hash="x", full_name="Workflow Check",
                    is_active=True, is_verified=True, is_approved=True, signature="Dr W. Check")
        db.add(user)
        db.commit()
        templates = {}
        for mode in MODES:   # the stored sheet as it is: no grammar structure
            cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": t["skill_sheet"], "scan_type": t["scan_type"]}
            row = Template(name=f"{slug} ({mode})", template_config=cfg, user_id=user.id, tags=[], is_active=True)
            db.add(row)
            db.commit()
            templates[mode] = str(row.id)
        return str(user.id), templates, t["scan_type"]
    finally:
        db.close()


def dictation(case: str) -> dict:
    return json.loads((SC / "smoke_1414" / f"{case}.input.json").read_text())


def phase1_row(template_id: str) -> dict:
    db = SessionLocal()
    try:
        import uuid
        rows = db.query(TemplateCaseSheet).filter(TemplateCaseSheet.template_id == uuid.UUID(template_id)).all()
        return [{"status": r.status, "latency_ms": r.latency_ms, "model": r.model, "error": r.error,
                 "master_len": len(r.master_sheet or "")} for r in rows]
    finally:
        db.close()


async def run_case(client: httpx.AsyncClient, headers: dict, did: str, scan_type: str, template_id: str,
                   mode: str, dictation_s: float) -> dict:
    d = dictation(did)
    hist = d.get("clinical_history") or ""
    rec: dict = {"case": did, "mode": mode, "template_id": template_id, "history": hist, "findings": d["findings"]}
    if mode != "inline":
        t = time.perf_counter()
        r = await client.post(f"/api/templates/{template_id}/prepare", headers=headers,
                              json={"clinical_history": hist, "scan_type": scan_type})
        rec["prepare"] = {**r.json(), "s": round(time.perf_counter() - t, 3)}
        log(f"[{did}/{mode}] prepare -> {rec['prepare']}")
        if mode == "cached":
            await asyncio.sleep(dictation_s)
    t = time.perf_counter()
    r = await client.post(f"/api/templates/{template_id}/generate", headers=headers, timeout=600,
                          json={"user_inputs": {"FINDINGS": d["findings"], "CLINICAL_HISTORY": hist}})
    rec["generate_wait_s"] = round(time.perf_counter() - t, 2)
    body = r.json()
    rec["response"] = {k: body.get(k) for k in ("success", "error", "pipeline", "model", "report_id", "scan_type")}
    rec["report"] = body.get("response")
    rec["artifacts"] = body.get("artifacts")
    db = SessionLocal()
    try:
        import uuid
        row = db.get(Report, uuid.UUID(body["report_id"])) if body.get("report_id") else None
        cand = (row.candidate_reports or [{}])[0] if row is not None else {}
    finally:
        db.close()
    rec["candidate"] = cand
    rec["phase1_source"] = cand.get("phase1_source")
    rec["lat"] = cand.get("lat")
    rec["options_late"] = cand.get("options_late")
    rec["phase1_rows_at_return"] = phase1_row(template_id)
    if mode == "inline":   # the inline Phase 1 runs on after the report returns and is stored for next time
        for _ in range(60):
            if any(r["status"] != "running" for r in phase1_row(template_id)):
                break
            await asyncio.sleep(1)
    rec["phase1_rows"] = phase1_row(template_id)
    log(f"[{did}/{mode}] generate {rec['generate_wait_s']} s pipeline={body.get('pipeline')} "
        f"phase1={rec['phase1_source']} lat={rec['lat']}")
    return rec


def render_case(rec: dict) -> str:
    c = rec.get("candidate") or {}
    L = [f"# {rec['case']} ({rec['mode']})", "", f"**History:** {rec['history']}", "", f"**Findings:** {rec['findings']}",
         "", f"- pipeline {rec['response'].get('pipeline')}, phase1_source {rec['phase1_source']}, "
         f"generate wait {rec['generate_wait_s']} s", f"- lat {rec['lat']}", f"- Phase 1 rows {rec['phase1_rows']}",
         f"- prepare {rec.get('prepare')}", "", "## Report", "```", rec.get("report") or f"ERROR {rec['response']}", "```",
         "", "## Options"]
    L += [f"- [{o.get('kind')} -> {o.get('section')}] {o.get('sentence')}" for o in c.get("options") or []] or ["- none"]
    q = c.get("quality_check") or {}
    L += ["", "## Check", f"- flags {[(f.get('kind'), (f.get('text') or '')[:100]) for f in q.get('flags', [])]}",
          f"- review {q.get('review')}", f"- options_late {rec.get('options_late')}",
          f"- artifacts sections {((rec.get('artifacts') or {}).get('sections'))}"]
    return "\n".join(L) + "\n"


def _row(rec: dict) -> str:
    lat = rec.get("lat") or {}
    p1 = next((r.get("latency_ms") for r in rec.get("phase1_rows") or [] if r.get("latency_ms")), None)
    return (f"| {rec['case']} | {rec['mode']} | {rec['phase1_source']} | {round(p1 / 1000, 1) if p1 else '-'} | "
            f"{lat.get('phase1_wait_s')} | {lat.get('generator_s')} | {lat.get('route_s')} | {lat.get('options_s')} | "
            f"{lat.get('check_s')} | {lat.get('vet_s')} | {lat.get('generate_s')} | {rec['generate_wait_s']} | "
            f"{rec.get('options_late')} | {len((rec.get('candidate') or {}).get('options') or [])} |")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=DEFAULT_CASE)
    ap.add_argument("--dictation-s", type=float, default=20.0)
    a = ap.parse_args()
    user_id, templates, scan_type = setup(a.case.split(".")[0])
    app_main._schedule_prefetch_task = lambda **kw: None  # guideline prefetch: not part of this flow
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}
    recs = []
    runner_log = open(OUT / "runner_stdout.log", "w")
    with contextlib.redirect_stdout(runner_log):  # the model runner prints settings to stdout
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_main.app), base_url="http://local") as c:
            for mode in MODES:
                recs.append(await run_case(c, headers, a.case, scan_type, templates[mode], mode, a.dictation_s))
    for r in recs:
        stem = f"{r['case']}.{r['mode']}"
        (OUT / f"{stem}.json").write_text(json.dumps(r, indent=1, default=str))
        (OUT / f"{stem}.md").write_text(render_case(r))
    L = ["# Lean templated path: local production-workflow check", "",
         f"Case {a.case}; dictation sleep {a.dictation_s} s; RR_TEMPLATE_MIRROR=1; scratch DB {engine.url}", "",
         "| case | mode | phase1_source | Phase 1 s | phase1 wait s | generator s | route s | options s | check s | "
         "vet s | generate s | generate wait s | options late | options |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    L += [_row(r) for r in recs]
    (OUT / "summary.md").write_text("\n".join(L) + "\n")
    print(OUT)


if __name__ == "__main__":
    asyncio.run(main())
