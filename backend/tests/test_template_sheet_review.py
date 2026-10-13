"""Style-step sheet checks (Rules-step spec, step 5)."""
import httpx

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_review as V
from tests.template_sheet_fixtures import LEDGER_SHEET


def _st(sheet=LEDGER_SHEET):
    return tsg.parse_sheet(sheet).structure


def _jev(score):
    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        return httpx.Response(200, json={"answers": {k: {"noul": score} for k in qs}})
    return httpx.MockTransport(handler)


def test_fixed_candidates_skip_targeted_and_decided_lines():
    assert V.fixed_candidates(_st(), []) == ["Axial images were acquired.", "No previous imaging available."]
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    assert V.fixed_candidates(_st(sheet), led) == ["Axial images were acquired."]     # the default has its rule
    led2, _ = td.set_decision([], "fixed", "Axial images were acquired.", {"keep": "always"}, source="creation")
    assert V.fixed_candidates(_st(), led2) == ["No previous imaging available."]


def test_an_undecided_concepts_default_is_still_checked():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\nRULE WHEN [context: the dictation names a previous imaging study for '
        'comparison] REPLACE "No previous imaging available." WITH "Compared with {date}."\n')
    assert "No previous imaging available." in V.fixed_candidates(_st(sheet), [])   # polarity stays checkable


async def test_the_absence_backstop_skips_a_line_a_context_rule_targets():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\nRULE WHEN [context: the dictation names a previous imaging study for '
        'comparison] REPLACE "No previous imaging available." WITH "Compared with {date}."\n')
    assert await V.fixed_flags(_st(sheet), [], transport=_jev(0.1)) == []
    assert await V.fixed_flags(_st(sheet), [], transport=_jev(0.9)) == ["Axial images were acquired.",
                                                                         "No previous imaging available."]


async def test_absence_worded_lines_are_flagged_by_code_the_rest_by_jev():
    assert await V.fixed_flags(_st(), [], transport=_jev(0.1)) == ["No previous imaging available."]
    assert await V.fixed_flags(_st(), [], transport=_jev(0.9)) == ["Axial images were acquired.",
                                                                    "No previous imaging available."]


def test_the_normal_report_is_built_in_section_and_sheet_order():
    rep = V.normal_report(LEDGER_SHEET, _st())
    assert rep == [{"section": "FINDINGS", "header": "Findings:", "sentences": [
        {"key": "Liver :: liver", "text": "The liver is normal in size.", "kind": "normal", "paragraph": "Liver"},
        {"key": 'Liver :: "No focal liver lesion."', "text": "No focal liver lesion.", "kind": "negative",
         "paragraph": "Liver"}]}]


def test_uncovered_lists_covered_structures_without_a_normal():
    assert [(c["title"], c["key"]) for c in V.uncovered(_st())] == [("Liver: gallbladder", "Liver :: gallbladder")]


