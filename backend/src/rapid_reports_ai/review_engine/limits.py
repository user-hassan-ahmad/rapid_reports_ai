"""Size limits on what a client sends to the review and chat endpoints (F2 M2). A body over a limit fails pydantic
validation, so FastAPI answers 422 before any work is done."""
from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional

from pydantic import AfterValidator, Field, StringConstraints

DETAIL_MAX_KEYS = 20
DETAIL_MAX_BYTES = 65536  # apply/undo details carry the inserted and removed text; a report-sized edit must fit
TEXT_HASH_MAX = 64
TEXT_MAX = 100_000
IDS_MAX = 200
ID_MAX = 128


def _bounded_detail(v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if v is None:
        return v
    if len(v) > DETAIL_MAX_KEYS:
        raise ValueError(f"detail has more than {DETAIL_MAX_KEYS} keys")
    if len(json.dumps(v, default=str).encode()) > DETAIL_MAX_BYTES:
        raise ValueError(f"detail is over {DETAIL_MAX_BYTES} bytes")
    return v


Detail = Annotated[Dict[str, Any], AfterValidator(_bounded_detail)]
TextHash = Annotated[str, StringConstraints(max_length=TEXT_HASH_MAX)]
ReportText = Annotated[str, StringConstraints(max_length=TEXT_MAX)]
ItemId = Annotated[str, StringConstraints(max_length=ID_MAX)]
ItemIds = Annotated[List[ItemId], Field(max_length=IDS_MAX)]

__all__ = ["DETAIL_MAX_KEYS", "DETAIL_MAX_BYTES", "TEXT_HASH_MAX", "TEXT_MAX", "IDS_MAX", "Detail", "TextHash",
           "ReportText", "ItemId", "ItemIds"]
