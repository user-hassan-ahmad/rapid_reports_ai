import pytest

from rapid_reports_ai.template_required_values import (apply_required_values, backstop, missing_line, values_applied,
                                                       write_missing)
from rapid_reports_ai.template_sheet_grammar import parse_sheet

SHEET = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP

## Paragraph: Left ventricle (FINDINGS)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal left ventricular size and function."
"""
LINE = 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "LV mass index" | "RVEF"] AT TOP'

HEADED = """## Report Structure
SECTION OPENING | header: none | role: other
SECTION LV | header: "LEFT VENTRICLE" | role: findings
SECTION RV | header: "RIGHT VENTRICLE" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["RVEF"] AT TOP

## Paragraph: Left ventricle (LV)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal LV."
"""


def test_the_list_line_leaves_the_sheet_and_the_record_keeps_the_na_items():
    text, rec = apply_required_values(SHEET, ["rvef.", " LV MASS INDEX"])
    assert LINE not in text and "LIST_MISSING" not in text and text.endswith("\n")
    assert rec == {"lists": [{"line": 6, "items": ["LVEF", "LV mass index", "RVEF"], "na": ["LV mass index", "RVEF"],
                              "position": "top", "section": "FINDINGS", "outcome": "applied"}],
                   "skipped": None, "error": None}
    assert values_applied(rec)
    res = parse_sheet(text, mode="template")
    assert res.errors == [] and res.structure.usable


def test_nothing_marked_na_still_removes_the_line():
    text, rec = apply_required_values(SHEET, [])
    assert "LIST_MISSING" not in text and rec["lists"][0]["na"] == [] and values_applied(rec)


def test_an_item_on_two_lists_is_listed_once():
    two = SHEET + 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["lvef" | "LV wall thickness"] AT END\n'
    text, rec = apply_required_values(two, ["LVEF", "LV wall thickness"])
    assert "LIST_MISSING" not in text
    assert [e["na"] for e in rec["lists"]] == [["LVEF"], ["LV wall thickness"]]


def test_a_sheet_without_a_list_or_not_parsing_clean_is_unchanged_and_not_applied():
    plain = SHEET.replace(LINE + "\n", "")
    assert apply_required_values(plain, ["LVEF"]) == (plain, {"lists": [], "skipped": "no_list", "error": None})
    legacy = "## FINDINGS\nLVEF: {value}\n"
    text, rec = apply_required_values(legacy, [])
    assert (text, rec) == (legacy, {"lists": [], "skipped": "parse", "error": None}) and not values_applied(rec)


def test_never_raises(monkeypatch):
    import rapid_reports_ai.template_required_values as M

    def boom(sheet):
        raise RuntimeError("parser down")
    monkeypatch.setattr(M, "_clean", boom)
    text, rec = apply_required_values(SHEET, [])
    assert text == SHEET and rec["error"].startswith("RuntimeError") and not values_applied(rec)


def test_code_writes_the_literal_line_at_the_top_of_its_section_and_strips_the_generators():
    _, rec = apply_required_values(SHEET, ["RVEF", "LV mass index"])
    report = "Findings:\nValues not provided: LVEF, RVEF.\nNormal LV.\n\nConclusion:\nNormal."
    assert write_missing(report, SHEET, rec["lists"]) == (
        "Values not provided: LV mass index, RVEF.\n\nFindings:\nNormal LV.\n\nConclusion:\nNormal.", 1)
    assert missing_line(["RVEF"]) == "Values not provided: RVEF."


def test_at_end_without_headers_and_by_section_header():
    end = SHEET.replace("AT TOP", "AT END")
    _, rec = apply_required_values(end, ["LVEF"])
    assert write_missing("Findings:\nNormal LV.\n\nConclusion:\nNormal.", end, rec["lists"])[0] == \
        "Findings:\nNormal LV.\n\nValues not provided: LVEF.\n\nConclusion:\nNormal."
    _, rec = apply_required_values(SHEET, ["LVEF"])
    assert write_missing("Normal LV.", SHEET, rec["lists"])[0] == "Values not provided: LVEF.\n\nNormal LV."
    _, rec = apply_required_values(HEADED, ["RVEF"])
    report = "No previous CMR available.\n\nLEFT VENTRICLE\nNormal LV.\n\nRIGHT VENTRICLE\nNormal RV.\n\nConclusion:\nNormal."
    assert write_missing(report, HEADED, rec["lists"])[0] == (
        "No previous CMR available.\n\nValues not provided: RVEF.\n\nLEFT VENTRICLE\nNormal LV.\n\nRIGHT VENTRICLE\n"
        "Normal RV.\n\nConclusion:\nNormal.")


def test_nothing_na_writes_nothing_but_strips_an_unrequested_list():
    _, rec = apply_required_values(SHEET, [])
    assert write_missing("Findings:\nValues not provided: RVEF.\nNormal LV.", SHEET, rec["lists"]) == ("Findings:\nNormal LV.", 1)


def test_write_missing_never_raises(monkeypatch):
    import rapid_reports_ai.template_required_values as M

    def boom(sheet):
        raise RuntimeError("parser down")
    monkeypatch.setattr(M, "_clean", boom)
    assert write_missing("Normal LV.", SHEET, [{"na": ["LVEF"], "position": "top", "section": "FINDINGS",
                                                "outcome": "applied"}]) == ("Normal LV.", 0)


def _scores(ps, seen=None):
    async def ask(report, items):
        if seen is not None:
            seen.update(report=report, items=items)
        return ps
    return ask


async def test_backstop_lists_and_flags_a_filled_value_the_report_lacks():
    _, rec = apply_required_values(SHEET, ["RVEF"])
    seen = {}
    lists, flags, b = await backstop("Findings:\nLVEF 45%.", rec["lists"], ["LVEF", "LV mass index"],
                                     ask=_scores([0.9, 0.2], seen))
    assert seen == {"report": "Findings:\nLVEF 45%.", "items": ["LVEF", "LV mass index"]}
    assert lists[0]["na"] == ["RVEF", "LV mass index"] and rec["lists"][0]["na"] == ["RVEF"]   # the input is untouched
    assert flags == [{"kind": "value_missing", "text": "LV mass index",
                      "message": "Required value LV mass index not found in the report"}]
    assert b == {"asked": 2, "missing": ["LV mass index"], "error": None}
    assert write_missing("Findings:\nLVEF 45%.", SHEET, lists)[0] == \
        "Values not provided: RVEF, LV mass index.\n\nFindings:\nLVEF 45%."


async def test_backstop_creates_the_line_when_nothing_was_marked_na():
    _, rec = apply_required_values(SHEET, [])
    lists, flags, _ = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF"], ask=_scores([0.1]))
    assert write_missing("Findings:\nNormal.", SHEET, lists)[0] == "Values not provided: LVEF.\n\nFindings:\nNormal."
    assert [f["text"] for f in flags] == ["LVEF"]


async def test_backstop_leaves_a_value_the_report_states_alone():
    _, rec = apply_required_values(SHEET, [])
    lists, flags, b = await backstop("Findings:\nLVEF 45%.", rec["lists"], ["LVEF"], ask=_scores([0.9]))
    assert lists == rec["lists"] and flags == [] and b["missing"] == []
    assert write_missing("Findings:\nLVEF 45%.", SHEET, lists)[0] == "Findings:\nLVEF 45%."


_UNAVAILABLE = [{"kind": "value_check_unavailable", "text": "",
                 "message": "Required values could not be checked against the report"}]


async def test_backstop_jev_failure_changes_nothing_and_says_so_once():
    _, rec = apply_required_values(SHEET, [])

    async def boom(report, items):
        raise RuntimeError("jev down")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF", "LV mass index"], ask=boom)
    assert lists is rec["lists"] and flags == _UNAVAILABLE and b["error"].startswith("RuntimeError")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["LVEF"], ask=_scores([]))
    assert lists is rec["lists"] and flags == _UNAVAILABLE and b["error"] == "jev: answer count mismatch"


@pytest.mark.parametrize("filled", [[], [" "], None])
async def test_backstop_without_filled_items_asks_nothing(filled):
    _, rec = apply_required_values(SHEET, [])

    async def fail(report, items):
        raise AssertionError("no call")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], filled or [], ask=fail)
    assert lists is rec["lists"] and flags == [] and b == {"asked": 0, "missing": [], "error": None}


async def test_backstop_reads_the_report_without_the_generators_na_lines():
    _, rec = apply_required_values(SHEET, [])
    seen = {}
    lists, flags, _ = await backstop("Findings:\nValues not provided: LVEF.\nNormal LV.", rec["lists"], ["LVEF"],
                                     ask=_scores([0.1], seen))
    assert "Values not provided" not in seen["report"] and seen["report"] == "Findings:\nNormal LV."
    assert lists[0]["na"] == ["LVEF"] and [f["text"] for f in flags] == ["LVEF"]


async def test_backstop_never_lists_or_flags_an_item_the_template_does_not_require():
    _, rec = apply_required_values(SHEET, [])
    seen = {}
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["Aortic root", "lvef."],
                                     ask=_scores([0.1], seen))
    assert seen["items"] == ["lvef."] and b["asked"] == 1
    assert lists[0]["na"] == ["lvef."] and [f["text"] for f in flags] == ["lvef."]

    async def fail(report, items):
        raise AssertionError("no call")
    lists, flags, b = await backstop("Findings:\nNormal.", rec["lists"], ["Aortic root"], ask=fail)
    assert lists is rec["lists"] and flags == [] and b["asked"] == 0
    assert "Aortic root" not in write_missing("Findings:\nNormal.", SHEET, lists)[0]


def test_write_missing_records_its_error(monkeypatch):
    import rapid_reports_ai.template_required_values as M

    def boom(sheet):
        raise RuntimeError("parser down")
    monkeypatch.setattr(M, "_clean", boom)
    r: dict = {}
    assert write_missing("Normal LV.", SHEET, [{"na": ["LVEF"], "position": "top", "section": "FINDINGS",
                                                "outcome": "applied"}], rec=r) == ("Normal LV.", 0)
    assert r["write_error"].startswith("RuntimeError")


def test_top_placement_after_an_inline_header_goes_on_its_own_line():
    _, rec = apply_required_values(SHEET, ["LVEF"])
    assert write_missing("Findings: Normal LV.\n\nConclusion: Normal.", SHEET, rec["lists"])[0] == \
        "Values not provided: LVEF.\n\nFindings: Normal LV.\n\nConclusion: Normal."
    # anchored to another section with an inline header: the line goes on its own line inside it
    two = SHEET.replace('SECTION CONCLUSION', 'SECTION VESSELS | header: "Vessels:" | role: findings\nSECTION CONCLUSION')
    two = two.replace("AT TOP", "AT TOP | section: VESSELS")
    _, rec = apply_required_values(two, ["LVEF"])
    assert write_missing("Findings: Normal LV.\n\nVessels: Normal.\n\nConclusion: Normal.", two, rec["lists"])[0] == \
        "Findings: Normal LV.\n\nVessels:\nValues not provided: LVEF.\nNormal.\n\nConclusion: Normal."


CMR = """## Report Structure
SECTION COMPARISON | header: none | role: comparison
SECTION LEFT VENTRICLE | header: "LEFT VENTRICLE" | role: findings
SECTION RIGHT VENTRICLE | header: "RIGHT VENTRICLE" | role: findings
SECTION ATRIA | header: "ATRIA" | role: findings
SECTION SUMMARY | header: "SUMMARY" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF" | "aortic root diameter"] AT TOP | section: LEFT VENTRICLE

