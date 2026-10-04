"""Review engine item contract and merge (spec §6.1, §7, §10.1)."""
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.review_engine.items import (Candidate, Edit, ReviewInput, ReviewItem, Span, item_key, merge,
                                                  text_hash)


def C(kind="partial", lane="coverage", anchor=None, line_id=None, detector="d"):
    span = Span(start=anchor[0], end=anchor[1], text="x") if anchor else None
    return Candidate(lane=lane, kind=kind, anchor=span, line_id=line_id, detector=detector)


def test_item_key_is_stable_and_normalised():
    assert item_key("coverage", "partial", "A  cyst.") == item_key("coverage", "partial", "a cyst.")
    assert item_key("coverage", "partial", "a cyst") != item_key("accuracy", "partial", "a cyst")
    assert len(item_key("a", "b", "c")) == 16


def test_text_hash():
    assert text_hash("abc") == text_hash("abc") and len(text_hash("abc")) == 16 and text_hash("abc") != text_hash("abd")


def test_merge_by_overlapping_anchor_and_shared_line():
    a = C(anchor=(0, 10))
    b = C(anchor=(5, 15), lane="accuracy", kind="unsupported", detector="code.numbers")
    c = C(line_id="d3")
    d = C(line_id="d3", kind="laterality", detector="code.laterality")
    e = C(anchor=(20, 30))
    groups = merge([a, b, c, d, e])
    assert [len(g) for g in groups] == [2, 2, 1]
    assert groups[0][0] is a and groups[1][0] is c and groups[2][0] is e


def test_merge_is_transitive():
    a, b, c = C(anchor=(0, 5)), C(anchor=(4, 9), line_id="d1"), C(line_id="d1")
    assert len(merge([a, b, c])) == 1


def test_touching_spans_do_not_merge():
    assert len(merge([C(anchor=(0, 5)), C(anchor=(5, 9))])) == 2


def test_review_item_defaults():
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="coverage", kind="partial", cls="minor")
    assert it.status == "open" and it.history == [] and len(it.id) == 36 and it.edit is None


def test_edit_insert_without_anchor_means_append():
    e = Edit(mode="insert", replace="x", section="IMPRESSION")
    assert e.after is None


def test_review_input_shape():
    art = GenerationArtifacts(report="R", dictated_findings="D", sections=["FINDINGS"], options=[])
    inp = ReviewInput(report_id="r1", pathway="quick", artifacts=art, clinical_history="", scan_type="CT")
    assert inp.synthesis is None and inp.pre_edit_report is None
