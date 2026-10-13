"""Chat-to-edit turns stored with the template (template pipeline spec, block 4): the instruction a radiologist gave,
the reply, and whether it was applied, identifier-shaped spans scrubbed first. Evidence for the later learning loop, so recording never fails the request
and never logs the text (only the exception type)."""
import json
import logging
import uuid

from .database.models import TemplateChatTurn
from .template_examples import scrub
from .template_sheet_structure import sheet_hash

logger = logging.getLogger(__name__)

MAX_CREATOR_TURNS = 50
MAX_FIELD = 4000
MAX_ROUTING = 20000


def _scrub_obj(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, dict):
        return {k: _scrub_obj(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_scrub_obj(x) for x in v]
    return v


def _routing(r):
    """The router's evidence, identifier-shaped spans scrubbed, capped (a capped record keeps version and route)."""
    if not r:
        return None
    r = _scrub_obj(r)
    try:
        size = len(json.dumps(r))
    except (TypeError, ValueError):
        return {"unserialisable": True}
    return r if size <= MAX_ROUTING else {"truncated": True, "version": r.get("version"), "route": r.get("route")}


def _text(v) -> str:
    return v if isinstance(v, str) else ""


def _clean(v) -> str:
    """Stored text: identifier-shaped spans removed (names, NHS numbers, dates), then capped."""
    return scrub(_text(v))[:MAX_FIELD]


def record_turn(db, template_id, instruction: str, response: str, applied: bool,
                sheet_before: str, sheet_after: str, routing: dict | None = None) -> None:
    try:
        db.add(TemplateChatTurn(
            template_id=template_id, instruction=_clean(instruction),
            response=_clean(response), applied=applied,
            sheet_hash_before=sheet_hash(sheet_before or ""), sheet_hash_after=sheet_hash(sheet_after or ""),
            routing=_routing(routing),
        ))
        db.commit()
    except Exception as e:   # evidence only
        db.rollback()
        logger.warning("chat turn not stored for %s: %s", template_id, type(e).__name__)


def store_creator_turns(db, template_id, turns: list[dict]) -> int:
    """The creator's turns, sent with the first save (the template did not exist while they happened)."""
    try:
        template_id = uuid.UUID(str(template_id))
    except ValueError:
        return 0
    try:
        rows = []
        for t in (turns or [])[:MAX_CREATOR_TURNS]:
            t = t or {}
            instruction = _text(t.get("instruction")).strip()
            if not instruction:
                continue
            rows.append(TemplateChatTurn(template_id=template_id, instruction=_clean(instruction),
                                         response=_clean(t.get("response")), applied=True))
        if not rows:
            return 0
        db.add_all(rows)
        db.commit()
        return len(rows)
    except Exception as e:   # evidence only
        db.rollback()
        logger.warning("chat turns not stored for %s: %s", template_id, type(e).__name__)
        return 0
