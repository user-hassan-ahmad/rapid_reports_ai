# backend/src/rapid_reports_ai/scripts/review_labs/additions_map.py
"""S4 synthesis card → Additions candidates (spec §6.4), and a criteria-by-system index for the Gate C arm."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List

_ALIASES = {"cadrads": "cadrads", "tirads": "tirads", "acrtirads": "tirads", "orads": "orads", "orad": "orads",
            "lirads": "lirads", "lungrads": "lungrads", "pirads": "pirads", "birads": "birads", "bosniak": "bosniak",
            "fleischner": "fleischner", "kellgrenlawrence": "kellgrenlawrence", "cacdrs": "cacdrs", "garden": "garden",
            "nascet": "nascet", "modic": "modic", "pfirrmann": "pfirrmann", "aast": "aast"}

_QUAL_NORM = {"splenic": "spleen", "hepatic": "liver", "renal": "kidney"}


def system_key(name: str) -> str:
    """Lower-case letters of the system name up to its first version/year token, mapped through _ALIASES.
    A qualifier (modality or organ) is kept as a suffix so O-RADS US and O-RADS MRI stay distinct."""
    n = re.sub(r"^\s*(?:the\s+)?(?:(?:19|20)\d{2}\s+)?", "", name or "", flags=re.I)
    qm = re.search(r"\b(us|mri|ct|spleen|splenic|liver|hepatic|kidney|renal)\b", n, flags=re.I)
    qual = _QUAL_NORM.get(qm.group(1).lower(), qm.group(1).lower()) if qm else ""
    if qm:
        n = n[:qm.start()] + " " + n[qm.end():]
    head = re.split(r"\b(?:v?\d+(?:\.\d+)*|classification|criteria|system|version)\b", n, maxsplit=1, flags=re.I)[0]
    key = re.sub(r"[^a-z]", "", head.lower())
    for k, v in _ALIASES.items():
        if key.startswith(k):
            key = v
            break
    return f"{key}_{qual}" if qual and key else key


def _citation(card: dict) -> dict:
    src = (card.get("sources") or [{}])[0]
    if not isinstance(src, dict):
        src = {}
    return {"card": card.get("finding_number"), "source": src.get("url"), "label": src.get("title")}


def _cand(card: dict, kind: str, detector: str, evidence: dict) -> dict:
    return {"lane": "additions", "kind": kind, "detector": detector, "line": None,
            "anchor": card.get("finding_short_label") or card.get("finding"),
            "evidence": {"finding": card.get("finding"), **{k: v for k, v in evidence.items() if v not in (None, "")}},
            "citation": _citation(card)}


def map_card(card: dict, with_criteria: bool = False) -> List[dict]:
    out = []
    for c in card.get("classifications") or []:
        ev = {"system": c.get("system"), "grade": c.get("grade")}
        if with_criteria:
            ev["criteria"] = c.get("criteria")
        out.append(_cand(card, "grade", "s4.classification", ev))
    for t in card.get("thresholds") or []:
        out.append(_cand(card, "threshold", "s4.threshold",
                         {"parameter": t.get("parameter"), "threshold": t.get("threshold"), "significance": t.get("significance")}))
    for i, f in enumerate(card.get("follow_up_actions") or []):
        out.append(_cand(card, "follow_up" if i == 0 else "option", "s4.follow_up",
                         {"modality": f.get("modality"), "timing": f.get("timing"), "indication": f.get("indication")}))
    for d in card.get("differentials") or []:
        out.append(_cand(card, "option", "s4.differential", {"text": d.get("diagnosis")}))
    for fl in card.get("imaging_flags") or []:
        out.append(_cand(card, "option", "s4.imaging_flag", {"text": fl if isinstance(fl, str) else str(fl)}))
    return out


def criteria_index(cards: Iterable[dict]) -> Dict[str, List[str]]:
    """system key → distinct per-grade criteria texts seen in production synthesis (each defines ONE grade)."""
    idx: Dict[str, set] = defaultdict(set)
    for card in cards:
        for c in card.get("classifications") or []:
            if c.get("criteria"):
                idx[system_key(c.get("system", ""))].add(f"{c.get('grade')}: {c['criteria'].strip()}")
    return {k: sorted(v) for k, v in idx.items()}


def criteria_lookup(idx: Dict[str, List[str]], system: str) -> List[str]:
    """Criteria for `system`: its qualified key first, then the unqualified one ("lirads_ct" → "lirads")."""
    key = system_key(system)
    if key in idx:
        return idx[key]
    return idx.get(key.split("_", 1)[0], [])
