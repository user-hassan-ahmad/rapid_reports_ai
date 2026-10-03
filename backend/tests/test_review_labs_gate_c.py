import json
import os
from pathlib import Path

import pytest

from rapid_reports_ai.scripts.review_labs import additions_map as AM

CARD = {"finding_number": 1, "finding": "12 mm left renal lesion", "finding_short_label": "Left renal lesion",
        "classifications": [{"system": "Bosniak 2019", "grade": "II", "criteria": "Thin septa ...", "management": "x"}],
        "thresholds": [{"parameter": "size", "threshold": "4 cm", "significance": "s", "context": "c"}],
        "follow_up_actions": [{"modality": "US", "timing": "6 months", "indication": "i", "urgency": "routine",
                               "guideline_source": "g"}, {"modality": "MRI", "timing": "", "indication": "j"}],
        "differentials": [{"diagnosis": "d1"}], "imaging_flags": ["f1"], "sources": [{"url": "u", "title": "t"}]}


def test_map_card_kinds_and_citation():
    cands = AM.map_card(CARD)
    kinds = [c["kind"] for c in cands]
    assert kinds == ["grade", "threshold", "follow_up", "option", "option", "option"]
    g = cands[0]
    assert g["lane"] == "additions" and g["detector"] == "s4.classification"
    assert g["evidence"]["system"] == "Bosniak 2019" and "criteria" not in g["evidence"]
    assert g["citation"] == {"card": 1, "source": "u", "label": "t"}


def test_map_card_with_criteria_arm():
    g = AM.map_card(CARD, with_criteria=True)[0]
    assert g["evidence"]["criteria"] == "Thin septa ..."


def test_system_key_normalises():
    assert AM.system_key("Bosniak classification v2019") == AM.system_key("Bosniak 2019") == "bosniak"
    assert AM.system_key("LI-RADS v2018") == "lirads"
    assert AM.system_key("C-RADS v2") == AM.system_key("C-RADS")
    assert AM.system_key("2019 Bosniak") == AM.system_key("Bosniak 2019") == AM.system_key("The Bosniak classification") == "bosniak"
    assert AM.system_key("O-RADS US") != AM.system_key("O-RADS MRI")
    assert AM.system_key("O-RADS US") == "orads_us" and AM.system_key("LI-RADS US") == "lirads_us"
    assert AM.system_key("AAST 2018 splenic") == "aast_spleen"


def test_cand_keeps_zero_grade_and_citation_guards_sources():
    card = {"finding": "f", "sources": ["not a dict"], "classifications": [{"system": "Garden", "grade": 0}]}
    c = AM.map_card(card)[0]
    assert c["evidence"]["grade"] == 0
    assert c["citation"]["source"] is None


def test_system_key_covers_s1_phase3_systems():
    path = Path(__file__).resolve().parent.parent / "test_cases" / "jev_tool_lab" / "s1_phase3.json"
    systems = sorted({c["system"] for c in json.loads(path.read_text())})
    keys = {s: AM.system_key(s) for s in systems}
    assert all(keys.values()), {s: k for s, k in keys.items() if not k}
    aast = [s for s in systems if s.startswith("AAST 2018")]
    print("AAST systems collapsing to one key:", {s: keys[s] for s in aast})
    assert len(aast) == 3 and {keys[s] for s in aast} == {"aast_kidney", "aast_liver", "aast_spleen"}
