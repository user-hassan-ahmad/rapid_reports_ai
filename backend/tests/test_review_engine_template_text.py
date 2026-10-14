"""The template's own words are never marked AI synthesis (review_engine/template_text.py + provenance / gate)."""
import pytest

from rapid_reports_ai.review_engine import dictated_gate as dg
from rapid_reports_ai.review_engine import engine, provenance
from rapid_reports_ai.review_engine import template_text as tt
from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.items import ReviewItem, Span, text_hash
from rapid_reports_ai.review_engine.jev_pass import JevPass
from rapid_reports_ai.template_sheet_grammar import parse_sheet
from tests.review_engine_fakes import inp, jev

RUN = "00000000-0000-0000-0000-0000000000f1"

CAC = ("Prospective ECG-gated coronary calcium scoring was performed initially using a Siemens Dual Source Flash "
       "multidetector scanner.")
CTCA = ("Prospective ECG gated coronary CT angiography was performed using a Siemens Dual Source Flash multidetector "
        "scanner. Axial cross sections of the heart were acquired with the patient in the supine position upon "
        "inspiratory breath hold. A separate workstation was used for 3D reformation of the dataset.")
SHEET = f"""## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Coronary Calcium Scoring (FINDINGS) | header: "Coronary calcium scoring:"
COVERS ["calcium score"]
FIXED "{CAC}"
RULE WHEN [context: calcium scoring was not done] REPLACE "{CAC}" WITH "Coronary calcium scoring was not performed due to {{reason}}."

## Paragraph: CTCA Procedure (FINDINGS) | header: "CTCA Procedure:"
COVERS ["acquisition"]
FIXED "{CTCA}"
RULE WHEN [context: a heart rate is given] USE "Average HR: {{rate}} bpm."
"""
INVENTED = "There is a moderate mixed plaque in the proximal circumflex artery."
REPORT = (f"FINDINGS:\nCoronary calcium scoring:\n{CAC}\nCTCA Procedure:\n{CTCA} Average HR: 58 bpm.\n"
          f"The LAD has a 50% stenosis. {INVENTED}\n"
          "IMPRESSION:\nModerate LAD stenosis.\n")
DICT = "- LAD 50% stenosis"


def _texts():
    st = parse_sheet(SHEET).structure
    assert st.usable
    return tt.unit_texts(st)


def _inp(report=REPORT, texts=None):
    i = inp(report, DICT, pathway="templated")
    return i.model_copy(update={"template_text": _texts() if texts is None else texts})


def _marked(items):
    return [it.anchor.text for it in items if it.kind == "ai_generated"]


# ── matching ───────────────────────────────────────────────────────────────

def test_unit_texts_hold_fixed_rule_and_header_wordings():
    texts = _texts()
    assert CAC in texts and CTCA in texts
    assert "Average HR: {rate} bpm." in texts
    assert "Coronary calcium scoring was not performed due to {reason}." in texts
    assert "Coronary calcium scoring:" in texts


def test_both_fixed_sentences_match_verbatim_and_hyphen_spacing_is_folded():
    m = tt.match(REPORT, [CAC, CTCA])
    owned = "".join(REPORT[s:e] for s, e in m.spans)
    assert "Prospective ECG-gated" in owned and "Prospective ECG gated" in owned
    assert m.unmatched == []
    folded = REPORT.replace("ECG-gated", "ECG gated").replace("Axial cross sections", "axial  cross-sections")
    m2 = tt.match(folded, [CAC, CTCA])
    assert len(m2.spans) == 2 and m2.unmatched == []


def test_a_multi_sentence_unit_matches_sentence_by_sentence_and_reports_the_missing_one():
    report = REPORT.replace(" Axial cross sections of the heart were acquired with the patient in the supine position "
                            "upon inspiratory breath hold.", "")
    m = tt.match(report, [CTCA])
    owned = " ".join(report[s:e] for s, e in m.spans)
    assert "A separate workstation was used for 3D reformation of the dataset" in owned
    assert m.unmatched == ["Axial cross sections of the heart were acquired with the patient in the supine position "
                           "upon inspiratory breath hold."]


def test_a_slot_value_is_not_in_the_spans():
    m = tt.match(REPORT, ["Average HR: {rate} bpm."])
    owned = [REPORT[s:e] for s, e in m.spans]
    assert all("58" not in o for o in owned)
    assert any("Average HR" in o for o in owned) and any("bpm" in o for o in owned)


