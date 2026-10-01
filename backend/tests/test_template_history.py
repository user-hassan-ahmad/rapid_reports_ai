from __future__ import annotations

import importlib

import pytest

from rapid_reports_ai import template_history as th
from rapid_reports_ai import report_review as rr
from rapid_reports_ai.report_review import ReportSection

SECTIONS = [ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            ReportSection(name="FINDINGS", header=None, role="findings"),
            ReportSection(name="IMPRESSION", header="Impression", role="impression")]
HISTORY = "67 year old female with right iliac fossa pain, raised CRP. Query appendicitis."


def test_provenance_accepts_a_terse_restatement():
    assert th.grounded("67F. Right iliac fossa pain. Raised CRP. ?Appendicitis.", HISTORY)


def test_provenance_rejects_added_facts():
    assert not th.grounded("67F. Right iliac fossa pain. Raised CRP. Previous appendicectomy.", HISTORY)
    assert not th.grounded("72F. Right iliac fossa pain.", HISTORY)


# The prompt's target form: the referrer's own words and abbreviations, connecting words dropped,
# age/sex as 67F, '?' for 'query', markers kept on their fact.
ACCEPT = [
    ("67F. RIF pain. ?Appendicitis.", "67 yo F, RIF pain ?appendicitis"),
    ("67F. RIF pain. ?Appendicitis.", "67 year old female with RIF pain. Query appendicitis."),
    ("54M. Chest pain 2/7. No fever. ?PE.", "54-year-old man, chest pain for 2/7, no fever. ?PE"),
    ("71F. Hx bowel cancer. Weight loss. ?Recurrence.", "71 year old lady. Hx bowel cancer, weight loss, ?recurrence"),
    ("History bowel cancer.", "Previous bowel cancer"),
    ("45M. Post-op day 3 with fever. ?Collection.", "45M post-op day 3 with fever, ?collection"),
    ("45M. Post-op day 3 fever. ?Collection.", "45M post-op day 3 with fever, ?collection"),
    ("60F. Back pain. No trauma.", "60 year old woman, back pain, no trauma"),
    ("Known Crohn's disease. Abdo pain 2/52. ?Stricture.", "Known Crohn's disease, abdo pain for 2/52, ?stricture"),
    ("67 y/o F. Pain.", "67 year old female, pain"),
    ("67 year old female. Pain.", "67F pain"),
    ("?PE or pneumonia.", "?PE or pneumonia"),
    ("D-dimer +ve. Troponin -ve.", "D-dimer +ve, troponin -ve"),
    ("Mass 3.5 cm.", "mass 3.5 cm, node 5.3 cm"),
    ("Appendicitis?", "RIF pain, appendicitis?"),
    ("RIF pain. ?Appendicitis.", "RIF pain ?appendicitis"),
    ("No fever. ?PE.", "no fever ?PE"),
    ("No fever and cough.", "no fever and cough"),
    ("67F. Pain.", "woman aged 67, pain"),
    ("67M. Pain.", "67 M, pain"),
    ("67F. Pain.", "67-year-old female, pain"),
    ("Pain 3 years.", "pain for 3 years"),
]


@pytest.mark.parametrize("text,history", ACCEPT)
def test_provenance_accepts_the_target_form(text, history):
    assert th.grounded(text, history), th._why_ungrounded(text, history)


