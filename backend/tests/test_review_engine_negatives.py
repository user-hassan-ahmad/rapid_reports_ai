# tests/test_review_engine_negatives.py
"""Negatives classifier (Plan 2 Task 14): routing per label, code-only removal (correction 12), fail-soft model
failure, recommendations excluded, anchors after several removals, number detection. Synthetic cases only."""
import pytest

from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine import negatives as neg
from rapid_reports_ai.review_engine import verifier
from rapid_reports_ai.review_engine.items import ReviewInput, item_key, text_hash

REPORT = """FINDINGS:
There is a 3 cm mass in the pancreatic head. No pneumoperitoneum. The common bile duct is dilated. No pleural effusion. No ascites, lymphadenopathy or bowel obstruction. The liver is normal. The spleen measures 14 cm and is otherwise normal. No focal lesion in the 4cm kidney. The T1 vertebra is intact.

IMPRESSION:
Pancreatic head mass. No metastatic disease. Recommend MRI for further characterisation, no contrast allergy noted.
"""
DICTATION = "3 cm pancreatic head mass. Free gas under the diaphragm. Dilated CBD. Ascites present. No pleural effusion."
CLAUSES = ["No pneumoperitoneum.", "No pleural effusion.", "No ascites", "No lymphadenopathy or bowel obstruction", "The liver is normal.",
           "The spleen measures 14 cm and is otherwise normal.", "No focal lesion in the 4cm kidney.",
           "The T1 vertebra is intact.", "No metastatic disease."]


def inp(report=REPORT, dictation=DICTATION, history=""):
    art = GenerationArtifacts(report=report, dictated_findings=dictation, sections=quick_section_names(report),
                              options=[], brief=None, quality_check=None)
    return ReviewInput(report_id="00000000-0000-0000-0000-000000000001", pathway="quick", artifacts=art,
                       clinical_history=history, scan_type="CT abdomen")


def model(labels, calls=None):
    class R:
        pass

    async def fake(**kw):
        if calls is not None:
            calls.append(kw)
        r = R()
        r.output = neg.Labels(labels=labels)
        return r
    return fake


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(**kw):
        raise AssertionError("unstubbed model call")
    monkeypatch.setattr(neg, "_run_agent_with_model", boom)


LABELS = ["1 | contradicted | Free gas under the diaphragm | no", "2 | dictated | No pleural effusion | no",
          "3 | contradicted | Ascites present | no", "4 | implicated | pancreatic head mass | no",
          "5 | default | - | no", "6 | default | - | yes", "7 | default | - | yes", "8 | default | - | no",
          "9 | contradicted | pancreatic head mass | no"]


# ── candidates and code checks ───────────────────────────────────────────────

def test_candidates_exclude_recommendations():
    got = [c["clause"] for c in neg.candidates(REPORT)]
    assert got == CLAUSES
    assert not any("Recommend" in c for c in got)


def test_number_detection_glued_units_and_level_names():
    assert neg.code_number_flag("No focal lesion in the 4cm kidney.", DICTATION, "")
    assert neg.code_number_flag("The spleen measures 14 cm.", DICTATION, "")
    assert not neg.code_number_flag("The T1 vertebra is intact.", DICTATION, "")
    assert not neg.code_number_flag("No fracture at C7 or L4/5.", DICTATION, "")
    assert not neg.code_number_flag("Mass is 3 cm.", DICTATION, "")             # dictated number
    assert not neg.code_number_flag("Stable since 2019.", "", "Prior scan 2019")  # in history
    assert neg.undictated_numbers("No focal lesion in the 4cm kidney.", DICTATION, "") == "4cm"


def test_parse_labels_and_flat_schema():
    assert all(f.annotation not in (dict,) for f in neg.Labels.model_fields.values())
    assert neg.Labels(labels='["1 | default | - | no"]').labels == ["1 | default | - | no"]
    got = neg.parse_labels(["1 | Default | - | no", "2 | implicated | mass | yes", "9 | default", "x | default",
                            "3 | maybe | - | no"], 3)
    assert got == {1: {"cls": "default", "pointer": "", "number": False},
                   2: {"cls": "implicated", "pointer": "mass", "number": True}}


