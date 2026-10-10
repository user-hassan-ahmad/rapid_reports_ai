"""Region lists for the hybrid stack (spec §3.3): the schema library and the fixed groups."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

TECHNIQUE, GENERAL, CONCLUSION, OTHER = "Technique", "General", "Conclusion", "Other findings"
FIXED = (TECHNIQUE, GENERAL, CONCLUSION)
GENERIC_FAMILY = "generic"


class Region(BaseModel):
    name: str
    includes: str


@lru_cache(maxsize=1)
def library() -> dict:
    return json.loads(Path(__file__).with_name("schema_library.json").read_text())


def family_keys() -> list[str]:
    """Families offered to Jev and the reconciler (the generic fallback is never offered)."""
    return [k for k in library()["families"] if k != GENERIC_FAMILY]


def family_regions(family: str) -> list[Region]:
    lib = library()
    out: list[Region] = []
    for key in lib["families"][family]["regions"]:
        if key.startswith("@"):
            out += [Region(name=lvl, includes=lib["level_includes"]) for lvl in lib["levels"][key[1:]]]
        else:
            r = lib["regions"][key]
            out.append(Region(name=r["name"], includes=r["includes"]))
    return out


def other_region() -> Region:
    r = library()["regions"]["other"]
    return Region(name=r["name"], includes=r["includes"])


def groups_for(regions: list[Region]) -> list[str]:
    return [TECHNIQUE] + [r.name for r in regions] + [GENERAL, CONCLUSION]


def pill_regions(regions: list[Region]) -> list[str]:
    """The checklist pills: every region except the catch-all."""
    return [r.name for r in regions if r.name != OTHER]


def scan_key(scan_type: str) -> str:
    return re.sub(r"\s+", " ", (scan_type or "").strip().lower())
