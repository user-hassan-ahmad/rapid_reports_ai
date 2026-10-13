"""CAD-RADS 2.0 outcome caveats travel into the Apply proposal (reference fields do not), so compaction must never
move them out of the outcomes. Each outcome keeps at least the caveats it had after the clinical read (d55e279)."""
import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[2] / "guidelines" / "cad-rads-2" / "entry.json"

EXPECTED = {
    "stable_0": 0, "acute_0": 0, "stable_n": 1, "acute_n": 1, "stable_1_p1": 1, "stable_1_p2": 1, "stable_1_p34": 1,
    "stable_2_p12": 1, "stable_2_p34": 1, "acute_1_p12": 3, "acute_1_p34": 3, "acute_2_p12": 4, "acute_2_p34": 4,
    "stable_2_p12_i": 3, "stable_2_p34_i": 3, "acute_2_p12_i": 6, "acute_2_p34_i": 6, "stable_3": 5, "stable_3_ipos": 3,
    "stable_3_ineg_defer": 4, "stable_3_ineg_infarct": 6, "stable_3_iborder_ffr": 3, "stable_3_iborder_ctp": 5,
    "stable_4a": 6, "stable_4a_ipos": 3, "stable_4a_ineg_defer": 4, "stable_4a_ineg_infarct": 7,
    "stable_4a_iborder_ffr": 3, "stable_4a_iborder_ctp": 6, "acute_3": 4, "acute_3_ipos": 3, "acute_3_ineg": 6,
    "acute_3_iborder_ffr": 3, "acute_3_iborder_ctp": 4, "acute_4a": 5, "acute_4a_ipos": 3, "acute_4a_ineg": 7,
    "acute_4a_iborder_ffr": 3, "acute_4a_iborder_ctp": 5, "stable_4b": 2, "stable_5": 3, "acute_4b": 2, "acute_5": 4,
    "stable_1_e": 3, "stable_2_e": 3, "stable_3_e": 3, "stable_4a_e": 3, "stable_4b_e": 3, "stable_5_e": 3,
    "acute_1_e": 3, "acute_2_e": 3, "acute_3_e": 3, "acute_4a_e": 3, "acute_4b_e": 3, "acute_5_e": 3,
    "management_not_defined": 1,
}

# Conditions the clinical read required on specific outcomes, by a phrase each caveat must keep.
REQUIRED = {
    "stable_3_ineg_defer": "persist despite adequate medical therapy",      # Table 4 footnote d (I-2)
    "stable_4a_ineg_defer": "persist despite adequate medical therapy",
    "stable_3_ineg_infarct": "fixed perfusion defect",                       # Table 1 footnote a
    "acute_3_ineg": "not specific to acute chest pain",                      # I-3
    "acute_4a_ineg": "not specific to acute chest pain",
    "stable_4a": "ICA may be favoured",                                      # Table 4 footnote e
}


def test_every_cad_rads_outcome_keeps_its_caveats():
    outcomes = {o["id"]: o for o in json.loads(PACK.read_text())["outcomes"]}
    assert set(outcomes) == set(EXPECTED)
    short = {k: (len(outcomes[k]["caveats"]), n) for k, n in EXPECTED.items() if len(outcomes[k]["caveats"]) < n}
    assert not short, short
    assert sum(len(o["caveats"]) for o in outcomes.values()) >= 185
    for oid, phrase in REQUIRED.items():
        assert any(phrase in c for c in outcomes[oid]["caveats"]), (oid, phrase)
