# Skill-Sheet Analytics — Phase 1 (Backend Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the admin-gated `/api/admin/analytics/overview` endpoint that returns descriptive analytics for skill-sheet-driven reports (organic users only), with the top-priority Skill-Sheet Quality data, Signal Coverage, and Volume aggregates.

**Architecture:** A `require_admin` dependency (email allowlist) gates a new `analytics_routes.py` router. Aggregation lives in pure functions in `analytics_queries.py` (take a `Session` + filters → JSON-serializable dicts), unit-tested against a Postgres test DB because the analytics tables use Postgres-only column types (`ARRAY`, `JSONB`). The endpoint composes those functions.

**Tech Stack:** FastAPI, SQLAlchemy (sync), pytest + pytest-asyncio, Postgres (prod + tests), poetry.

**Scope of this plan (Phase 1):** access gate + test infra + scope helpers + three descriptive queries (Skill-Sheet Quality, Signal Coverage, Volume & Adoption) + the `/overview` endpoint returning them. The remaining descriptive queries (head-to-head, audit summary, template refinement) are **Phase 1b**; the dashboard UI is **Phase 2**; trace + objective quality is **Phase 3**; LLM scoring is **Phase 4**.

---

## File structure

- Create `backend/src/rapid_reports_ai/analytics_queries.py` — pure aggregation functions + scope helpers.
- Create `backend/src/rapid_reports_ai/analytics_routes.py` — `/api/admin/analytics` router.
- Modify `backend/src/rapid_reports_ai/auth.py` — add `require_admin` dependency + `_admin_emails()`.
- Modify `backend/src/rapid_reports_ai/main.py` — register the analytics router.
- Modify `backend/tests/conftest.py` — add a Postgres-backed `pg_session` fixture + seed helpers.
- Create `backend/tests/test_analytics_queries.py` — query unit tests.
- Create `backend/tests/test_analytics_routes.py` — endpoint + auth tests.

---

## Task 1: Postgres-backed analytics test fixture

**Files:**
- Modify: `backend/tests/conftest.py`

The existing fixtures use SQLite with only `users` + `password_reset_tokens` because SQLite can't compile `ARRAY`/`TSVECTOR`/`Vector`. Analytics queries touch `reports`, `report_feedback` (ARRAY), etc., so they need Postgres. This fixture creates only the analytics-relevant tables (excludes `tnm_staging`, which needs the `vector` extension) and rolls back per test. It **skips** when `TEST_DATABASE_URL` is unset.

- [ ] **Step 1: Add the fixture and seed helper to conftest.py**

