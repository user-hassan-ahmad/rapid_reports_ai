#!/usr/bin/env python3
"""
Create a user account directly (admin onboarding), bypassing the signup form.

The new user is created already-usable: is_active, is_verified, and is_approved
are all True, so they can log in immediately with the password set here and
change it later from their account.

SAFETY: dry-run by default. Nothing is written unless you pass --commit.
The target database is whatever DATABASE_URL points to — the script prints the
host it connects to so you can confirm before committing.

Usage:
  # Dry run against production (read-only — shows what WOULD be created):
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/create_user.py \
      --email jane@hospital.nhs.uk --name "Dr Jane Doe" \
      --role consultant_radiologist --institution "St Thomas' Hospital"

  # Actually create (auto-generates a strong password and prints it):
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/create_user.py \
      --email jane@hospital.nhs.uk --name "Dr Jane Doe" \
      --role consultant_radiologist --institution "St Thomas' Hospital" --commit

  # Create with a specific generic password:
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/create_user.py \
      --email jane@hospital.nhs.uk --name "Dr Jane Doe" \
      --role registrar --institution "Guy's Hospital" \
      --password "Welcome2RadFlow!" --commit

  $DATABASE_PUBLIC_URL is read from backend/.env. Load it first, e.g.:
      export $(grep -E '^DATABASE_PUBLIC_URL=' .env | xargs)
"""
import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Roles accepted by the signup schema (RegisterRequest in main.py).
ALLOWED_ROLES = [
    "consultant_radiologist",
    "registrar",
    "reporting_radiographer",
    "medical_student",
    "other_healthcare_professional",
    "other",
]


def _db_host(url: str) -> str:
    """Best-effort 'host:port/db' label for display, without credentials."""
    try:
        after_at = url.split("@", 1)[1]
        return after_at
    except (IndexError, AttributeError):
        return "<unparseable>"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a user account directly (admin onboarding).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", required=True, help="User's email (login).")
    parser.add_argument("--name", required=True, help="Full name, e.g. 'Dr Jane Doe'.")
    parser.add_argument("--role", required=True, choices=ALLOWED_ROLES, help="User role.")
    parser.add_argument("--institution", required=True, help="Institution name.")
    parser.add_argument(
        "--password",
        default=None,
        help="Generic password. If omitted, a strong one is generated and printed.",
    )
    parser.add_argument(
        "--signup-reason",
        default="Onboarded directly by admin (create_user.py)",
        help="Stored on the user for audit/triage context.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write to the database. Without this flag the script is a dry run.",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set. Prefix the command with "
              'DATABASE_URL="$DATABASE_PUBLIC_URL" to target production.')
        sys.exit(1)

    # Generate a strong generic password if none supplied.
    generated = args.password is None
    password = args.password or secrets.token_urlsafe(12)

    # Import app modules AFTER DATABASE_URL is fixed (connection.py builds the
    # engine eagerly at import time from DATABASE_URL).
    from rapid_reports_ai.auth import get_password_hash
    from rapid_reports_ai.database.connection import SessionLocal
    from rapid_reports_ai.database.crud import get_user_by_email
    from rapid_reports_ai.database.models import User

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"\n=== create_user [{mode}] ===")
    print(f"Target DB : {_db_host(database_url)}")
    print(f"Email     : {args.email}")
    print(f"Name      : {args.name}")
    print(f"Role      : {args.role}")
    print(f"Institution: {args.institution}")
    print(f"Flags     : is_active=True, is_verified=True, is_approved=True")
    print()

    db = SessionLocal()
    try:
        existing = get_user_by_email(db, args.email)
        if existing:
            print(f"ABORT: a user with email '{args.email}' already exists "
                  f"(id={existing.id}). No changes made.")
            sys.exit(1)

        user = User(
            email=args.email,
            password_hash=get_password_hash(password),
            full_name=args.name,
            role=args.role,
            institution=args.institution,
            signup_reason=args.signup_reason,
            is_active=True,
            is_verified=True,
            is_approved=True,
        )

        if not args.commit:
            print("DRY RUN — nothing written. Re-run with --commit to create the user.")
            print(f"Password that WOULD be set: {password}"
                  + ("  (auto-generated)" if generated else "  (you supplied)"))
            db.rollback()
            return

        db.add(user)
        db.commit()
        db.refresh(user)

        print("USER CREATED")
        print(f"  id       : {user.id}")
        print(f"  email    : {user.email}")
        print(f"  password : {password}"
              + ("  (auto-generated — share securely)" if generated else ""))
        print("\nThey can log in now and change this password from their account.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
