"""Admin approve/reject endpoints. Authentication is by HMAC-in-URL only —
no session required, so the admin can action from their email client.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .auth import verify_admin_token
from .database import get_db
from .database.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _html(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        status_code=status,
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>body{font-family:system-ui;padding:3rem;max-width:40rem;margin:auto;}"
            "h1{font-size:1.25rem;margin-bottom:0.5rem;}"
            ".ok{color:#0a7d23;}.err{color:#a4262c;}</style></head>"
            f"<body>{body}</body></html>"
        ),
    )


def _parse_uid(uid: str) -> uuid.UUID:
    try:
        return uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")


@router.get("/approve", response_class=HTMLResponse)
async def approve_user(
    uid: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_id = _parse_uid(uid)
    if not verify_admin_token(user_id, "approve", token):
        return _html("Invalid", "<h1 class='err'>Invalid or expired approval link</h1>", status=403)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return _html("Not found", "<h1 class='err'>User not found</h1>", status=404)

    if user.is_approved:
        return _html(
            "Already approved",
            f"<h1 class='ok'>{user.email} is already approved</h1>",
        )

    user.is_approved = True
    db.commit()
    return _html(
        "Approved",
        f"<h1 class='ok'>{user.email} approved</h1>"
        f"<p>They can now verify their email and log in.</p>",
    )


@router.get("/reject", response_class=HTMLResponse)
async def reject_user(
    uid: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_id = _parse_uid(uid)
    if not verify_admin_token(user_id, "reject", token):
        return _html("Invalid", "<h1 class='err'>Invalid or expired rejection link</h1>", status=403)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return _html(
            "Already removed",
            "<h1 class='ok'>User already removed</h1>",
        )

    email = user.email
    # Bulk delete avoids ORM-side cascade loading; child rows are cleaned up by
    # the DB-level FK ON DELETE CASCADE constraints already on templates, reports,
    # etc. This keeps the delete safe and O(1) even for heavily-associated users.
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()
    return _html(
        "Rejected",
        f"<h1 class='ok'>{email} rejected and removed</h1>",
    )