def test_prompt_is_verbatim_lab_copy():
    from rapid_reports_ai import enhancement_utils as eu
    from pathlib import Path
    lab = Path(eu.__file__).parent / "scripts" / "review_labs" / "prompts" / "negatives_v5.txt"
    assert neg.prompt() == lab.read_text().strip()


# ── routing ──────────────────────────────────────────────────────────────────

async def test_routing_per_label(monkeypatch):
    calls = []
    monkeypatch.setattr(neg, "_run_agent_with_model", model(LABELS, calls))
    items, log = await neg.classify_negatives(inp(), "run-1")
    assert calls and calls[0]["retries"] == 0 and calls[0]["output_type"] is neg.Labels
    assert "STATEMENTS TO CLASSIFY:\n1. No pneumoperitoneum.\n2. No pleural effusion." in calls[0]["user_prompt"]
    by = {it.evidence["clause"]: it for it in items}
    assert "No pleural effusion." not in by                                   # dictated: no item
    pn = by["No pneumoperitoneum."]                                          # whole generated negative sentence
    assert (pn.kind, pn.status, pn.cls, pn.edit.mode, pn.edit.find) == \
        ("removed", "pre_applied", "action", "remove", "No pneumoperitoneum.")
    assert pn.evidence["removal_reason"] == "contradicted" and pn.evidence["removed_text"] == "No pneumoperitoneum."
    asc = by["No ascites"]                       # first item of a list: verifier refuses (partial_remove) → conflict
    assert (asc.kind, asc.status, asc.cls, asc.evidence["check_reason"], asc.evidence["pointer"]) == \
        ("check", "open", "action", "conflict", "Ascites present")
    imp = by["No lymphadenopathy or bowel obstruction"]
    assert (imp.kind, imp.status, imp.evidence["check_reason"], imp.evidence["pointer"]) == \
        ("check", "open", "uncertain", "pancreatic head mass")
    assert (by["The liver is normal."].kind, by["The liver is normal."].cls) == ("assumed_normal", "info")
    sp = by["The spleen measures 14 cm and is otherwise normal."]           # positive text: not removable
    assert (sp.kind, sp.status, sp.evidence["check_reason"], sp.evidence["pointer"]) == ("check", "open", "number", "14 cm")
    kid = by["No focal lesion in the 4cm kidney."]     # a number is never "negative-only" for the verifier → check
    assert (kid.kind, kid.status, kid.evidence["check_reason"], kid.evidence["pointer"]) == \
        ("check", "open", "number", "4cm")
    assert by["The T1 vertebra is intact."].kind == "assumed_normal"
    assert by["No metastatic disease."].kind == "removed"
    assert by["The liver is normal."].section == "FINDINGS" and by["No metastatic disease."].section == "IMPRESSION"
    for it in items:
        assert it.lane == "accuracy" and it.detectors == ["negatives.v5"] and it.run_id == "run-1"
        assert it.key == item_key("accuracy", "negative", it.evidence["clause"])
    assert "No pneumoperitoneum" not in log["report"] and "No metastatic disease" not in log["report"]
    assert "No ascites, lymphadenopathy" in log["report"] and "4cm kidney" in log["report"]
    assert log["text_hash"] == text_hash(log["report"]) and log["error"] is None


async def test_keys_stable_when_label_flips(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["5 | default | - | no"]))
    a, _ = await neg.classify_negatives(inp(), "r1")
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["5 | implicated | mass | no"]))
    b, _ = await neg.classify_negatives(inp(), "r2")
    ka = {it.evidence["clause"]: it.key for it in a}
    kb = {it.evidence["clause"]: it.key for it in b}
    assert ka["The liver is normal."] == kb["The liver is normal."]


async def test_number_in_dictated_sentence_is_check_never_removed(monkeypatch):
    report = "FINDINGS:\nThe aorta is normal in calibre at 21 mm. No free fluid.\n\nIMPRESSION:\nNo acute abnormality.\n"
    dictation = "Normal calibre aorta. No free fluid. No acute abnormality."
    monkeypatch.setattr(neg, "_run_agent_with_model", model(
        ["1 | dictated | Normal calibre aorta | yes", "2 | dictated | No free fluid | no",
         "3 | dictated | No acute abnormality | no"]))
    items, log = await neg.classify_negatives(inp(report, dictation), "r")
    assert len(items) == 1
    it = items[0]
    assert (it.kind, it.status, it.evidence["check_reason"], it.evidence["pointer"]) == ("check", "open", "number", "21 mm")
    assert it.edit is None and log["report"] == report