async def test_sheet_checks_is_fail_soft_and_reports_unmatched_entries():
    led, _ = td.set_decision([], "normal", "Spleen :: spleen", {"text": "The spleen is normal."}, source="creation")
    out = await V.sheet_checks(LEDGER_SHEET, led, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert out["errors"] == ["fixed"] and out["fixed_cards"] == []
    assert [c["key"] for c in out["unmatched_cards"]] == ["Spleen :: spleen"]
    assert out["normal_report"] and out["uncovered_cards"]
    assert (await V.sheet_checks("# free", []))["errors"] == ["parse"]


def _jev_on(word):
    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        return httpx.Response(200, json={"answers": {
            k: {"noul": 0.9 if word in q["instructions"].split("REPORT: ")[-1].lower() else 0.1} for k, q in qs.items()}})
    return httpx.MockTransport(handler)


async def test_a_line_that_may_state_a_decided_concept_twice_is_a_card():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet.replace(
        'FIXED "Axial images were acquired."\n', 'FIXED "Axial images were acquired."\nFIXED "There is no prior study."\n')
    out = await V.sheet_checks(sheet, led, transport=_jev_on("prior"))
    assert [(c["key"], c["note"]) for c in out["duplicate_cards"]] == [
        ("There is no prior study.", "May be stated twice: Comparison with previous imaging")]
    assert "There is no prior study." not in [c["key"] for c in out["fixed_cards"]]   # one card per line
    assert await V.concept_duplicates(_st(LEDGER_SHEET), [], transport=_jev_on("prior")) == []   # nothing decided


# ── realistic cases ──────────────────────────────────────────────────────────────────────────────────────────────

BREATH = "The patient was able to hold their breath for the study."
LIMITED = "the dictation states a technical limitation of the study"
# a patient-specific line written as the default of a study-level concept (limitation), with its context rule
BREATH_SHEET = LEDGER_SHEET.replace(
    'FIXED "Axial images were acquired."\n',
    f'FIXED "Axial images were acquired."\nFIXED "{BREATH}"\n'
    f'RULE WHEN [context: {LIMITED}] REPLACE "{BREATH}" WITH "Breath-holding was limited."\n')


def _jev_if(word):
    """Jev stub: high only for the question about a sentence containing `word`."""
    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        return httpx.Response(200, json={"answers": {
            k: {"noul": 0.9 if word in q["instructions"].lower() else 0.1} for k, q in qs.items()}})
    return httpx.MockTransport(handler)


async def test_a_patient_specific_concept_default_is_surfaced_by_the_fixed_check():
    st = _st(BREATH_SHEET)
    assert BREATH in V.fixed_candidates(st, [])          # an undecided concept's default is still a candidate
    assert await V.fixed_flags(st, [], transport=_jev_if("breath")) == [BREATH, "No previous imaging available."]
    out = await V.sheet_checks(BREATH_SHEET, [], transport=_jev_if("breath"))
    assert BREATH in [c["key"] for c in out["fixed_cards"]]


def test_the_fixed_question_is_case_agnostic():
    q = " ".join([V.FIXED_INSTRUCTIONS, *V.FIXED_CRITERIA.values()]).lower()
    for word in ("contrast", "liver", "breath", "ct", "mri"):
        assert f" {word} " not in f" {q} "


async def test_a_negative_that_may_state_a_decided_concept_twice_is_a_card_on_that_negative():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet.replace(
        'NEGATIVE "No focal liver lesion."\n', 'NEGATIVE "No focal liver lesion."\nNEGATIVE "No prior study for comparison."\n')
    cards = await V.concept_duplicates(_st(sheet), led, transport=_jev_on("prior"))
    assert [(c["ledger_kind"], c["key"], c["title"]) for c in cards] == [
        ("normal", td.negative_key("Liver", "No prior study for comparison."), "No prior study for comparison.")]
    assert [x["choice"] for x in cards[0]["choices"]] == [{"text": ""}, {"text": "No prior study for comparison."}]


OTHER = "the dictation states the study was performed out of hours"   # a context condition no standard concept owns
CONDITIONAL_SHEET = LEDGER_SHEET.replace(
    'FIXED "Axial images were acquired."\n',
    'FIXED "Axial images were acquired."\nFIXED "Routine protocol."\n'
    f'RULE WHEN [context: {OTHER}] REPLACE "Routine protocol." WITH "Out-of-hours protocol."\n'
    f'RULE WHEN [context: {OTHER}] USE "Reported out of hours."\n')


def test_a_non_standard_context_rule_makes_its_lines_conditional_not_always_printed():
    st = _st(CONDITIONAL_SHEET)
    cands = V.fixed_candidates(st, [])
    assert "Routine protocol." not in cands                       # its target: resolved per case at Generate
    assert "Out-of-hours protocol." not in cands and "Reported out of hours." not in cands
    assert cands == ["Axial images were acquired.", "No previous imaging available."]
    assert not {"Routine protocol.", "Out-of-hours protocol.", "Reported out of hours."} & {
        x["text"] for x in V.duplicate_candidates(st, [])}


def _cmp_ledger():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging available.",
                                                           "when_met": "Compared with {date}."}, source="creation")
    return led