# Meaning-changing restatements (reviewer probe classes). Each must fail, and so fall back to verbatim.
REJECT = [
    ("negation dropped", "60F. Chest pain.", "60 year old woman, no chest pain, dyspnoea"),
    ("query->fact", "67F. Appendicitis.", "67 year old female ?appendicitis"),
    ("postfix query->fact", "Appendicitis.", "RIF pain, appendicitis?"),
    ("fact->query", "67F. ?Appendicitis.", "67 year old female, known appendicitis"),
    ("decimal swap", "Mass 5.3 cm.", "mass 3.5 cm, node 5.3 cm"),
    ("number move", "Mass 5 cm. Node 3 cm.", "mass 3 cm, node 5 cm"),
    ("unit swap", "Mass 3 cm.", "mass 3 mm, previous 2 cm"),
    ("date swap", "Surgery 03/12.", "surgery 12/03, CT 03/12"),
    ("laterality swap", "Right leg pain. Left leg swelling.", "left leg pain, right leg swelling"),
    ("comparator flip", "CRP <100.", "CRP >100"),
    ("+ve/-ve flip", "D-dimer -ve.", "D-dimer +ve, troponin -ve"),
    ("sex via MR", "67M. Pain.", "67 year old, prior MR, pain"),
    ("sex via MS", "40F. Weakness.", "40 year old, MS, weakness"),
    ("sex via pronoun", "40M.", "40, patient says he fell? no - referral by partner"),
    ("sex via lone letter", "67F.", "67 year old, f/u pain"),
    ("sex swap", "60M.", "60 year old woman, husband present"),
    ("past via any hx", "Previous stroke.", "Hx diabetes. ?stroke"),
    ("age from other number", "3M. Pain.", "67 year old man, pain for 3 days"),
    ("age from other number 2", "40F.", "female, CRP 40"),
    ("not dropped", "Pain. Trauma.", "pain, not trauma"),
    ("without->with", "Pain with fever.", "pain without fever"),
    ("negation moved", "No fever. Cough.", "fever, no cough"),
    ("excluded->query", "?PE.", "PE excluded last week"),
    ("excluded dropped", "PE.", "PE excluded"),
    ("scope carries over or", "Fever.", "no pain or fever"),
    ("modifier cut off", "Pre-op.", "post-op day 3, pre-op CT normal"),
    ("added fact", "67F. RIF pain. Previous appendicectomy.", "67 yo F, RIF pain"),
    ("added acronym", "54M. Chest pain. AF.", "54 year old man, chest pain"),
    ("expanded abbreviation", "Right iliac fossa pain.", "RIF pain"),
    ("age words outside age", "Pain 3 years old.", "pain for 3 years"),
    # partial clauses: a tail or head dropped after/before a connective flips meaning (round 3 probe)
    ("partial clause", "Chest pain.", "chest pain and cough"),
    ("tail negation after connective", "Chest pain.", "chest pain is not present"),
    ("ruled out after was", "PE.", "PE was ruled out"),
    ("resolved after has", "Fever.", "fever has resolved"),
    ("unlikely after is", "PE.", "PE is unlikely"),
    ("family history", "History of breast cancer.", "family history of breast cancer"),
    ("mother had", "Stroke.", "mother had stroke"),
    ("wife has", "Cancer.", "wife has cancer"),
    ("risk of", "DVT.", "at risk of DVT"),
    ("concern for", "PE.", "concern for PE"),
    ("assess for", "Metastases.", "assess for metastases"),
    ("or scope: ?A or B -> B", "Pneumonia.", "?PE or pneumonia"),
    ("split at or", "?PE. Pneumonia.", "?PE or pneumonia"),
    ("split at or before marker", "?PE. ?Pneumonia.", "?PE or ?pneumonia"),
    ("and scope: no A and B -> B", "Cough.", "no fever and cough"),
    ("split at and", "No fever. Cough.", "no fever and cough"),
    ("or scope: no A or B -> B", "Cough.", "no fever or cough"),
    ("postfix across and", "Fever.", "fever and cough negative"),
    ("postfix ? across or", "Pneumonia.", "PE or pneumonia?"),
    ("split before postfix", "Troponin. Negative.", "troponin negative"),
    ("age from duration", "3M. Pain.", "man with pain for 3 years"),
    ("age from 'years ago'", "5 yo. Surgery.", "surgery 5 years ago"),
    ("age via 'o'", "2 yo.", "o/e 2 lesions"),
    ("sex outside age span", "67F. Pain.", "67 year old, female, pain"),
    ("known dropped", "Crohn's.", "known Crohn's"),
    ("possible dropped", "Fracture.", "possible fracture"),
    ("? suffix mid", "PE.", "PE? pneumonia"),
    ("unless", "Contrast.", "unless contrast allergy"),
    ("rather than", "Pneumonia.", "infection rather than pneumonia"),
    ("if", "Mass.", "if mass seen"),
    ("was on", "Warfarin.", "was previously on warfarin"),
    ("stopped", "Warfarin.", "warfarin stopped"),
    ("age skip joins facts", "Pain swelling.", "pain 67 years swelling"),
    ("negative after was", "Troponin.", "troponin was negative"),
    ("not after fact", "Fracture.", "fracture not seen"),
    ("no evidence", "Evidence of DVT.", "no evidence of DVT"),
    ("denied", "Chest pain.", "denied chest pain"),
    ("absent", "Pulses.", "pulses absent"),
    ("normal dropped", "CT.", "CT was normal"),
]


@pytest.mark.parametrize("name,text,history", REJECT, ids=[r[0] for r in REJECT])
def test_provenance_rejects_meaning_changes(name, text, history):
    assert not th.grounded(text, history)


@pytest.fixture
def restate(monkeypatch):
    """Restatement on, via the real env switch (module re-read), restored afterwards."""
    monkeypatch.setenv("RR_HISTORY_RESTATE", "1")
    importlib.reload(th)
    assert th.RESTATE
    yield
    monkeypatch.delenv("RR_HISTORY_RESTATE")
    importlib.reload(th)
    assert not th.RESTATE