```python
# --- Append to backend/tests/conftest.py ---
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import sessionmaker as _sessionmaker

from rapid_reports_ai.database.models import (  # noqa: E402
    Report, EphemeralSkillSheet, ReportFeedback, ReportVersion,
    ReportAudit, ReportAuditCriterion, Template, TemplateVersion, TemplateRating,
)

_ANALYTICS_TABLES = [
    User.__table__, EphemeralSkillSheet.__table__, Template.__table__,
    TemplateVersion.__table__, TemplateRating.__table__, Report.__table__,
    ReportVersion.__table__, ReportAudit.__table__, ReportAuditCriterion.__table__,
    ReportFeedback.__table__,
]


@pytest.fixture
def pg_session() -> Iterator[Session]:
    """Session against a real Postgres test DB. Skips if TEST_DATABASE_URL unset."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; analytics query tests need Postgres")
    engine = _create_engine(url)
    # Clean slate for the analytics subset.
    Base.metadata.drop_all(bind=engine, tables=_ANALYTICS_TABLES)
    Base.metadata.create_all(bind=engine, tables=_ANALYTICS_TABLES)
    SessionLocal = _sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=_ANALYTICS_TABLES)
        engine.dispose()


def make_user(session, email, full_name="Test User"):
    u = User(id=uuid.uuid4(), email=email, password_hash="x", full_name=full_name,
             is_active=True, is_verified=True, is_approved=True)
    session.add(u); session.flush()
    return u


def make_quick_report(session, user, scan_type="ct chest", clinical_history="cough",
                      created_at=None, final_content=None, latency_ms=1200):
    ess = EphemeralSkillSheet(
        id=uuid.uuid4(), scan_type=scan_type,
        scan_type_normalized=scan_type.lower().strip(),
        clinical_history=clinical_history, skill_sheet_markdown="- check lungs",
        analyser_model="zai-glm-4.7", analyser_latency_ms=latency_ms, user_id=user.id,
    )
    session.add(ess); session.flush()
    r = Report(
        id=uuid.uuid4(), report_type="auto", generation_mode="quick_ephemeral",
        model_used="zai-glm-4.7", report_content="LUNGS: clear.",
        ephemeral_skill_sheet_id=ess.id, user_id=user.id,
        final_report_content=final_content,
        final_edit_diff="--- a\n+++ b\n" if final_content else None,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(r); session.flush()
    return r


def make_template_report(session, user, created_at=None):
    t = Template(id=uuid.uuid4(), name="CT Chest", user_id=user.id,
                 template_config={"generation_mode": "skill_sheet_guided"})
    session.add(t); session.flush()
    r = Report(id=uuid.uuid4(), report_type="templated", model_used="zai-glm-4.7",
               report_content="report body", template_id=t.id, user_id=user.id,
               created_at=created_at or datetime.now(timezone.utc))
    session.add(r); session.flush()
    return r
```

- [ ] **Step 2: Verify collection imports cleanly**

Run: `cd backend && poetry run pytest tests/conftest.py --collect-only -q`
Expected: no import errors (collects 0 tests from conftest).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: add Postgres-backed analytics fixture and seed helpers"
```

---

## Task 2: `require_admin` dependency + `ADMIN_EMAILS`

**Files:**
- Modify: `backend/src/rapid_reports_ai/auth.py`
- Test: `backend/tests/test_analytics_routes.py` (auth portion; created here)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_analytics_routes.py
import os
from rapid_reports_ai.auth import _admin_emails


def test_admin_emails_parses_csv(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "a@x.com, B@Y.com ")
    assert _admin_emails() == {"a@x.com", "b@y.com"}


def test_admin_emails_empty(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    assert _admin_emails() == set()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && poetry run pytest tests/test_analytics_routes.py -v`
Expected: FAIL — `ImportError: cannot import name '_admin_emails'`.

- [ ] **Step 3: Add `_admin_emails` and `require_admin` to auth.py**

```python
# backend/src/rapid_reports_ai/auth.py  (add near other dependencies)
def _admin_emails() -> set[str]:
    """Lowercased set of admin emails from the ADMIN_EMAILS env var (comma-separated)."""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Allow only users whose email is in ADMIN_EMAILS. 403 otherwise."""
    if current_user.email.lower() not in _admin_emails():
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

(`os`, `Depends`, `HTTPException`, `User`, and `get_current_user` are already imported in auth.py.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_analytics_routes.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/auth.py backend/tests/test_analytics_routes.py
git commit -m "feat(auth): add require_admin dependency gated by ADMIN_EMAILS"
```

---

## Task 3: Scope helpers in `analytics_queries.py`

**Files:**
- Create: `backend/src/rapid_reports_ai/analytics_queries.py`
- Test: `backend/tests/test_analytics_queries.py`

Defines the in-scope filters: organic users only (exclude allowlist), the two skill-sheet pipelines, and an optional date window.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_analytics_queries.py
import os
from rapid_reports_ai import analytics_queries as aq
from tests.conftest import make_user, make_quick_report, make_template_report


