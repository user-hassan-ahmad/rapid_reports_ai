"""One-tap decision cards (Rules-step spec, "Cards")."""
from rapid_reports_ai import template_decision_run as R
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_rules_cards as C

EX = ["Findings: LVEF 55%. ECV 28%. No previous imaging.",
      "Findings: LVEF 60%. Compared with CT of 01/01/2020.",
      "Findings: LVEF 50%. ECV 30%. No previous imaging."]


def _run(values=(), concepts=(), states=None):
    out = R.RunOutput(values=list(values), concepts=list(concepts))
    run = R.check_quotes(out, EX)
    run.states = states
    return run


def _q(r, t):
    return R.Quote(report=r, text=t)


LVEF = R.ValueCandidate(name="LVEF", quotes=[_q(1, "LVEF 55%"), _q(2, "LVEF 60%"), _q(3, "LVEF 50%")])
ECV = R.ValueCandidate(name="ECV", quotes=[_q(1, "ECV 28%"), _q(3, "ECV 30%")])
NO_PRIOR = R.ConceptWording(concept="comparison", state="none", text="No previous imaging.",
                            quotes=[_q(1, "No previous imaging."), _q(3, "No previous imaging.")])
PRIOR = R.ConceptWording(concept="comparison", state="compared", text="Compared with {study} of {date}.",
                         quotes=[_q(2, "Compared with CT of 01/01/2020.")])
ALL = {"comparison": [1, 2, 3], "contrast": [], "sequences": [], "limitation": []}
PRIOR_COND = "the dictation names a previous imaging study for comparison"


def test_evidence_line_names_reports_never_percentages():
    assert C.evidence_line({"reports": [4, 1, 2], "quote": "ECV 28%"}) == "reports 1, 2, 4: 'ECV 28%'"
    assert C.evidence_line({"reports": [3], "quote": None}) == "report 3: not stated"


def test_a_value_in_every_example_is_kept_pre_ticked_and_a_partial_one_is_a_card():
    out = C.build_cards(_run([LVEF, ECV], states=ALL), 3)
    assert [c["id"] for c in out["kept"]] == ["value:lvef"] and out["kept"][0]["selected"] == "every"
    ecv = out["cards"][0]
    assert ecv["id"] == "value:ecv" and ecv["selected"] is None
    assert [C.evidence_line(e) for e in ecv["evidence"]] == ["reports 1, 3: 'ECV 28%'", "report 2: not stated"]
    assert [c["id"] for c in ecv["choices"]] == ["every", "relevant", "not_needed"]
    assert out["defaults"] == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}}]


def test_a_varying_concept_is_a_card_with_both_wordings_never_pre_ticked():
    out = C.build_cards(_run([], [NO_PRIOR, PRIOR], states=ALL), 3)
    card = next(c for c in out["cards"] if c["id"] == "concept:comparison")
    assert card["wording"] == {"default": "No previous imaging.", "when_met": "Compared with {study} of {date}.",
                               "condition": PRIOR_COND}
    assert card["selected"] is None
    keep = next(x for x in card["choices"] if x["id"] == "keep")["choice"]
    assert td.validate("concept", "comparison", keep)[1] == keep


def test_a_default_only_concept_is_still_asked():
    out = C.build_cards(_run([], [NO_PRIOR], states={**ALL, "comparison": [1, 2, 3]}), 3)
    assert [c["id"] for c in out["cards"]] == ["concept:comparison"] and not out["kept"]


def test_two_wordings_for_one_role_are_a_disagreement_ranked_first():
    other = R.ConceptWording(concept="comparison", state="none", text="LVEF 60%.", quotes=[_q(2, "LVEF 60%.")])
    out = C.build_cards(_run([ECV], [NO_PRIOR, other, PRIOR], states=ALL), 3)
    assert out["cards"][0]["kind"] == "disagree" and out["cards"][0]["key"] == "comparison"
    labels = [x["label"] for x in out["cards"][0]["choices"]]
    assert labels[-1] == "Use whichever is dictated" and len(labels) == 3
    dictated = out["cards"][0]["choices"][-1]["choice"]                 # its own choice, not "not used"
    assert td.validate("concept", "comparison", dictated)[1]["dictated"] is True


def test_no_jev_means_no_study_level_cards():
    out = C.build_cards(_run([ECV], [NO_PRIOR, PRIOR], states=None), 3)
    assert [c["kind"] for c in out["cards"]] == ["value"]


