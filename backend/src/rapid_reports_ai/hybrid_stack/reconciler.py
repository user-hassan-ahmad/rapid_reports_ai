"""Reconciler (spec §3.3): for a scan type seen for the first time, keep a family as-is or compose
one from the region library plus new regions. Qwen with reasoning; plain JSON and Title Case,
because uppercase output with reasoning on corrupted names on Cerebras ("MEDIASTINUM" -> "MEDIUMIUM",
11/12 lists; Title Case 0/12). Code validates; the caller caches."""
from __future__ import annotations

import asyncio
import json
import os

from pydantic import BaseModel, Field

from .http import post_json
from .schemas import Region, family_keys, family_regions, library, other_region

MAX_NEW_REGIONS = 8
_RESERVED = {"technique", "conclusion", "general", "other findings", "incidental findings", "other", "incidental"}

RECONCILE_SYSTEM = ("You build the region list for a radiology examination's visual schema. Regions are broad zones "
                    "a radiologist reports one by one; each region lists what it includes.")

RECONCILE_USER = """Scan type: {scan_type}
Clinical history: {history}

FAMILIES (key — what it is for — its regions):
{families}

REGION LIBRARY (key — name — includes):
{library}

If one family above already gives this examination a useful region list as it stands (its regions match what this examination reports, at the right level of detail), reply {{"family": "<family key>"}}.

Otherwise build the ordered region list for this examination, in the order a radiologist reports it:
- Reuse a library region (by its key) wherever it fits this examination as it is.
- Add a new region only for a structure or compartment this examination reports separately and no library region covers. Give it a short name and an includes list in the same style.
- Keep regions broad: one region per structure or compartment the radiologist would report on its own line, typically 6 to 12 regions. Include structures incidentally in the field of view as one region.
- When anatomy differs between patients and the scan type does not say which applies, use one neutral region.
- Do not add Technique, Conclusion, General, Other or Incidental regions: they always exist, and incidental findings outside the listed regions go to "Other findings".
- Write names in Title Case.

Reply as JSON: either {{"family": "<family key>"}} or {{"regions": [{{"key": "<library key>"}} or {{"name": "<new name>", "includes": "<what it includes>"}}]}}"""

URL = "https://api.cerebras.ai/v1/chat/completions"
MODEL = "qwen-3.8-27b"


class Reconciled(BaseModel):
    regions: list[Region]
    family: str | None = None  # set when an existing family was kept as-is
    log: dict = Field(default_factory=dict)


def _prompt(scan_type: str, history: str) -> str:
    lib = library()
    fams = "\n".join(f"{k} — {lib['families'][k]['description']} — {', '.join(r.name for r in family_regions(k))}"
                     for k in family_keys())
    regions = "\n".join(f"{k} — {v['name']} — {v['includes']}" for k, v in lib["regions"].items()
                        if k != "other" and not k.startswith("generic_"))
    return RECONCILE_USER.format(scan_type=scan_type, history=history or "(not specified)", families=fams, library=regions)


def validate(out: dict) -> Reconciled:
    if out.get("family") in family_keys():
        return Reconciled(regions=family_regions(out["family"]), family=out["family"], log={"family": out["family"]})
    lib = library()["regions"]
    regions, seen, reused, new, dropped = [], set(), [], [], []
    for it in out.get("regions") or []:
        key = it.get("key")
        if key in lib and key != "other" and not key.startswith("generic_"):
            name, inc = lib[key]["name"], lib[key]["includes"]
            kind = "reused"
        elif not key and it.get("name") and it.get("includes") and len(new) < MAX_NEW_REGIONS:
            name, inc = str(it["name"]).strip(), str(it["includes"]).strip()
            kind = "new"
        else:
            dropped.append(it)
            continue
        if name.lower() in seen or name.lower() in _RESERVED:
            dropped.append(it)
            continue
        seen.add(name.lower())
        (reused if kind == "reused" else new).append(name if kind == "new" else key)
        regions.append(Region(name=name, includes=inc))
    if not regions:
        raise ValueError("reconciler returned no usable regions")
    regions.append(other_region())
    return Reconciled(regions=regions, log={"reused": reused, "new": new, "dropped": dropped})


async def reconcile(scan_type: str, history: str, transport=None) -> Reconciled:
    body = {"model": MODEL, "temperature": 0.1, "max_tokens": 8000, "reasoning_effort": "medium",
            "messages": [{"role": "system", "content": RECONCILE_SYSTEM},
                         {"role": "user", "content": _prompt(scan_type, history)}],
            "response_format": {"type": "json_object"}}
    key = os.environ.get("CEREBRAS_API_KEY", "")
    for attempt in range(3):
        r = await post_json(URL, key, body, 30.0, transport)
        if r.status_code != 429:
            break
        await asyncio.sleep(1 + 2 * attempt)
    r.raise_for_status()
    return validate(json.loads(r.json()["choices"][0]["message"]["content"]))