def test_in_scope_excludes_internal_and_legacy(pg_session, monkeypatch):
    monkeypatch.setenv("ANALYTICS_EXCLUDE_EMAILS", "hassan@x.com")
    organic = make_user(pg_session, "organic@nhs.net")
    internal = make_user(pg_session, "hassan@x.com")
    make_quick_report(pg_session, organic)            # in scope
    make_template_report(pg_session, organic)         # in scope
    make_quick_report(pg_session, internal)           # excluded (internal)
    # legacy auto (no ephemeral) — excluded by pipeline filter
    from rapid_reports_ai.database.models import Report
    import uuid
    pg_session.add(Report(id=uuid.uuid4(), report_type="auto", generation_mode=None,
                          model_used="x", report_content="y", user_id=organic.id))
    pg_session.flush()

    rows = aq.in_scope_reports(pg_session).all()
    assert len(rows) == 2
    assert {r.report_type for r in rows} == {"auto", "templated"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: rapid_reports_ai.analytics_queries`.

- [ ] **Step 3: Implement the scope helpers**

```python
# backend/src/rapid_reports_ai/analytics_queries.py
"""Read-only aggregate queries for the admin analytics dashboard.

Pure functions: each takes a SQLAlchemy Session (+ filters) and returns
JSON-serializable dicts. No FastAPI imports here.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from sqlalchemy import func, and_, select
from sqlalchemy.orm import Session, Query

from .database.models import (
    Report, User, EphemeralSkillSheet, Template, TemplateVersion, TemplateRating,
)


def _exclude_emails() -> set[str]:
    raw = os.getenv("ANALYTICS_EXCLUDE_EMAILS", "hassan.ahmad.ucl@gmail.com")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _skill_sheet_template_ids(db: Session):
    """Subquery of template ids whose config generation_mode is skill_sheet_guided."""
    return (
        select(Template.id)
        .where(Template.template_config["generation_mode"].astext == "skill_sheet_guided")
        .scalar_subquery()
    )


def in_scope_reports(
    db: Session,
    pipeline: str = "both",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Query:
    """Base query of in-scope Report rows (organic users, skill-sheet pipelines)."""
    excl = _exclude_emails()
    q = db.query(Report).join(User, User.id == Report.user_id)
    q = q.filter(func.lower(User.email).notin_(excl))

    quick = and_(Report.report_type == "auto", Report.generation_mode == "quick_ephemeral")
    tmpl = and_(Report.report_type == "templated",
                Report.template_id.in_(_skill_sheet_template_ids(db)))
    if pipeline == "quick":
        q = q.filter(quick)
    elif pipeline == "template":
        q = q.filter(tmpl)
    else:
        q = q.filter(quick | tmpl)

    if date_from is not None:
        q = q.filter(Report.created_at >= date_from)
    if date_to is not None:
        q = q.filter(Report.created_at <= date_to)
    return q


def report_pipeline_label(r: Report) -> str:
    return "quick" if r.report_type == "auto" else "template"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/analytics_queries.py backend/tests/test_analytics_queries.py
git commit -m "feat(analytics): in-scope report query (organic, skill-sheet pipelines)"
```

---

## Task 4: `skill_sheet_quality()` query (top priority)

**Files:**
- Modify: `backend/src/rapid_reports_ai/analytics_queries.py`
- Test: `backend/tests/test_analytics_queries.py`

- [ ] **Step 1: Write the failing test**

```python
def test_skill_sheet_quality(pg_session, monkeypatch):
    monkeypatch.setenv("ANALYTICS_EXCLUDE_EMAILS", "hassan@x.com")
    u = make_user(pg_session, "organic@nhs.net")
    make_quick_report(pg_session, u, scan_type="CT Chest", latency_ms=1000)
    make_quick_report(pg_session, u, scan_type="ct chest", latency_ms=2000)
    make_quick_report(pg_session, u, scan_type="MRI Head", latency_ms=1500)

    out = aq.skill_sheet_quality(pg_session)
    assert out["ephemeral"]["count"] == 3
    # "ct chest" normalises to one cluster of 2
    clusters = {c["scan_type"]: c["count"] for c in out["ephemeral"]["scan_type_clusters"]}
    assert clusters["ct chest"] == 2
    assert out["ephemeral"]["analyser_models"] == [{"model": "zai-glm-4.7", "count": 3}]
    assert out["ephemeral"]["latency_ms"]["median"] == 1500
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_skill_sheet_quality -v`
Expected: FAIL — `AttributeError: module has no attribute 'skill_sheet_quality'`.

- [ ] **Step 3: Implement `skill_sheet_quality`**

```python
# append to analytics_queries.py

def skill_sheet_quality(
    db: Session, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None
) -> dict:
    """Ephemeral skill-sheet usage (quick side) + template refinement (template side)."""
    excl = _exclude_emails()

    ess_q = (
        db.query(EphemeralSkillSheet)
        .join(User, User.id == EphemeralSkillSheet.user_id)
        .filter(func.lower(User.email).notin_(excl))
    )
    if date_from is not None:
        ess_q = ess_q.filter(EphemeralSkillSheet.created_at >= date_from)
    if date_to is not None:
        ess_q = ess_q.filter(EphemeralSkillSheet.created_at <= date_to)
    ess_sub = ess_q.subquery()

    count = db.query(func.count()).select_from(ess_sub).scalar() or 0

    models = [
        {"model": m, "count": c}
        for m, c in db.query(ess_sub.c.analyser_model, func.count())
        .group_by(ess_sub.c.analyser_model).order_by(func.count().desc()).all()
    ]
    clusters = [
        {"scan_type": s, "count": c}
        for s, c in db.query(ess_sub.c.scan_type_normalized, func.count())
        .group_by(ess_sub.c.scan_type_normalized).order_by(func.count().desc()).limit(20).all()
    ]
    median = db.query(
        func.percentile_cont(0.5).within_group(ess_sub.c.analyser_latency_ms.asc())
    ).scalar()
    avg = db.query(func.avg(ess_sub.c.analyser_latency_ms)).scalar()

    # Template side: skill_sheet_guided templates used by in-scope template reports.
    tmpl_ids = [r.template_id for r in in_scope_reports(db, "template", date_from, date_to).all()]
    refinements = []
    if tmpl_ids:
        for tid, name, ver_count in (
            db.query(Template.id, Template.name, func.count(TemplateVersion.id))
            .outerjoin(TemplateVersion, TemplateVersion.template_id == Template.id)
            .filter(Template.id.in_(set(tmpl_ids)))
            .group_by(Template.id, Template.name).all()
        ):
            refinements.append({"template_id": str(tid), "name": name, "versions": int(ver_count)})

    return {
        "ephemeral": {
            "count": int(count),
            "analyser_models": models,
            "scan_type_clusters": clusters,
            "latency_ms": {
                "median": int(median) if median is not None else None,
                "avg": float(avg) if avg is not None else None,
            },
        },
        "template": {"refinements": refinements},
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_skill_sheet_quality -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/analytics_queries.py backend/tests/test_analytics_queries.py
git commit -m "feat(analytics): skill_sheet_quality aggregate"
```

---

## Task 5: `signal_coverage()` query

**Files:**
- Modify: `backend/src/rapid_reports_ai/analytics_queries.py`
- Test: `backend/tests/test_analytics_queries.py`

- [ ] **Step 1: Write the failing test**

```python
def test_signal_coverage(pg_session, monkeypatch):
    monkeypatch.setenv("ANALYTICS_EXCLUDE_EMAILS", "hassan@x.com")
    u = make_user(pg_session, "organic@nhs.net")
    make_quick_report(pg_session, u, final_content=None)             # no edit captured
    make_quick_report(pg_session, u, final_content="edited body")    # edit captured
    out = aq.signal_coverage(pg_session)
    assert out["total"] == 2
    assert out["skill_sheet_present"] == {"n": 2, "pct": 100.0}
    assert out["final_edit_captured"] == {"n": 1, "pct": 50.0}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_signal_coverage -v`
Expected: FAIL — no attribute `signal_coverage`.

- [ ] **Step 3: Implement `signal_coverage`**

```python
# append to analytics_queries.py

def _pct(n: int, total: int) -> dict:
    return {"n": int(n), "pct": round(100.0 * n / total, 1) if total else 0.0}


def signal_coverage(
    db: Session, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None
) -> dict:
    """For in-scope reports, how many carry each captured signal."""
    base = in_scope_reports(db, "both", date_from, date_to)
    rows = base.all()
    total = len(rows)
    skill_sheet = sum(
        1 for r in rows
        if r.ephemeral_skill_sheet_id is not None or r.template_id is not None
    )
    final_edit = sum(1 for r in rows if r.final_report_content)
    return {
        "total": total,
        "skill_sheet_present": _pct(skill_sheet, total),
        "final_edit_captured": _pct(final_edit, total),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_signal_coverage -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/analytics_queries.py backend/tests/test_analytics_queries.py
git commit -m "feat(analytics): signal_coverage aggregate"
```

---

## Task 6: `volume_and_adoption()` query

**Files:**
- Modify: `backend/src/rapid_reports_ai/analytics_queries.py`
- Test: `backend/tests/test_analytics_queries.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

def test_volume_and_adoption(pg_session, monkeypatch):
    monkeypatch.setenv("ANALYTICS_EXCLUDE_EMAILS", "hassan@x.com")
    u = make_user(pg_session, "organic@nhs.net", full_name="Dr Organic")
    make_quick_report(pg_session, u, created_at=datetime(2026, 4, 20, tzinfo=timezone.utc))
    make_template_report(pg_session, u, created_at=datetime(2026, 4, 21, tzinfo=timezone.utc))
    out = aq.volume_and_adoption(pg_session)
    assert out["totals"] == {"quick": 1, "template": 1}
    by_user = {r["email"]: r["count"] for r in out["by_user"]}
    assert by_user["organic@nhs.net"] == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_volume_and_adoption -v`
Expected: FAIL — no attribute `volume_and_adoption`.

- [ ] **Step 3: Implement `volume_and_adoption`**

```python
# append to analytics_queries.py

def volume_and_adoption(
    db: Session, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None
) -> dict:
    rows = in_scope_reports(db, "both", date_from, date_to).all()
    totals = {"quick": 0, "template": 0}
    by_week: dict[str, dict] = {}
    by_user_counts: dict = {}
    for r in rows:
        label = report_pipeline_label(r)
        totals[label] += 1
        wk = r.created_at.strftime("%G-W%V")
        bucket = by_week.setdefault(wk, {"week": wk, "quick": 0, "template": 0})
        bucket[label] += 1
        by_user_counts[r.user_id] = by_user_counts.get(r.user_id, 0) + 1

    user_emails = {
        u.id: u.email for u in db.query(User).filter(User.id.in_(by_user_counts.keys())).all()
    } if by_user_counts else {}
    by_user = sorted(
        ({"email": user_emails.get(uid, "?"), "count": c} for uid, c in by_user_counts.items()),
        key=lambda x: x["count"], reverse=True,
    )
    return {
        "totals": totals,
        "by_week": [by_week[k] for k in sorted(by_week)],
        "by_user": by_user,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && TEST_DATABASE_URL=postgresql://postgres@localhost:5432/radflow_test poetry run pytest tests/test_analytics_queries.py::test_volume_and_adoption -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/analytics_queries.py backend/tests/test_analytics_queries.py
git commit -m "feat(analytics): volume_and_adoption aggregate"
```

---

## Task 7: `/overview` endpoint + router registration

**Files:**
- Create: `backend/src/rapid_reports_ai/analytics_routes.py`
- Modify: `backend/src/rapid_reports_ai/main.py` (register router near other `include_router` calls ~line 5595)
- Test: `backend/tests/test_analytics_routes.py`

- [ ] **Step 1: Write the failing test (auth gate)**

```python
# add to backend/tests/test_analytics_routes.py
from rapid_reports_ai.auth import create_access_token  # token helper used by the app


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_overview_forbidden_for_non_admin(client, db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@radflow.uk")
    u = make_user(db_session, "regular@nhs.net")
    token = create_access_token({"sub": str(u.id)})
    resp = client.get("/api/admin/analytics/overview", headers=_auth(token))
    assert resp.status_code == 403


def test_overview_ok_for_admin(client, db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@radflow.uk")
    u = make_user(db_session, "boss@radflow.uk")
    token = create_access_token({"sub": str(u.id)})
    resp = client.get("/api/admin/analytics/overview", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"volume", "signal_coverage", "skill_sheet_quality"}
```

> Note: this auth test uses the SQLite `client` fixture (only `users` exist), so the
> endpoint must tolerate empty/zero data without touching Postgres-only tables in a way
> that errors on SQLite. The aggregate functions only `SELECT` and return zeros on empty
> tables; `reports` is created in SQLite via `JSONBType` (JSON fallback) — confirm `reports`
> is added to `_TEST_TABLES` in conftest for this test (Step 4 below). If `report_feedback`
> (ARRAY) blocks SQLite creation, keep Phase 1 endpoints off that table (they are).

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && poetry run pytest tests/test_analytics_routes.py -k overview -v`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Create the router**

```python
# backend/src/rapid_reports_ai/analytics_routes.py
"""Admin analytics dashboard API (read-only)."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .auth import require_admin
from .database.connection import get_db
from . import analytics_queries as aq

router = APIRouter(prefix="/api/admin/analytics", tags=["admin-analytics"])


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


@router.get("/overview")
async def overview(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    _admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    df, dt = _parse_dt(date_from), _parse_dt(date_to)
    return {
        "volume": aq.volume_and_adoption(db, df, dt),
        "signal_coverage": aq.signal_coverage(db, df, dt),
        "skill_sheet_quality": aq.skill_sheet_quality(db, df, dt),
    }
```

- [ ] **Step 4: Register the router and widen SQLite test tables**

In `backend/src/rapid_reports_ai/main.py`, after the `admin_router` registration (~line 5595):

```python
from .analytics_routes import router as analytics_router
app.include_router(analytics_router)
```

In `backend/tests/conftest.py`, add `Report` (JSONBType → JSON works on SQLite) to `_TEST_TABLES` so the auth tests can hit empty aggregates:

```python
from rapid_reports_ai.database.models import Report  # if not already imported
_TEST_TABLES = [User.__table__, PasswordResetToken.__table__, Report.__table__]
```

(`skill_sheet_quality`/`volume`/`signal_coverage` only read `reports`, `users`, `ephemeral_skill_sheets`, `templates`; `percentile_cont` is not exercised on empty data. If any function errors on SQLite with empty data, wrap its body in a `try/except` returning the zero-shape — but verify first.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_analytics_routes.py -v`
Expected: all pass (403 for non-admin, 200 + keys for admin).

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/analytics_routes.py backend/src/rapid_reports_ai/main.py backend/tests/conftest.py backend/tests/test_analytics_routes.py
git commit -m "feat(analytics): /api/admin/analytics/overview endpoint behind require_admin"
```

---

## Self-review notes (already applied)

- **Spec coverage (Phase 1 slice):** access gate (Task 2), Skill-Sheet Quality top-priority (Task 4), Signal Coverage (Task 5), Volume (Task 6), endpoint (Task 7). Head-to-head / audit / refinement = Phase 1b (next plan). UI = Phase 2.
- **Test-DB reality:** analytics-query tests run on Postgres (`TEST_DATABASE_URL`); auth/endpoint tests run on the SQLite `client` with `reports` added. This is the one cross-cutting constraint and is handled in Tasks 1 & 7.
- **Type consistency:** `in_scope_reports`, `skill_sheet_quality`, `signal_coverage`, `volume_and_adoption`, `_exclude_emails`, `_admin_emails`, `require_admin` are used with identical names across tasks.
- **Env vars:** `ADMIN_EMAILS` (gate), `ANALYTICS_EXCLUDE_EMAILS` (organic exclusion, default `hassan.ahmad.ucl@gmail.com`), `TEST_DATABASE_URL` (tests only).