async def test_validation_failure_is_fail_soft(monkeypatch):
    async def bad(**kw):
        class UnexpectedModelBehavior(Exception):
            pass
        raise UnexpectedModelBehavior("Exceeded maximum retries (0) for output validation")
    monkeypatch.setattr(neg, "_run_agent_with_model", bad)
    items, log = await neg.classify_negatives(inp(), "r")
    assert log["error_kind"] == "validation" and log["error"]
    assert log["report"] == REPORT                                           # nothing removed
    assert all(it.status == "open" for it in items)
    kinds = {it.evidence["clause"]: it.kind for it in items}
    # unlabelled = default: assumed normal; only the code number check still raises a check
    assert {k for k, v in kinds.items() if v != "assumed_normal"} == \
        {"The spleen measures 14 cm and is otherwise normal.", "No focal lesion in the 4cm kidney."}
    assert kinds["No pleural effusion."] == "assumed_normal" and kinds["No metastatic disease."] == "assumed_normal"


async def test_transport_failure_is_fail_soft(monkeypatch):
    async def down(**kw):
        raise ConnectionError("cerebras down")
    monkeypatch.setattr(neg, "_run_agent_with_model", down)
    items, log = await neg.classify_negatives(inp(), "r")
    assert log["error_kind"] == "transport"
    assert not any(it.kind == "removed" for it in items)


async def test_no_candidates_no_call():
    report = "FINDINGS:\nThere is a 3 cm mass.\n\nIMPRESSION:\nMass. Recommend follow-up, no contrast.\n"
    items, log = await neg.classify_negatives(inp(report, "3 cm mass."), "r")   # the boom fixture is not hit
    assert items == [] and log["candidates"] == 0


# ── correction 12: code-built removal only ──────────────────────────────────

async def test_contradicted_not_code_removable_is_conflict_check(monkeypatch):
    # The contradicted statement shares its sentence with positive text: code cannot remove it cleanly.
    report = "FINDINGS:\nThe gallbladder is normal and contains a 9 mm polyp.\n\nIMPRESSION:\nGallbladder polyp.\n"
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["1 | contradicted | gallbladder wall thickening | no"]))
    items, log = await neg.classify_negatives(inp(report, "9 mm gallbladder polyp. Gallbladder wall thickening."), "r")
    assert len(items) == 1
    it = items[0]
    assert (it.kind, it.status, it.cls, it.evidence["check_reason"]) == ("check", "open", "action", "conflict")
    assert it.edit is None and log["report"] == report


async def test_removal_blocked_when_preapply_fails(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["9 | contradicted | mass | no"]))
    seen = []

    def refuse(report, edit, kind, dictation, **kw):
        seen.append((kind, kw.get("code_built")))
        return ["not_negative_only"]
    monkeypatch.setattr(verifier, "preapply_failures", refuse)
    items, log = await neg.classify_negatives(inp(), "r")
    it = next(i for i in items if i.evidence["clause"] == "No metastatic disease.")
    assert (it.kind, it.status, it.evidence["check_reason"]) == ("check", "open", "conflict")
    assert ("removed", True) in seen and log["report"] == REPORT


async def test_removal_passes_preapply(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["9 | contradicted | mass | no"]))
    items, log = await neg.classify_negatives(inp(), "r")
    it = next(i for i in items if i.evidence["clause"] == "No metastatic disease.")
    assert verifier.preapply_failures(REPORT, it.edit, "removed", DICTATION, code_built=True,
                                      sections=quick_section_names(REPORT)) == []
    assert it.status == "pre_applied" and it.verified["code"] is True
    assert verifier.apply_edit(REPORT, it.edit, quick_section_names(REPORT)) == log["report"]