def test_an_absent_unit_is_unmatched_and_short_units_own_nothing():
    m = tt.match(REPORT, ["No pericardial effusion.", "Normal."])
    assert m.spans == [] and m.unmatched == ["No pericardial effusion."]


def test_template_texts_of_a_config_without_a_grammar_sheet_is_empty():
    assert tt.template_texts({"generation_mode": "skill_sheet_guided", "skill_sheet": "free prose"}) == []
    assert tt.template_texts(None) == []
    assert CAC in tt.template_texts({"generation_mode": "skill_sheet_guided", "skill_sheet": SHEET})


# ── provenance ─────────────────────────────────────────────────────────────

def test_build_items_never_marks_template_text_but_marks_invented_text_and_the_slot_value():
    i = _inp()
    al = align(REPORT, DICT, "", i.artifacts.sections)
    items, log = provenance.build_items(i, RUN, al, None, [])
    marked = _marked(items)
    for m in marked:
        for frag in ("Prospective", "Axial cross sections", "separate workstation", "Average HR", "bpm"):
            assert frag not in m
    assert INVENTED in marked
    assert "58" in marked
    assert log["template_owned"] >= 3


def test_quick_report_or_no_template_text_is_unchanged():
    q = inp(REPORT, DICT)
    al = align(REPORT, DICT, "", q.artifacts.sections)
    items, log = provenance.build_items(q, RUN, al, None, [])
    assert any("Prospective ECG-gated" in m for m in _marked(items))
    assert log["template_owned"] == 0


def _suppressed_unsupported(report, text):
    s = report.index(text)
    return ReviewItem(key="k-unsup", report_id="00000000-0000-0000-0000-000000000001", run_id=RUN, lane="accuracy",
                      detectors=["jev.supported"], kind="unsupported", cls="suppress", section="FINDINGS",
                      anchor=Span(start=s, end=s + len(text), text=text, text_hash=text_hash(report)),
                      label="", reason="", evidence={}, status="open", history=[])


@pytest.mark.asyncio
async def test_synthesis_items_skip_template_words(monkeypatch):
    report = REPORT.replace("The LAD has a 50% stenosis.", "The LAD has a 50% stenosis on the Siemens scanner.")
    monkeypatch.setattr(provenance.rc, "_jev", jev({"syn*": {"choice": "not_stated"}}))
    for text, template, want_marked in ((CTCA.split(". ")[0] + ".", True, False),
                                        ("The LAD has a 50% stenosis on the Siemens scanner.", True, True)):
        i = _inp(report) if template else inp(report, DICT)
        al = align(report, DICT, "", i.artifacts.sections)
        # pair the clause with the dictated line so confirm considers it
        monkeypatch.setattr(provenance, "_paired", lambda al, c: True)
        out, log = await provenance.synthesis_items(i, RUN, al, None, [_suppressed_unsupported(report, text)], [], [])
        assert bool(out) is want_marked, (text, [it.anchor.text for it in out])
        for it in out:
            assert "Prospective" not in it.anchor.text


# ── dictated gate (live) ───────────────────────────────────────────────────

def test_gate_synth_runs_skip_template_words():
    i = _inp()
    body = REPORT
    al = align(body, DICT, "", i.artifacts.sections)
    units = [body[s:e] for s, e, _ in dg.units(al)]
    jp = JevPass(gate_texts=units)
    jp.gate = {f"g{k}": {"probabilities": {"all_stated": 0.0, "some_details_added": 0.0, "not_stated": 1.0}}
               for k in range(len(units))}
    jp.gate.update({f"t{k}": {"choice": "abnormal"} for k in range(len(units))})
    g = dg.classify(i, body, al, jp)
    prov, _, _, log = dg.apply(i, RUN, al, g, [], [])
    anchors = []
    for it in prov:
        if it.kind != "ai_generated":
            continue
        anchors.append(it.anchor.text)
        anchors += [a["text"] for a in (it.evidence or {}).get("also_anchors") or []]
    for a in anchors:
        for frag in ("Prospective", "Axial cross sections", "separate workstation", "3D reformation"):
            assert frag not in a
    assert any("circumflex" in a for a in anchors)
    assert log["template_owned"] >= 3


