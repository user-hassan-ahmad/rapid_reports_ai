"""Lab: the templated mirror through the production endpoints, locally (LAB ONLY; no prod writes).

    uv run python -m rapid_reports_ai.scripts.template_workflow_check [--sheets <lab run dir>] [--dictation-s 20]

Starts the app in-process (httpx ASGITransport) on a scratch sqlite DB with real models and RR_TEMPLATE_MIRROR=1,
creates a user and one skill_sheet_guided template per set carrying the lab's lean grammar sheet (default
SCRATCH/e2e_small_s_64800/<set>/lean_sheet.md) and its grammar structure, then for ct_ap_acute-d1, -d3 and
cmr_cardiomyopathy-d2:
 1. POST /api/templates/{id}/prepare (as "Set up workspace");
 2. sleeps for a realistic dictation time;
 3. POST /api/templates/{id}/generate with the dictation;
 4. records phase1_source (expect "cached"), the latencies, the report, the options and the artifacts.
One more case fires generate straight after prepare (expect "awaited"), one has no prepare (expect "inline");
each on its own copy of the template so its case key is new.

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
FIXTURES = HERE.parents[3] / "tests" / "fixtures" / "sheet_lab"
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
from rapid_reports_ai import template_sheet_grammar as tsg  # noqa: E402
from rapid_reports_ai.auth import create_access_token  # noqa: E402
from rapid_reports_ai.database.connection import SessionLocal, engine  # noqa: E402
from rapid_reports_ai.database.models import (  # noqa: E402
    Base, Report, ReportVersion, Template, TemplateCaseSheet, TemplateVersion, User,
)

assert engine.url.get_backend_name() == "sqlite" and str(OUT) in str(engine.url), engine.url

CASES = [("ct_ap_acute", "ct_ap_acute-d1"), ("ct_ap_acute", "ct_ap_acute-d3"),
         ("cmr_cardiomyopathy", "cmr_cardiomyopathy-d2")]
AWAITED = ("ct_ap_acute", "ct_ap_acute-d3")      # generate fired straight after prepare
INLINE = ("cmr_cardiomyopathy", "cmr_cardiomyopathy-d2")  # no prepare at all


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def setup(sheets_dir: Path) -> tuple:
    Base.metadata.create_all(bind=engine, tables=[t.__table__ for t in (
        User, Template, TemplateVersion, Report, ReportVersion, TemplateCaseSheet)])
    db = SessionLocal()
    try:
        import uuid
        user = User(id=uuid.uuid4(), email="workflow-check@local.test", password_hash="x", full_name="Workflow Check",
                    is_active=True, is_verified=True, is_approved=True, signature="Dr W. Check")
        db.add(user)
        db.commit()
        templates = {}
        for set_name in sorted({s for s, _ in CASES}):
            sheet = (sheets_dir / set_name / "lean_sheet.md").read_text()
            parsed = tsg.parse_sheet(sheet)
            assert parsed.structure.usable, (set_name, parsed.errors)
            scan = json.loads((FIXTURES / set_name / "answer_key.json").read_text())["scan_type"]
            for copy in ("main", "awaited", "inline"):
                cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": sheet, "scan_type": scan,
                       "sheet_structure": parsed.structure.model_dump(mode="json")}
                t = Template(name=f"{set_name} ({copy})", template_config=cfg, user_id=user.id, tags=[], is_active=True)
                db.add(t)
                db.commit()
                templates[(set_name, copy)] = str(t.id)
        return str(user.id), templates
    finally:
        db.close()


def dictation(set_name: str, did: str) -> dict:
    return next(d for d in json.loads((FIXTURES / set_name / "dictations.json").read_text()) if d["id"] == did)


def phase1_row(template_id: str) -> dict:
    db = SessionLocal()
    try:
        import uuid
        rows = db.query(TemplateCaseSheet).filter(TemplateCaseSheet.template_id == uuid.UUID(template_id)).all()
        return [{"status": r.status, "latency_ms": r.latency_ms, "model": r.model, "error": r.error,
                 "master_len": len(r.master_sheet or "")} for r in rows]
    finally:
        db.close()


async def run_case(client: httpx.AsyncClient, headers: dict, set_name: str, did: str, template_id: str,
                   mode: str, dictation_s: float) -> dict:
    d = dictation(set_name, did)
    rec: dict = {"case": did, "mode": mode, "template_id": template_id, "history": d.get("clinical_history", ""),
                 "findings": d["findings"]}
    if mode != "inline":
        t = time.perf_counter()
        r = await client.post(f"/api/templates/{template_id}/prepare", headers=headers,
                              json={"clinical_history": d.get("clinical_history", ""), "scan_type": d["scan_type"]})
        rec["prepare"] = {**r.json(), "s": round(time.perf_counter() - t, 3)}
        log(f"[{did}/{mode}] prepare -> {rec['prepare']}")
        if mode == "cached":
            await asyncio.sleep(dictation_s)
    t = time.perf_counter()
    r = await client.post(f"/api/templates/{template_id}/generate", headers=headers, timeout=600,
                          json={"user_inputs": {"FINDINGS": d["findings"],
                                                "CLINICAL_HISTORY": d.get("clinical_history", "")}})
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
          f"- artifacts sections {((rec.get('artifacts') or {}).get('sections'))}"]
    return "\n".join(L) + "\n"


def _row(rec: dict) -> str:
    lat = rec.get("lat") or {}
    p1 = next((r.get("latency_ms") for r in rec.get("phase1_rows") or [] if r.get("latency_ms")), None)
    return (f"| {rec['case']} | {rec['mode']} | {rec['phase1_source']} | {round(p1 / 1000, 1) if p1 else '-'} | "
            f"{lat.get('phase1_wait_s')} | {lat.get('brief_s')} | {lat.get('generator_s')} | {lat.get('check_s')} | "
            f"{lat.get('gate_s')} | {rec['generate_wait_s']} | {len((rec.get('candidate') or {}).get('options') or [])} |")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", default=str(SCRATCH / "e2e_small_s_64800"))
    ap.add_argument("--dictation-s", type=float, default=20.0)
    a = ap.parse_args()
    user_id, templates = setup(Path(a.sheets))
    app_main._schedule_prefetch_task = lambda **kw: None  # guideline prefetch: not part of this flow
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}
    recs = []
    runner_log = open(OUT / "runner_stdout.log", "w")
    with contextlib.redirect_stdout(runner_log):  # the model runner prints settings to stdout
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_main.app), base_url="http://local") as c:
            for set_name, did in CASES:
                recs.append(await run_case(c, headers, set_name, did, templates[(set_name, "main")], "cached",
                                           a.dictation_s))
            recs.append(await run_case(c, headers, *AWAITED, templates[(AWAITED[0], "awaited")], "awaited", 0))
            recs.append(await run_case(c, headers, *INLINE, templates[(INLINE[0], "inline")], "inline", 0))
    for r in recs:
        stem = f"{r['case']}.{r['mode']}"
        (OUT / f"{stem}.json").write_text(json.dumps(r, indent=1, default=str))
        (OUT / f"{stem}.md").write_text(render_case(r))
    L = ["# Templated mirror: local production-workflow check", "",
         f"Sheets {a.sheets}; dictation sleep {a.dictation_s} s; RR_TEMPLATE_MIRROR=1; scratch DB {engine.url}", "",
         "| case | mode | phase1_source | Phase 1 s | phase1 wait s | brief s | generator s | check s | gate s | "
         "generate wait s | options |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    L += [_row(r) for r in recs]
    (OUT / "summary.md").write_text("\n".join(L) + "\n")
    print(OUT)


if __name__ == "__main__":
    asyncio.run(main())
