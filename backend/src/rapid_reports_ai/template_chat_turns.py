"""Chat-to-edit turns stored with the template (template pipeline spec, block 4): the instruction a radiologist gave,
the reply, and whether it was applied. Evidence for the later learning loop, so recording never fails the request
and never logs the text (only the exception type)."""
import logging
import uuid

from .database.models import TemplateChatTurn
from .template_sheet_structure import sheet_hash

logger = logging.getLogger(__name__)

MAX_CREATOR_TURNS = 50
MAX_FIELD = 4000


def _text(v) -> str:
    return v if isinstance(v, str) else ""


def record_turn(db, template_id, instruction: str, response: str, applied: bool,
                sheet_before: str, sheet_after: str) -> None:
    try:
        db.add(TemplateChatTurn(
            template_id=template_id, instruction=(instruction or "")[:MAX_FIELD],
            response=(response or "")[:MAX_FIELD], applied=applied,
            sheet_hash_before=sheet_hash(sheet_before or ""), sheet_hash_after=sheet_hash(sheet_after or ""),
        ))
        db.commit()
    except Exception as e:   # evidence only
        db.rollback()
        logger.warning("chat turn not stored for %s: %s", template_id, type(e).__name__)


def store_creator_turns(db, template_id, turns: list[dict]) -> int:
    """The creator's turns, sent with the first save (the template did not exist while they happened)."""
    try:
        template_id = uuid.UUID(str(template_id))
        rows = []
        for t in (turns or [])[:MAX_CREATOR_TURNS]:
            t = t or {}
            instruction = _text(t.get("instruction")).strip()
            if not instruction:
                continue
            rows.append(TemplateChatTurn(template_id=template_id, instruction=instruction[:MAX_FIELD],
                                         response=_text(t.get("response"))[:MAX_FIELD], applied=True))
        if not rows:
            return 0
        db.add_all(rows)
        db.commit()
        return len(rows)
    except Exception as e:   # evidence only
        db.rollback()
        logger.warning("chat turns not stored for %s: %s", template_id, type(e).__name__)
        return 0