async def test_default_is_verbatim_without_a_model_call(monkeypatch):
    assert not th.RESTATE

    async def boom(**kw):
        raise AssertionError("no model call by default")
    monkeypatch.setattr(th, "_run_agent_with_model", boom)
    assert await th.write_history("  67 year old   female\n\n RIF pain ?appendicitis ") == \
        ("67 year old female\nRIF pain ?appendicitis", "verbatim")
    assert await th.write_history(" \n ") is None


def _fake_agent(text):
    class R:
        class output:
            pass
    R.output.text = text

    async def fake(**kw):
        return R
    return fake


@pytest.mark.parametrize("name,text,history", REJECT, ids=[r[0] for r in REJECT])
async def test_rejected_restatements_fall_back_to_verbatim(restate, monkeypatch, name, text, history):
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent(text))
    assert await th.write_history(history) == (history, "verbatim")


async def test_write_history_returns_grounded_text(restate, monkeypatch):
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent(" 67F. Right iliac fossa pain. ?Appendicitis. "))
    assert await th.write_history(HISTORY) == ("67F. Right iliac fossa pain. ?Appendicitis.", "restated")


async def test_write_history_falls_back_on_failure_or_empty_and_tidies(restate, monkeypatch):
    messy = "  67 year old   female\n\n\n  RIF pain \t ?appendicitis  "
    tidy = "67 year old female\nRIF pain ?appendicitis"

    async def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(th, "_run_agent_with_model", boom)
    assert await th.write_history(messy) == (tidy, "verbatim")
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent("  "))
    assert await th.write_history(messy) == (tidy, "verbatim")


async def test_write_history_empty_input_is_none(monkeypatch):
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent("67F."))
    assert await th.write_history("  \n ") is None


async def test_ungrounded_restatement_logs_the_failing_fragment(restate, monkeypatch):
    logged = []
    monkeypatch.setattr(th.logger, "warning", lambda msg, *a: logged.append(msg % a))
    monkeypatch.setattr(th, "_run_agent_with_model", _fake_agent("67F. Chest pain."))
    await th.write_history("67 year old woman, no chest pain")
    assert any("'Chest pain'" in m for m in logged)


# --------------------------------------------------------------------------------------- placement

def test_insert_puts_the_section_first_when_findings_are_implicit():
    report = "The appendix is dilated.\n\nImpression\nAppendicitis."
    out = th.insert_history(report, "67F. ?Appendicitis.", SECTIONS)
    assert out.startswith("CLINICAL HISTORY\n67F. ?Appendicitis.\n\nThe appendix is dilated.")


