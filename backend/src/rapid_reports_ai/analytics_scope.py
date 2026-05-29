"""Shared scope for skill-sheet analytics.

Defines what counts as an in-scope report: **organic users** (internal accounts
excluded) on the **skill-sheet pipelines** (quick_ephemeral + skill_sheet_guided
templates). The batch scorer and the Metabase SQL pack must agree on this scope;
this module is the single source of truth on the Python side.

The skill_sheet_guided check is done in Python (not a JSON SQL operator) so the
query is portable across SQLite (tests) and Postgres (prod).
"""
from __future__ import annotations

import os

from sqlalchemy import func, and_
from sqlalchemy.orm import Session, Query

from .database.models import Report, User, Template


def exclude_emails() -> set[str]:
    """Lowercased internal-account emails to exclude (env, comma-separated)."""
    raw = os.getenv("ANALYTICS_EXCLUDE_EMAILS", "hassan.ahmad.ucl@gmail.com")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def skill_sheet_template_ids(db: Session) -> list:
    """Ids of templates whose config is skill_sheet_guided (parsed in Python)."""
    out = []
    for tid, cfg in db.query(Template.id, Template.template_config).all():
        if isinstance(cfg, dict) and cfg.get("generation_mode") == "skill_sheet_guided":
            out.append(tid)
    return out


def in_scope_reports(db: Session, pipeline: str = "both") -> Query:
    """Base query of in-scope Report rows (organic users, skill-sheet pipelines)."""
    excl = exclude_emails()
    q = db.query(Report).join(User, User.id == Report.user_id)
    if excl:
        q = q.filter(func.lower(User.email).notin_(excl))

    quick = and_(Report.report_type == "auto", Report.generation_mode == "quick_ephemeral")
    tmpl = and_(Report.report_type == "templated",
                Report.template_id.in_(skill_sheet_template_ids(db)))

    if pipeline == "quick":
        return q.filter(quick)
    if pipeline == "template":
        return q.filter(tmpl)
    return q.filter(quick | tmpl)
