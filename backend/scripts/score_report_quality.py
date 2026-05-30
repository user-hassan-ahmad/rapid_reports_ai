#!/usr/bin/env python3
"""Batch-score skill-sheet reports into report_quality_scores.

Re-runnable and idempotent (one row per report + rubric_version). Each report
costs a few LLM calls via the QUALITY_JUDGE model, so this is an offline batch,
not a request-path operation. Metabase reads the resulting table.

Usage:
  # Dry run (list what would be scored, no model calls, no writes):
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/score_report_quality.py --dry-run

  # Score up to 20 reports:
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/score_report_quality.py --limit 20

  # Re-score (overwrite existing rows for the current rubric version):
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/score_report_quality.py --rescore

  $DATABASE_PUBLIC_URL is in backend/.env:
      export $(grep -E '^DATABASE_PUBLIC_URL=' .env | xargs)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main() -> None:
    p = argparse.ArgumentParser(description="Batch quality-score skill-sheet reports.")
    p.add_argument("--pipeline", choices=["quick", "template", "both"], default="both")
    p.add_argument("--limit", type=int, default=None, help="Max reports to process.")
    p.add_argument("--rescore", action="store_true", help="Re-score reports that already have a row.")
    p.add_argument("--dry-run", action="store_true", help="List targets; no model calls, no writes.")
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print('ERROR: DATABASE_URL not set. Prefix with DATABASE_URL="$DATABASE_PUBLIC_URL".')
        sys.exit(1)

    # Fill judge/API keys from .env if the shell doesn't already have them, WITHOUT
    # clobbering the explicitly-passed DATABASE_URL (which selects the target DB).
    try:
        from dotenv import dotenv_values
        _env = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
        for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "FIREWORKS_API_KEY"):
            if _env.get(k) and not os.environ.get(k):
                os.environ[k] = _env[k]
    except Exception:
        pass  # .env optional; keys may already be in the environment

    # Import after DATABASE_URL is set (connection.py builds the engine at import).
    from rapid_reports_ai.database.connection import SessionLocal
    from rapid_reports_ai.analytics_scope import in_scope_reports
    from rapid_reports_ai import quality_scoring as qs

    db = SessionLocal()
    try:
        reports = in_scope_reports(db, args.pipeline).all()
        if args.limit is not None:
            reports = reports[: args.limit]

        print(f"In-scope reports: {len(reports)} (pipeline={args.pipeline}, rubric={qs.RUBRIC_VERSION_V2})")
        ok = err = 0
        for r in reports:
            label = "quick" if r.report_type == "auto" else "template"
            if args.dry_run:
                print(f"  [dry-run] would score {r.id} ({label})")
                continue
            try:
                qs.score_report(db, r, rescore=args.rescore)
                ok += 1
                print(f"  scored {r.id} ({label})")
            except Exception as e:  # keep going; one bad report shouldn't abort the batch
                err += 1
                print(f"  ! {r.id} ({label}): {type(e).__name__}: {e}")
        if not args.dry_run:
            print(f"done: scored={ok} errors={err} total={len(reports)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
