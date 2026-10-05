"""The rail chat thread (spec §10.2, §12.6): `report_chat_messages` rows, so History reopens a report with its chat.

A successful chat turn saves the user message and the assistant reply (prose + edits with verified/failed). Apply /
Undo of one edit updates the reply's `applied_item_ids` (the rail's `lane: chat` item ids) and keeps the apply event
detail on the edit (`applied_detail`), so the rebuilt item can be undone after a reload. Nothing here re-runs chat."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .database.models import ReportChatMessage

APPLIED_DETAIL_KEYS = ("from", "insert", "removed", "left", "right")


def _uuid(x: Any) -> Optional[uuid.UUID]:
    try:
        return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))
    except (ValueError, TypeError, AttributeError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def save_turn(db: Session, report_id: str, user_text: str, reply_text: str, edits: List[dict]) -> Tuple[str, str]:
    """Save one turn; returns (user message id, assistant message id). The reply sorts after the question."""
    at = _now()
    user = ReportChatMessage(report_id=_uuid(report_id), role="user", content=user_text or "", created_at=at)
    reply = ReportChatMessage(report_id=_uuid(report_id), role="assistant", content=reply_text or "",
                              edits=list(edits or []), applied_item_ids=[],
                              created_at=at + timedelta(microseconds=1))
    db.add_all([user, reply])
    db.commit()
    return str(user.id), str(reply.id)


def _dump(row: ReportChatMessage) -> dict:
    return {"id": str(row.id), "role": row.role, "content": row.content, "edits": row.edits or [],
            "applied_item_ids": row.applied_item_ids or [],
            "created_at": row.created_at.isoformat() if row.created_at else None}


def list_thread(db: Session, report_id: str) -> List[dict]:
    rows = (db.query(ReportChatMessage).filter(ReportChatMessage.report_id == _uuid(report_id))
            .order_by(ReportChatMessage.created_at, ReportChatMessage.role.desc()).all())   # same instant: user first
    return [_dump(r) for r in rows]


class ChatTargetError(ValueError):
    """The applied update names a message or edit that cannot take it (→ 422)."""


def set_applied(db: Session, report_id: str, message_id: str, edit_index: int, item_id: str, applied: bool,
                detail: Optional[dict] = None) -> Optional[List[str]]:
    """Record Apply (applied=True) or Undo of one edit; returns the message's applied ids, None if not found."""
    mid = _uuid(message_id)
    row = db.get(ReportChatMessage, mid) if mid else None
    if row is None or row.report_id != _uuid(report_id):
        return None
    if row.role != "assistant":
        raise ChatTargetError("not an assistant message")
    edits = [dict(e) for e in (row.edits or [])]
    if not 0 <= edit_index < len(edits):
        raise ChatTargetError("edit_index out of range")
    ids = [i for i in (row.applied_item_ids or []) if i != item_id]
    if applied:
        ids.append(item_id)
        kept = {k: detail[k] for k in APPLIED_DETAIL_KEYS if k in detail} if detail else {}
        if kept:
            edits[edit_index]["applied_detail"] = kept
    else:
        edits[edit_index].pop("applied_detail", None)
    row.applied_item_ids, row.edits = ids, edits
    flag_modified(row, "applied_item_ids")
    flag_modified(row, "edits")
    db.commit()
    return ids