def test_removal_edit_is_pure_code_deletion():
    e = neg.removal_edit(REPORT, "No ascites")
    assert e.mode == "remove" and e.find in REPORT and REPORT.count(e.find) == 1
    assert neg.removal_edit(REPORT, "The spleen is absent") is None


# ── anchors after several removals ───────────────────────────────────────────
# Every anchor is on the ORIGINAL report (what the user sees in shadow); post-removal positions live in the log.

async def test_anchors_on_original_after_several_removals(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(LABELS))
    items, log = await neg.classify_negatives(inp(), "r")
    doc = log["report"]
    removed = [it for it in items if it.kind == "removed"]
    assert len(removed) == 2
    for it in items:
        assert it.anchor is not None and it.anchor.text_hash == text_hash(REPORT)
        assert REPORT[it.anchor.start:it.anchor.end] == it.anchor.text
    for it in removed:                       # the removed clause's own original span
        assert it.anchor.text == it.evidence["removed_text"]
        assert REPORT.count(it.edit.find) == 1          # the edit applies on the text the user sees
    # replaying the edits in item order on the original reproduces the post-removal report
    cur = REPORT
    for it in removed:
        cur = verifier.apply_edit(cur, it.edit, quick_section_names(REPORT))
    assert cur == doc
    # post-removal positions (log only): checks span their text in doc; a removal is zero-width where it was
    post = log["post_removal_anchors"]
    assert set(post) == {it.id for it in items}
    for it in items:
        a, b = post[it.id]
        if it.kind == "removed":
            before = REPORT[:it.anchor.start].rstrip()
            assert a == b and doc[:a].rstrip().endswith(before[-25:])
        else:
            assert doc[a:b] == it.anchor.text


async def test_removed_anchor_is_original_span_whatever_the_order(monkeypatch):
    # Removal order is candidate order; the IMPRESSION-side-first listing must still give original spans.
    report = "FINDINGS:\nMass in the liver. No pneumoperitoneum. No splenic lesion.\n\nIMPRESSION:\nLiver mass.\n"
    monkeypatch.setattr(neg, "candidates", lambda r: [{"clause": "No splenic lesion.", "before": ""},
                                                      {"clause": "No pneumoperitoneum.", "before": ""}])
    monkeypatch.setattr(neg, "_run_agent_with_model", model(["1 | contradicted | spleen | no",
                                                             "2 | contradicted | free gas | no"]))
    items, log = await neg.classify_negatives(inp(report, "Mass in the liver. Free gas. Splenic lesion."), "r")
    doc = log["report"]
    assert doc == "FINDINGS:\nMass in the liver.\n\nIMPRESSION:\nLiver mass.\n"
    for it in items:
        assert it.kind == "removed" and report[it.anchor.start:it.anchor.end] == it.evidence["removed_text"]
        a, b = log["post_removal_anchors"][it.id]
        assert a == b and doc[:a].rstrip().endswith("Mass in the liver.")


async def test_model_failure_number_clause_is_check_number(monkeypatch):
    """A number is never negative-only for the verifier, so a number-flagged clause is always a check item."""
    report = "FINDINGS:\nA 14 mm left renal cyst. No lymph nodes larger than 10 mm.\nIMPRESSION:\nLeft renal cyst."

    async def down(**kw):
        raise ConnectionError("down")
    monkeypatch.setattr(neg, "_run_agent_with_model", down)
    items, log = await neg.classify_negatives(inp(report, "- 14 mm left renal cyst"), "r")
    assert [(i.kind, i.status, i.evidence["check_reason"]) for i in items] == [("check", "open", "number")]
    assert log["report"] == report


async def test_items_carry_history(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(LABELS))
    items, _ = await neg.classify_negatives(inp(), "r")
    for it in items:
        assert it.history[0]["event"] == "created" and it.history[0]["text_hash"] == text_hash(REPORT)
        if it.kind == "removed":
            assert it.history[-1]["event"] == "pre_applied" and it.history[-1]["text_hash"]
            assert it.verified == {"code": True, "failed": [], "addressed": None, "contra": None,
                                   "unconfirmed": False, "preapply_failures": []}


# ── brief-owned statements are not re-classified (prod d3d1e0a5: 7 of 16 statements already labelled) ────────────