def test_insert_goes_before_the_next_present_header():
    secs = [ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"), SECTIONS[0],
            ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "TECHNIQUE\nCT.\n\nFINDINGS\nX."
    assert th.insert_history(report, "67F.", secs) == "TECHNIQUE\nCT.\n\nCLINICAL HISTORY\n67F.\n\nFINDINGS\nX."


EXPLICIT = [ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            ReportSection(name="FINDINGS", header="FINDINGS", role="findings"),
            ReportSection(name="IMPRESSION", header="IMPRESSION", role="impression")]


def test_insert_without_a_history_section_leaves_the_report_unchanged():
    assert th.insert_history("FINDINGS\nX.", "67F.", EXPLICIT[1:]) == "FINDINGS\nX."


def test_insert_replaces_a_generator_written_block():
    report = "CLINICAL HISTORY\n67 year old with pain and a guess.\n\nFINDINGS\nX.\n\nIMPRESSION\nY."
    assert th.insert_history(report, "67F.", EXPLICIT) == "CLINICAL HISTORY\n67F.\n\nFINDINGS\nX.\n\nIMPRESSION\nY."


def test_insert_places_before_inline_headers():
    out = th.insert_history("FINDINGS: X.\n\nIMPRESSION: Y.", "67F.", EXPLICIT)
    assert out == "CLINICAL HISTORY\n67F.\n\nFINDINGS: X.\n\nIMPRESSION: Y."


def test_insert_does_not_treat_prose_as_a_header():
    secs = [EXPLICIT[0], EXPLICIT[2]]
    report = "Findings of note are minor.\n\nIMPRESSION\nY."
    assert th.insert_history(report, "67F.", secs) == "Findings of note are minor.\n\nCLINICAL HISTORY\n67F.\n\nIMPRESSION\nY."


def test_insert_appends_when_the_history_section_is_last():
    secs = [EXPLICIT[1], EXPLICIT[2], EXPLICIT[0]]
    assert th.insert_history("FINDINGS\nX.\n\nIMPRESSION\nY.", "67F.", secs) == \
        "FINDINGS\nX.\n\nIMPRESSION\nY.\n\nCLINICAL HISTORY\n67F.\n"


HIST_LAST_OF_TWO = [ReportSection(name="CLINICAL HISTORY", header="History", role="history"),
                    ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]


def test_insert_keeps_inline_history_text_inside_findings():
    report = "FINDINGS\nLiver normal.\nHistory: nil.\nSpleen normal."
    assert th.insert_history(report, "67F.", HIST_LAST_OF_TWO) == \
        "History\n67F.\n\nFINDINGS\nLiver normal.\nHistory: nil.\nSpleen normal."


def test_insert_keeps_a_standalone_history_line_out_of_place():
    report = "FINDINGS\nLiver normal.\nHistory\nSpleen normal."
    out = th.insert_history(report, "67F.", HIST_LAST_OF_TWO)
    assert out.endswith("FINDINGS\nLiver normal.\nHistory\nSpleen normal.")


def test_insert_keeps_text_when_the_block_end_is_unsure():
    # next section implicit and no paragraph break: nothing is removed
    report = "CLINICAL HISTORY\nPain.\nThe appendix is dilated.\n\nImpression\nAppendicitis."
    out = th.insert_history(report, "67F.", SECTIONS)
    assert "The appendix is dilated." in out


def test_insert_removes_a_generator_block_before_implicit_findings():
    report = "CLINICAL HISTORY\nPain, query appendicitis.\n\nThe appendix is dilated.\n\nImpression\nAppendicitis."
    assert th.insert_history(report, "67F.", SECTIONS) == \
        "CLINICAL HISTORY\n67F.\n\nThe appendix is dilated.\n\nImpression\nAppendicitis."


@pytest.mark.parametrize("secs,report", [
    (EXPLICIT, "FINDINGS\nX.\n\nIMPRESSION\nY."),
    (EXPLICIT, "FINDINGS: X.\n\nIMPRESSION: Y."),
    (SECTIONS, "The appendix is dilated.\n\nImpression\nAppendicitis."),
    ([EXPLICIT[1], EXPLICIT[2], EXPLICIT[0]], "FINDINGS\nX.\n\nIMPRESSION\nY."),
])
def test_insert_is_idempotent(secs, report):
    text = "Previous CT.\nImpression: stable nodule.\n?progression"
    once = th.insert_history(report, text, secs)
    assert th.insert_history(once, text, secs) == once


PRIOR_REPORT_HISTORY = "Previous CT report:\nFINDINGS\nNodule 5 mm.\nIMPRESSION\nStable.\n?progression"


def test_history_lines_that_read_as_headers_are_folded():
    out = th.insert_history("FINDINGS\nNew 8 mm nodule.\n\nIMPRESSION\nProgression.", PRIOR_REPORT_HISTORY, EXPLICIT)
    assert out == ("CLINICAL HISTORY\nPrevious CT report:\nFINDINGS \u2013 Nodule 5 mm.\nIMPRESSION \u2013 Stable.\n?progression"
                   "\n\nFINDINGS\nNew 8 mm nodule.\n\nIMPRESSION\nProgression.")
    spans = {s.name: out[a:b].strip() for s, a, b in rr.section_spans(out, EXPLICIT)}
    assert spans == {"CLINICAL HISTORY": "Previous CT report:\nFINDINGS \u2013 Nodule 5 mm.\nIMPRESSION \u2013 Stable.\n?progression",
                     "FINDINGS": "New 8 mm nodule.", "IMPRESSION": "Progression."}
    assert th.insert_history(out, PRIOR_REPORT_HISTORY, EXPLICIT) == out


def test_a_trailing_header_line_in_the_history_ends_with_a_full_stop():
    out = th.insert_history("FINDINGS\nX.", "Pain.\nImpression", EXPLICIT)
    assert out == "CLINICAL HISTORY\nPain.\nImpression.\n\nFINDINGS\nX."
    assert [s.name for s, _, _ in rr.section_spans(out, EXPLICIT)] == ["CLINICAL HISTORY", "FINDINGS"]


def test_folded_history_is_safe_in_an_inline_header_report():
    report = "FINDINGS: New 8 mm nodule.\n\nIMPRESSION: Progression."
    out = th.insert_history(report, PRIOR_REPORT_HISTORY, EXPLICIT)
    assert out == ("CLINICAL HISTORY\nPrevious CT report:\nFINDINGS \u2013 Nodule 5 mm.\nIMPRESSION \u2013 Stable.\n?progression"
                   "\n\nFINDINGS: New 8 mm nodule.\n\nIMPRESSION: Progression.")
    spans = {s.name: out[a:b].strip() for s, a, b in rr.section_spans(out, EXPLICIT)}
    assert spans == {"CLINICAL HISTORY": "Previous CT report:\nFINDINGS \u2013 Nodule 5 mm.\nIMPRESSION \u2013 Stable.\n?progression",
                     "FINDINGS": "New 8 mm nodule.", "IMPRESSION": "Progression."}
    assert th.insert_history(out, PRIOR_REPORT_HISTORY, EXPLICIT) == out
