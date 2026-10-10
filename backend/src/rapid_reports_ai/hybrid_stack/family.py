"""Jev maps a free-text scan type to a schema family, or "none" (spec §3.3). Confidence alone did not
flag a missing family (cardiac MRI went to chest at 1.0), hence the explicit option."""
from __future__ import annotations

import os

from ..jev_client import JEV_MODEL, jev_post
from .schemas import family_keys, library

NONE = "none"
TIMEOUT_S = 10.0


async def choose_family(scan_type: str, history: str, transport=None) -> tuple[str, float]:
    fams = library()["families"]
    crit = {k: fams[k]["description"] for k in family_keys()}
    crit[NONE] = ("None of the other options describes this examination: a different body part, joint, "
                  "organ-specific or specialist examination that the options do not name.")
    q = {"type": "choice", "instructions": "Which kind of examination is this?", "criteria": crit}
    r = await jev_post({"model": JEV_MODEL, "state": f"Scan type: {scan_type}\nClinical history: {history}",
                        "questions": {"family": q}}, os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    a = r.json()["answers"]["family"]
    return a["choice"], float(a.get("confidence") or 0.0)