def _term_span(report, sentence, term):
    i = report.index(sentence) + sentence.index(term)
    return (i, i + len(term))


async def test_brief_owned_statements_skip_the_classifier(monkeypatch):
    """A candidate whose span holds a brief linked-normal label is routed unlabelled (the brief's item owns it); only
    the rest are listed for the model, numbered contiguously, and its labels map back to the right statements."""
    owned = [_term_span(REPORT, "The liver is normal.", "liver"),
             _term_span(REPORT, "The spleen measures 14 cm", "spleen")]
    calls = []
    monkeypatch.setattr(neg, "_run_agent_with_model", model(
        ["1 | contradicted | Free gas under the diaphragm | no", "6 | implicated | pancreatic head mass | no"], calls))
    items, log = await neg.classify_negatives(inp(), "r", owned=owned)
    listing = calls[0]["user_prompt"].split("STATEMENTS TO CLASSIFY:\n", 1)[1]
    assert "The liver is normal." not in listing and "The spleen measures" not in listing
    assert listing.splitlines()[4] == "5. No focal lesion in the 4cm kidney."
    assert (log["candidates"], log["owned_by_brief"], log["classified"]) == (9, 2, 7)
    by = {it.evidence["clause"]: it for it in items}
    assert by["No pneumoperitoneum."].kind == "removed"
    assert by["The T1 vertebra is intact."].evidence["check_reason"] == "uncertain"   # classified 6 → candidate 8
    assert by["The liver is normal."].kind == "assumed_normal"                        # deduped later by the brief
    sp = by["The spleen measures 14 cm and is otherwise normal."]                      # the number check is code
    assert (sp.kind, sp.evidence["check_reason"]) == ("check", "number")
    assert set(log["labels"]) == {"1", "8"}


async def test_all_candidates_owned_makes_no_model_call():
    report = "FINDINGS:\nA 2 cm renal cyst. The liver is normal. No ascites.\n\nIMPRESSION:\nRenal cyst.\n"
    owned = [_term_span(report, "The liver is normal.", "liver"), _term_span(report, "No ascites.", "ascites")]
    items, log = await neg.classify_negatives(inp(report, "Liver normal."), "r", owned=owned)  # boom not hit
    assert log["classified"] == 0 and log["owned_by_brief"] == 2 and log["error"] is None
    assert items and all(it.kind == "assumed_normal" for it in items)


# ── evidence.form: the statement's grammatical form for the rail's AI layer ──────────────────────────────────────

@pytest.mark.parametrize("clause,form", [
    ("No pleural effusion.", "negative"), ("There is no free fluid.", "negative"), ("Nil acute fracture.", "negative"),
    ("Without hydronephrosis.", "negative"), ("Free fluid is absent.", "negative"),
    ("The liver shows no focal lesion.", "negative"), ("No lymphadenopathy or bowel obstruction", "negative"),
    ("The liver is unremarkable.", "normal"), ("The great vessels are patent.", "normal"),
    ("The ribs are intact.", "normal"), ("The lungs are clear.", "normal"),
    ("The heart and pericardium are unremarkable with no pericardial effusion.", "normal"),
    ("The spleen measures 14 cm and is otherwise normal.", "normal"), ("The bowel is not dilated.", "normal"),
])
def test_statement_form(clause, form):
    from rapid_reports_ai.review_engine.jev_pass import statement_form
    assert statement_form(clause) == form


async def test_negatives_items_carry_their_form(monkeypatch):
    monkeypatch.setattr(neg, "_run_agent_with_model", model(LABELS))
    items, _ = await neg.classify_negatives(inp(), "r")
    by = {it.evidence["clause"]: it for it in items}
    assert by["The liver is normal."].evidence["form"] == "normal"
    assert by["No lymphadenopathy or bowel obstruction"].evidence["form"] == "negative"
    assert by["No ascites"].evidence["form"] == "negative"                      # a conflict check
    assert by["The spleen measures 14 cm and is otherwise normal."].evidence["form"] == "normal"
    for it in items:
        assert it.kind not in ("assumed_normal", "check") or it.evidence["form"] in ("negative", "normal")