# ── loading ────────────────────────────────────────────────────────────────

def test_input_from_parts_carries_template_text_for_templated_reports_only():
    cand = {"content": REPORT, "sections": []}
    data = {"variables": {"FINDINGS": DICT}}
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": SHEET}
    t = engine.input_from_parts("00000000-0000-0000-0000-000000000001", "templated", data, cand, None, cfg)
    assert CAC in t.template_text
    q = engine.input_from_parts("00000000-0000-0000-0000-000000000001", "auto", data, cand, None, cfg)
    assert q.template_text == []
    assert engine.input_from_parts("00000000-0000-0000-0000-000000000001", "templated", data, cand, None
                                   ).template_text == []


def test_a_slot_value_never_crosses_a_sentence_end_but_holds_a_decimal():
    report = "The liver shows a new 3 cm mass. The spleen is normal."
    m = tt.match(report, ["The {organ} is normal."])
    assert [report[s:e] for s, e in m.spans] == ["The ", " is normal"]
    assert report.index("The spleen") == m.spans[0][0]
    m2 = tt.match("The mass measures 3.5 cm in length.", ["The mass measures {size} in length."])
    assert len(m2.spans) == 2 and m2.unmatched == []


# ── template_parts (the review run's and the rail's loading) ───────────────

class _Row:
    def __init__(self, report_type="templated", template_id="t1", id="r1"):
        self.report_type, self.template_id, self.id = report_type, template_id, id


class _Q:
    def __init__(self, log):
        self.log = log

    def filter(self, *a):
        return self

    def order_by(self, *a):
        return self

    def first(self):
        return self.log


class _Db:
    def __init__(self, tpl=None, log=None, query_raises=False):
        self.tpl, self.log, self.query_raises = tpl, log, query_raises

    def get(self, cls, _id):
        return self.tpl

    def query(self, cls):
        if self.query_raises:
            raise RuntimeError("no table")
        return _Q(self.log)


class _Obj:
    def __init__(self, **k):
        self.__dict__.update(k)


CFG = {"generation_mode": "skill_sheet_guided", "skill_sheet": SHEET}


def test_template_parts_fail_open_on_a_deleted_template_or_a_bad_config():
    assert engine.template_parts(_Db(tpl=None), _Row()) == {"template_config": None, "assumed_normals": []}
    bad = engine.template_parts(_Db(tpl=_Obj(template_config="not a dict")), _Row())
    assert bad["template_config"] is None
    i = engine.input_from_parts("00000000-0000-0000-0000-000000000001", "templated", {}, {"content": REPORT}, None,
                                bad["template_config"])
    assert i.template_text == [] and i.template_structure is None
    assert engine.template_parts(_Db(tpl=_Obj(template_config=CFG)), _Row(report_type="auto"))["template_config"] is None


def test_template_parts_reads_the_stack_gate_assumed_minus_removed_and_fails_open():
    gate = {"assumed": {"LMS": ["LMS: Normal."], "LAD": ["LAD: Normal proximal, mid and distal LAD."]},
            "removed": ["LMS: Normal."]}
    db = _Db(tpl=_Obj(template_config=CFG), log=_Obj(gate=gate))
    assert engine.template_parts(db, _Row(), {"stack": True})["assumed_normals"] == [
        "LAD: Normal proximal, mid and distal LAD."]
    assert engine.template_parts(db, _Row(), {})["assumed_normals"] == []          # not a stack report
    assert engine.template_parts(_Db(tpl=_Obj(template_config=CFG), query_raises=True), _Row(),
                                 {"stack": True})["assumed_normals"] == []
    assert engine.template_parts(_Db(tpl=_Obj(template_config=CFG), log=_Obj(gate={"assumed": "x"})), _Row(),
                                 {"stack": True})["assumed_normals"] == []


def test_the_rails_input_matches_the_review_runs():
    from rapid_reports_ai.review_engine import api
    rep = _Obj(id="00000000-0000-0000-0000-000000000001", report_type="templated", template_id="t1",
               input_data={"variables": {"FINDINGS": DICT}}, enhancement_json=None,
               candidate_reports=[{"content": REPORT, "sections": []}])
    i = api._input(rep, REPORT, _Db(tpl=_Obj(template_config=CFG)))
    assert CAC in i.template_text and i.template_structure is not None