async def test_an_answered_duplicate_card_does_not_come_back():
    led = _cmp_ledger()
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet.replace(
        'FIXED "Axial images were acquired."\n', 'FIXED "Axial images were acquired."\nFIXED "There is no prior study."\n'
    ).replace('NEGATIVE "No focal liver lesion."\n',
              'NEGATIVE "No focal liver lesion."\nNEGATIVE "No prior study for comparison."\n')
    cards = await V.concept_duplicates(_st(sheet), led, transport=_jev_on("prior"))
    assert {c["title"] for c in cards} == {"There is no prior study.", "No prior study for comparison."}
    keep = [{"kind": c["ledger_kind"], "key": c["key"], "choice": c["choices"][1]["choice"]} for c in cards]
    led2, errors = td.ledger_from_changes(keep, base=led)     # "Keep both" on each
    assert errors == []
    assert await V.concept_duplicates(_st(sheet), led2, transport=_jev_on("prior")) == []


async def test_a_failing_part_of_the_sheet_checks_is_named_and_the_rest_still_runs(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(V, "normal_report", boom)
    out = await V.sheet_checks(LEDGER_SHEET, [], transport=_jev(0.1))
    assert out["errors"] == ["normal_report"] and out["normal_report"] == [] and out["uncovered_cards"]


async def test_the_duplicate_check_batches_its_questions_and_caps_them(monkeypatch):
    sizes, logged = [], []

    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        sizes.append(len(qs))
        return httpx.Response(200, json={"answers": {k: {"noul": 0.1} for k in qs}})
    extra = "".join(f'FIXED "Line number {i}."\n' for i in range(30))
    sheet = tla.apply_ledger(LEDGER_SHEET, _cmp_ledger()).sheet.replace(
        'FIXED "Axial images were acquired."\n', 'FIXED "Axial images were acquired."\n' + extra)
    monkeypatch.setattr(V, "DUP_MAX_QUESTIONS", 25)
    monkeypatch.setattr(V.logger, "info", lambda msg, *a: logged.append(msg % a))   # global log config varies
    assert await V.concept_duplicates(_st(sheet), _cmp_ledger(), transport=httpx.MockTransport(handler)) == []
    assert sum(sizes) == 25 and max(sizes) <= V.JEV_BATCH
    assert any("truncated" in m for m in logged)



def test_the_fixed_question_is_a_criteria_noul_with_the_sentence():
    q = V.q_fixed("Axial images were acquired.")
    assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}
    assert q["instructions"] == ("Could this SENTENCE from a radiology report template differ between patients having "
                                 "this same scan? SENTENCE: Axial images were acquired.")
    assert q["criteria"]["false"].endswith("the same for every patient.")
    assert V.FIXED_STATE == "Statements from a radiology report template."
    assert "cooperation" in q["criteria"]["true"] and "sign-off" in q["criteria"]["false"]


async def test_slot_and_sign_off_lines_are_never_asked_nor_flagged():
    asked = []

    def handler(request):
        import json
        qs = json.loads(request.content)["questions"]
        asked.extend(q["instructions"] for q in qs.values())
        return httpx.Response(200, json={"answers": {k: {"noul": 0.9} for k in qs}})
    lines = ["Slice thickness {thickness} mm.", "Reported by the duty radiologist.", "Dr A. Smith, FRCR.",
             "No {structure} abnormality."]
    sheet = BREATH_SHEET.replace('FIXED "Axial images were acquired."\n', 'FIXED "Axial images were acquired."\n'
                                 + "".join(f'FIXED "{t}"\n' for t in lines))
    flags = await V.fixed_flags(_st(sheet), [], transport=httpx.MockTransport(handler))
    assert not any(t in q for t in lines for q in asked) and not set(lines) & set(flags)
    assert BREATH in flags and any(BREATH in q for q in asked)   # the breath-hold default is still asked



async def test_a_clinical_line_starting_with_signed_is_still_asked():
    asked, states = [], []

    def handler(request):
        import json
        body = json.loads(request.content)
        states.append(body["state"])
        asked.extend(q["instructions"] for q in body["questions"].values())
        return httpx.Response(200, json={"answers": {k: {"noul": 0.9} for k in body["questions"]}})
    line = "Signed consent was obtained for contrast."
    sheet = LEDGER_SHEET.replace('FIXED "Axial images were acquired."\n',
                                 f'FIXED "Axial images were acquired."\nFIXED "{line}"\nFIXED "Electronically signed."\n')
    flags = await V.fixed_flags(_st(sheet), [], transport=httpx.MockTransport(handler))
    assert line in flags and any(line in q for q in asked) and states == [V.FIXED_STATE]
    assert not any("Electronically signed." in q for q in asked)