## Paragraph: Left ventricle (LEFT VENTRICLE)
COVERS ["left ventricle"]
NORMAL [left ventricle] "Normal LV."
"""
CMR_REPORT = ("No previous CMR for comparison.\n\nLEFT VENTRICLE\nNormal LV.\n\nRIGHT VENTRICLE\nNormal RV.\n\n"
              "ATRIA\nNormal atria.\n\nSUMMARY\nNormal study.")


def test_a_report_wide_list_goes_at_the_top_of_the_body_never_under_the_first_findings_heading():
    """Browser test 2026-10-13: the line landed under "LEFT VENTRICLE". A report-wide list naming the default (first
    findings) section, as the analyser writes it, is not anchored there: it goes after the preamble line, before the
    first section heading."""
    _, rec = apply_required_values(CMR, ["aortic root diameter"])
    assert write_missing(CMR_REPORT, CMR, rec["lists"])[0] == (
        "No previous CMR for comparison.\n\nValues not provided: aortic root diameter.\n\nLEFT VENTRICLE\nNormal LV."
        "\n\nRIGHT VENTRICLE\nNormal RV.\n\nATRIA\nNormal atria.\n\nSUMMARY\nNormal study.")
    _, rec = apply_required_values(CMR.replace(" | section: LEFT VENTRICLE", ""), ["LVEF"])
    out = write_missing(CMR_REPORT, CMR.replace(" | section: LEFT VENTRICLE", ""), rec["lists"])[0]
    assert out.startswith("No previous CMR for comparison.\n\nValues not provided: LVEF.\n\nLEFT VENTRICLE\n")


def test_at_end_goes_after_the_last_findings_section_before_the_summary():
    end = CMR.replace("AT TOP", "AT END")
    _, rec = apply_required_values(end, ["LVEF"])
    assert write_missing(CMR_REPORT, end, rec["lists"])[0].endswith(
        "ATRIA\nNormal atria.\n\nValues not provided: LVEF.\n\nSUMMARY\nNormal study.")


def test_a_list_anchored_to_another_section_goes_at_the_top_of_that_section():
    anchored = CMR.replace("section: LEFT VENTRICLE", "section: ATRIA")
    _, rec = apply_required_values(anchored, ["LVEF"])
    assert "ATRIA\nValues not provided: LVEF.\nNormal atria." in write_missing(CMR_REPORT, anchored, rec["lists"])[0]


def test_a_report_without_a_preamble_starts_with_the_line():
    _, rec = apply_required_values(CMR, ["LVEF"])
    report = CMR_REPORT.split("\n\n", 1)[1]
    assert write_missing(report, CMR, rec["lists"])[0].startswith("Values not provided: LVEF.\n\nLEFT VENTRICLE\nNormal LV.")


# ── a value the confirm gate filled from the dictation (P3 2026-10-15: a captured value listed as not provided) ──
# SYNTHETIC: the writer dropped a dictated measurement; the gate had captured it with its sentence.

async def test_a_filled_value_the_report_lacks_is_flagged_but_never_listed_as_not_provided():
    _, rec = apply_required_values(SHEET, ["RVEF"])
    lists, flags, b = await backstop("Findings:\nNormal LV.", rec["lists"], ["LVEF"], ask=_scores([0.1]),
                                     list_missing=False)
    assert lists[0]["na"] == ["RVEF"]                      # only what the radiologist marked N/A
    assert [f["text"] for f in flags] == ["LVEF"] and b["missing"] == ["LVEF"]
    assert "LVEF" not in write_missing("Findings:\nNormal LV.", SHEET, lists)[0]


def test_restore_writes_the_dictated_sentence_at_the_end_of_its_region_section():
    from rapid_reports_ai.template_required_values import restore_values
    quotes = {"aortic root diameter": {"quote": "Aortic sinus measuring 41 mm.", "region": "ATRIA"}}
    out, edits, restored = restore_values(CMR_REPORT, CMR, ["aortic root diameter"], quotes)
    assert "ATRIA\nNormal atria. Aortic sinus measuring 41 mm.\n\nSUMMARY" in out
    assert edits == [{"type": "insertion", "sentence": "Aortic sinus measuring 41 mm."}]
    assert restored == ["aortic root diameter"]


def test_restore_without_a_matching_region_goes_at_the_end_of_the_findings():
    from rapid_reports_ai.template_required_values import restore_values
    quotes = {"LVEF": {"quote": "Ejection fraction 47%", "region": "Somewhere else"}}
    out, edits, _ = restore_values(CMR_REPORT, CMR, ["lvef"], quotes)
    assert "ATRIA\nNormal atria. Ejection fraction 47%.\n\nSUMMARY" in out
    assert edits == [{"type": "insertion", "sentence": "Ejection fraction 47%."}]
    # a report without headers: the end of the report's findings text
    out, _, _ = restore_values("Normal LV.", SHEET, ["LVEF"], quotes)
    assert out == "Normal LV. Ejection fraction 47%."


def test_restore_skips_a_sentence_already_in_the_report_and_an_item_without_a_quote():
    from rapid_reports_ai.template_required_values import restore_values
    report = CMR_REPORT.replace("Normal LV.", "Normal LV. Ejection fraction  47%.")
    quotes = {"LVEF": {"quote": "ejection fraction 47%.", "region": "LEFT VENTRICLE"},
              "aortic root diameter": {"quote": "", "region": ""}}
    out, edits, restored = restore_values(report, CMR, ["LVEF", "aortic root diameter"], quotes)
    assert out == report and edits == [] and restored == ["LVEF"]   # already there: nothing vanished


def test_restore_never_raises(monkeypatch):
    import rapid_reports_ai.template_required_values as M
    from rapid_reports_ai.template_required_values import restore_values

    def boom(*a, **k):
        raise RuntimeError("sections down")
    monkeypatch.setattr(M, "_clean", boom)
    monkeypatch.setattr("rapid_reports_ai.template_lean.report_sections", boom)
    out, edits, restored = restore_values(CMR_REPORT, CMR, ["LVEF"], {"LVEF": {"quote": "LVEF 47%.", "region": ""}})
    assert (out, edits, restored) == (CMR_REPORT, [], [])