def test_a_verified_quote_counts_as_stating_when_jev_misses_it():
    out = C.build_cards(_run([], [NO_PRIOR, PRIOR], states={n: [] for n in td.CONCEPTS}), 3)
    card = out["cards"][0]
    assert card["id"] == "concept:comparison" and not any(e["quote"] is None for e in card["evidence"])


def test_a_concept_every_example_words_the_same_way_is_still_a_card():
    prior_all = R.ConceptWording(concept="comparison", state="compared", text="Compared with {study}.",
                                 quotes=[_q(1, "LVEF 55%"), _q(2, "LVEF 60%"), _q(3, "LVEF 50%")])
    out = C.build_cards(_run([], [prior_all], states=ALL), 3)
    assert [c["id"] for c in out["cards"]] == ["concept:comparison"] and out["kept"] == []


EX_C = ["Technique: No contrast agent was given. LVEF 55%.", "Technique: No contrast agent was given. LVEF 60%.",
        "Technique: Following a contrast agent. LVEF 50%."]


def test_contrast_default_is_the_usual_wording_and_the_condition_is_its_opposite():
    none = R.ConceptWording(concept="contrast", state="not_given", text="No contrast agent was given.",
                            quotes=[_q(1, "No contrast agent was given."), _q(2, "No contrast agent was given.")])
    given = R.ConceptWording(concept="contrast", state="given", text="Following a contrast agent.",
                             quotes=[_q(3, "Following a contrast agent.")])
    run = R.check_quotes(R.RunOutput(concepts=[none, given]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["wording"] == {"default": "No contrast agent was given.", "when_met": "Following a contrast agent.",
                               "condition": "the dictation states a contrast agent was given"}
    # the same wordings, with the given wording usual: the other way round
    given2 = given.model_copy(update={"quotes": [_q(3, "Following a contrast agent."), _q(1, "LVEF 55%"),
                                                 _q(2, "LVEF 60%")]})
    run = R.check_quotes(R.RunOutput(concepts=[none.model_copy(update={"quotes": [_q(1, "No contrast agent was given.")]}),
                                               given2]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["wording"]["default"] == "Following a contrast agent."
    assert card["wording"]["condition"] == "the dictation states no contrast agent was given"


def test_the_budget_moves_the_rest_to_more():
    vals = [R.ValueCandidate(name=f"Value {i}", quotes=[_q(1, "LVEF 55%"), _q(3, "LVEF 50%")]) for i in range(11)]
    out = C.build_cards(_run(vals, states=ALL), 3)
    assert len(out["cards"]) == C.MAX_CARDS and len(out["more"]) == 3


def test_a_failed_run_has_no_cards():
    assert C.build_cards(R.DecisionRun(ok=False), 3) == {"cards": [], "more": [], "kept": [], "defaults": []}


from rapid_reports_ai import template_ledger_apply as tla
from tests.template_sheet_fixtures import LEDGER_SHEET


def test_current_value_cards_show_the_sheets_list_and_the_ledgers_other_values():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "ECV", {"need": "relevant"}, source="creation")
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    cards = C.current_value_cards(sheet, led)
    assert [(c["key"], c["selected"]) for c in cards] == [("LVEF", "every"), ("ECV", "relevant")]
    assert C.current_value_cards("# not grammar", led) == []


def test_card_for_change_is_prefilled_and_not_preselected():
    card = C.card_for_change("value", "ECV", {"need": "not_needed"})
    assert card["id"] == "value:ecv" and card["step"] == "chat" and card["selected"] is None
    card = C.card_for_change("concept", "comparison", {"use": True, "default": "", "when_met": "Compared with {date}."})
    assert card["wording"] == {"default": "", "when_met": "Compared with {date}.", "condition": PRIOR_COND}
    card = C.card_for_change("normal", "Liver :: liver", {"text": "The liver is normal."})
    assert card["wording"] == {"text": "The liver is normal."} and card["kind"] == "normal"


def test_a_contrast_tie_is_asked_never_defaulted():
    # Hassan, after the decision-run lab: the usual state needs a clear majority (2+ reports and more than the other)
    none = R.ConceptWording(concept="contrast", state="not_given", text="No contrast agent was given.",
                            quotes=[_q(1, "No contrast agent was given.")])
    given = R.ConceptWording(concept="contrast", state="given", text="Following a contrast agent.",
                             quotes=[_q(3, "Following a contrast agent.")])
    run = R.check_quotes(R.RunOutput(concepts=[none, given]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["id"] == "concept:contrast" and card["title"] == "Is contrast usually given for this scan?"
    assert card["selected"] is None and "wording" not in card
    given_c = next(x for x in card["choices"] if x["id"] == "usual:given")["choice"]
    none_c = next(x for x in card["choices"] if x["id"] == "usual:not_given")["choice"]
    assert given_c["default"] == "Following a contrast agent." and given_c["when_met"] == "No contrast agent was given."
    assert given_c["condition"] == "the dictation states no contrast agent was given"
    assert none_c["default"] == "No contrast agent was given."
    assert none_c["condition"] == "the dictation states a contrast agent was given"
    for ch in (given_c, none_c):
        assert td.validate("concept", "contrast", ch)[1] == ch


def test_one_report_stating_contrast_is_not_a_majority():
    none = R.ConceptWording(concept="contrast", state="not_given", text="No contrast agent was given.",
                            quotes=[_q(1, "No contrast agent was given.")])
    run = R.check_quotes(R.RunOutput(concepts=[none]), EX_C)
    run.states = {n: [] for n in td.CONCEPTS}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["title"] == "Is contrast usually given for this scan?"
    given_c = next(x for x in card["choices"] if x["id"] == "usual:given")["choice"]
    assert given_c["default"] == "" and given_c["when_met"] == "No contrast agent was given."
    assert td.validate("concept", "contrast", given_c)[1] == given_c


def test_values_seen_in_one_report_go_under_more():
    one = R.ValueCandidate(name="Heart rate", quotes=[_q(2, "LVEF 60%")])
    out = C.build_cards(_run([ECV, one], states=ALL), 3)
    assert [c["id"] for c in out["cards"]] == ["value:ecv"] and [c["id"] for c in C.flat(out["more"])] == ["value:heart rate"]


# ── follow-up lab (2026-10-13): More capped at MAX_MORE, one-report values grouped ─────────────────────────────

def _two(i):
    return R.ValueCandidate(name=f"Value {i}", quotes=[_q(1, "LVEF 55%"), _q(3, "LVEF 50%")])


def _one(i):
    return R.ValueCandidate(name=f"Single {i}", quotes=[_q(2, "LVEF 60%")])


def test_eight_single_report_values_are_one_collapsed_group():
    out = C.build_cards(_run([ECV, *(_one(i) for i in range(8))], states=ALL), 3)
    assert [c["id"] for c in out["cards"]] == ["value:ecv"]
    assert len(out["more"]) == 1
    group = out["more"][0]
    assert group["kind"] == "group" and group["collapsed"] is True
    assert group["title"] == "Seen in one report: " + ", ".join(f"Single {i}" for i in range(8))
    assert [c["id"] for c in group["cards"]] == [f"value:single {i}" for i in range(8)]
    assert all(c["choices"] and c["selected"] is None for c in group["cards"])   # each still choosable
    assert [c["id"] for c in C.flat(out["more"])] == [f"value:single {i}" for i in range(8)]


def test_more_is_capped_and_concept_cards_sit_outside_the_cap():
    out = C.build_cards(_run([*(_two(i) for i in range(15)), *(_one(i) for i in range(2))], [NO_PRIOR, PRIOR],
                             states=ALL), 3)
    assert len(out["cards"]) == C.MAX_CARDS
    concepts = [c for c in out["more"] if c["kind"] == "concept"]
    capped = [c for c in out["more"] if c["kind"] != "concept"]
    assert [c["id"] for c in concepts] == ["concept:comparison"]
    assert len(capped) == C.MAX_MORE
    assert [c["kind"] for c in capped][-2:] == ["group", "group"]
    flat_ids = {c["id"] for c in C.flat(out["more"])}
    assert len(flat_ids) == 15 - C.MAX_CARDS + 2 + 1          # nothing lost: 7 values, 2 singles, 1 concept


# ── the study setup as first evidence (Hassan, 2026-10-13) ─────────────────────────────────────────────────────

def _contrast_run(none_reports, given_reports, setup):
    none = R.ConceptWording(concept="contrast", state="not_given", text="No contrast agent was given.",
                            quotes=[_q(r, "No contrast agent was given.") for r in none_reports])
    given = R.ConceptWording(concept="contrast", state="given", text="Following a contrast agent.",
                             quotes=[_q(r, "Following a contrast agent.") for r in given_reports])
    ex = ["Technique: No contrast agent was given. Following a contrast agent."] * 3
    run = R.check_quotes(R.RunOutput(concepts=[w for w in (none, given) if w.quotes]), ex)
    run.states = {n: [] for n in td.CONCEPTS}
    run.setup = setup
    return C.build_cards(run, 3)["cards"][0]


def test_the_setup_sets_contrast_when_the_examples_tie():
    card = _contrast_run([1], [2], {"contrast": {"state": "given", "quote": "with IV contrast"}})
    assert card["wording"]["default"] == "Following a contrast agent."
    assert card["wording"]["condition"] == "the dictation states no contrast agent was given"
    assert card["evidence"][0] == {"reports": [], "source": "setup", "quote": "with IV contrast"}
    assert C.evidence_line(card["evidence"][0]) == "From the study setup: 'with IV contrast'"


def test_the_setup_against_a_clear_example_majority_asks_showing_both():
    card = _contrast_run([], [1, 2], {"contrast": {"state": "not_given", "quote": "non-contrast"}})
    assert card["title"] == "Is contrast usually given for this scan?" and card["selected"] is None
    assert card["evidence"][0]["source"] == "setup" and any(e["reports"] == [1, 2] for e in card["evidence"])


def test_a_silent_setup_is_todays_rule():
    assert _contrast_run([1], [2], {})["title"] == "Is contrast usually given for this scan?"
    card = _contrast_run([1, 3], [2], {})
    assert card["wording"]["default"] == "No contrast agent was given."
    assert not any(e.get("source") == "setup" for e in card["evidence"])


def test_a_setup_that_agrees_with_the_majority_is_shown_first():
    card = _contrast_run([], [1, 2], {"contrast": {"state": "given", "quote": "with IV contrast"}})
    assert card["wording"]["default"] == "Following a contrast agent." and card["evidence"][0]["source"] == "setup"


def test_a_concept_stated_in_the_setup_is_evidence_never_a_report_number():
    run = _run([], [NO_PRIOR, PRIOR], states=ALL)
    run.setup = {"comparison": {"state": None, "quote": None}}
    card = C.build_cards(run, 3)["cards"][0]
    assert card["evidence"][0] == {"reports": [], "source": "setup", "quote": None}
    assert C.evidence_line(card["evidence"][0]) == "From the study setup"


def test_unmatched_entries_become_review_cards_with_a_note():
    from rapid_reports_ai import template_rules_cards as trc
    entries = [{"kind": "fixed", "key": "A line the sheet lacks.", "choice": {"keep": "always"}},
               {"kind": "fixed", "key": "", "choice": {"keep": "nonsense"}}]          # invalid: skipped
    cards = trc.unmatched_cards(entries)
    assert [c["key"] for c in cards] == ["A line the sheet lacks."]
    assert cards[0]["step"] == "review" and cards[0]["note"] == trc.UNMATCHED_NOTE and cards[0]["selected"] is None
    assert trc.unmatched_cards(None) == [] and trc.unmatched_cards("x") == []


def test_an_unmatched_fixed_line_is_never_offered_always_again():
    from rapid_reports_ai import template_rules_cards as trc
    c = trc.unmatched_cards([{"kind": "fixed", "key": "A line the sheet lacks.", "choice": {"keep": "always"}}])[0]
    assert [(x["id"], x["choice"]) for x in c["choices"]] == [
        ("dictated", {"keep": "dictated"}), ("remove", {"keep": "remove"}), ("forget", td.FORGET)]


FRAG = R.ConceptWording(concept="comparison", state="compared", text="compared with {study} of {date}",
                        quotes=[_q(2, "Compared with CT of 01/01/2020.")])


def test_a_fragment_wording_is_never_offered_and_the_concept_falls_back_to_dictated():
    run = _run([], [NO_PRIOR, FRAG], states=ALL)
    assert any(w.text == FRAG.text for w in run.concepts)          # the quote is real: only the shape is wrong
    out = C.build_cards(run, 3)
    card = next(c for c in C.flat(out["cards"] + out["more"]) if c["key"] == "comparison")
    offered = [x["choice"] for x in card["choices"] if x["choice"]]
    assert all(FRAG.text not in (ch.get("default", ""), ch.get("when_met", "")) for ch in offered)
    assert any(x["id"] == "dictated" and x["choice"]["dictated"] for x in card["choices"])
    for ch in offered:
        td.validate("concept", "comparison", ch)                    # every offered choice is applicable
    assert card["selected"] is None
    assert any(e.get("quote") == "Compared with CT of 01/01/2020." for e in card["evidence"])


def test_usual_question_is_public():
    assert C.usual_question("contrast") == "Is contrast usually given for this scan?"
    assert C.usual_question("comparison") == "Which is usual: comparison with previous imaging?"
