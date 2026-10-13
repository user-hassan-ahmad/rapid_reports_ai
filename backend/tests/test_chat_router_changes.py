"""Code validates each structured change (spec Flow 2, "Uncertain or rejected changes become cards"; plan
decisions 3-6)."""
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_ledger as L
from tests.template_sheet_fixtures import ROUTER_SHEET


def _ctx(instruction, ledger=None, confirmed=False):
    return CH.Ctx(ROUTER_SHEET, ledger or [], instruction, confirmed=confirmed)


def test_a_listed_value_is_applied_through_the_ledger():
    v = CH.validate("value", CH.ValueChange(name="width", to="not_needed"), _ctx("drop width"))
    assert (v.action, v.key, v.choice, v.claim) == ("ledger", "Width", {"need": "not_needed"},
                                                    "Width is no longer required.")
    assert v.change == {"kind": "value", "name": "width", "to": "not_needed", "sure": True}


def test_a_new_value_needs_its_name_in_the_instruction():
    ok = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("always give the height"))
    assert ok.action == "ledger" and ok.key == "Height"
    card = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("add the other size"))
    assert card.action == "card" and card.card["ledger_kind"] == "value" and card.invented
    ask = CH.validate("value", CH.ValueChange(name="Mass", to="not_needed"), _ctx("drop mass"))
    assert ask.action == "ask" and "Mass" in ask.reason


def test_concept_wording_from_the_instruction_or_the_sheet_is_applied():
    instr = 'when there is a prior say "Compared with the {study} of {date}."'
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", state="used",
                                                default="No previous imaging available.",
                                                when_met="Compared with the {study} of {date}."), _ctx(instr))
    assert v.action == "ledger" and L.concept_state(v.choice) == (
        "used", "No previous imaging available.", "Compared with the {study} of {date}.",
        L.condition_for("comparison", "compared"))


def test_contrast_carries_its_condition_and_asks_which_is_usual():
    instr = 'say "Contrast was given." normally and "No contrast was given." when none'
    change = dict(concept="contrast", state="used", default="Contrast was given.", when_met="No contrast was given.")
    ask = CH.validate("concept", CH.ConceptChange(**change), _ctx(instr))
    assert ask.action == "ask" and ask.reason == L.usual_question("contrast")
    ok = CH.validate("concept", CH.ConceptChange(**change, condition="not_given"), _ctx(instr))
    assert ok.action == "ledger" and ok.choice["condition"] == L.condition_for("contrast", "not_given")
    led, _ = L.set_choice([], "concept", "contrast", ok.choice)
    kept = CH.validate("concept", CH.ConceptChange(concept="contrast", when_met="No contrast agent was given."),
                       _ctx('use "No contrast agent was given."', led))
    assert kept.action == "ledger" and kept.choice["condition"] == ok.choice["condition"]   # carried forward


def test_dictated_and_not_used_concepts():
    d = CH.validate("concept", CH.ConceptChange(concept="comparison", state="dictated"), _ctx("whichever is dictated"))
    assert d.action == "ledger" and L.concept_state(d.choice) == ("dictated", "", "", "")
    off = CH.validate("concept", CH.ConceptChange(concept="comparison", state="not_used"), _ctx("never mention it"))
    assert off.action == "ledger" and off.claim == f"{L.CONCEPTS['comparison']}: no longer stated."


def test_a_code_rejection_never_leaks_its_internal_text():
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", state="used"), _ctx("use it"))
    assert v.action == "reject" and v.reason == CH.REJECT.format(label=CH.KIND_LABEL["concept"])
    assert "wording" in v.detail and "wording" not in v.reason


def test_invented_concept_wording_becomes_a_prefilled_card_and_a_bad_slot_is_rejected():
    v = CH.validate("concept", CH.ConceptChange(concept="comparison", when_met="Compared with the {study}."),
                    _ctx("mention the prior study"))
    assert v.action == "card" and v.card["ledger_kind"] == "concept" and v.invented
    bad = CH.validate("concept", CH.ConceptChange(concept="comparison", when_met="Compared, see {reason}."),
                      _ctx('say "Compared, see {reason}."'))
    assert bad.action == "reject" and "{reason}" in bad.reason
    unknown = CH.validate("concept", CH.ConceptChange(concept="weather", state="not_used"), _ctx("x"))
    assert unknown.action == "ask"


def test_fixed_keep_reword_and_add():
    rm = CH.validate("fixed", CH.FixedChange(to="remove", line="No previous imaging available"), _ctx("stop that"))
    assert rm.action == "ledger" and rm.choice == {"keep": "remove"} and rm.key == "No previous imaging available."
    rw = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                             text="Axial and coronal images were acquired."),
                     _ctx("say Axial and coronal images were acquired. instead"))
    assert rw.action == "edit" and rw.op == {"op": "fixed_reword", "line": "Axial images were acquired.",
                                             "text": "Axial and coronal images were acquired."}
    add = CH.validate("fixed", CH.FixedChange(to="add", paragraph="technique", text="Images were reviewed."),
                      _ctx("add Images were reviewed. to the technique"))
    assert add.action == "edit" and add.op["op"] == "fixed_add" and add.choice == {"keep": "always"}
    missing = CH.validate("fixed", CH.FixedChange(to="remove", line="Not a sentence here."), _ctx("x"))
    assert missing.action == "ask"


def test_a_fixed_edit_on_a_concepts_line_goes_through_the_concept():
    led, _ = L.set_choice([], "concept", "comparison",
                          L.concept_choice("used", "No previous imaging available.", ""))
    rm = CH.validate("fixed", CH.FixedChange(to="remove", line="No previous imaging available."),
                     _ctx("stop saying no previous imaging", led))
    assert rm.kind == "concept" and rm.action == "ledger" and L.concept_state(rm.choice)[0] == "not_used"
    rw = CH.validate("fixed", CH.FixedChange(to="reword", line="No previous imaging available.",
                                             text="No prior imaging."), _ctx("say No prior imaging. instead", led))
    assert rw.kind == "concept" and L.concept_state(rw.choice)[1] == "No prior imaging."
    dic = CH.validate("fixed", CH.FixedChange(to="dictated", line="No previous imaging available."),
                      _ctx("only when dictated", led))
    assert dic.kind == "concept" and L.concept_state(dic.choice)[0] == "dictated"
    add = CH.validate("fixed", CH.FixedChange(to="add", paragraph="Technique", text="No previous imaging available."),
                      _ctx("add No previous imaging available.", led))
    assert add.action == "ask"


def test_a_reword_that_would_clash_with_a_decided_line_is_rejected():
    led, _ = L.set_choice([], "fixed", "Axial images were acquired.", {"keep": "always"})
    led, _ = L.set_choice(led, "fixed", "Axial and coronal images were acquired.", {"keep": "dictated"})
    v = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                            text="Axial and coronal images were acquired."),
                    _ctx("say Axial and coronal images were acquired.", led))
    assert v.action == "reject" and v.detail


def test_a_reword_not_in_the_instruction_is_a_proposal_card():
    v = CH.validate("fixed", CH.FixedChange(to="reword", line="Axial images were acquired.",
                                            text="Axial images were obtained."), _ctx("change the technique line"))
    assert v.action == "card" and v.card["kind"] == "proposal" and v.card["apply"]["op"]["op"] == "fixed_reword"
    assert v.card["title"].startswith("Make this change?")


def test_normals_reword_remove_and_add():
    rw = CH.validate("normal", CH.NormalChange(paragraph="upper", structure="alpha", to="reword",
                                               text="Alpha is unremarkable."), _ctx("say Alpha is unremarkable."))
    assert rw.action == "ledger" and rw.key == L.normal_key("Upper", "alpha") and rw.choice == {
        "text": "Alpha is unremarkable."}
    rm = CH.validate("normal", CH.NormalChange(paragraph="Upper", negative="No beta abnormality.", to="removed"),
                     _ctx("stop saying no beta abnormality"))
    assert rm.action == "ledger" and rm.choice == {"text": ""}
    add = CH.validate("normal", CH.NormalChange(paragraph="Lower", structure="delta", to="add",
                                                text="Delta is normal."), _ctx("add Delta is normal."))
    assert add.action == "edit" and add.op["op"] == "normal_add" and add.choice == {"text": "Delta is normal."}
    absent = CH.validate("normal", CH.NormalChange(paragraph="Lower", structure="delta", to="reword", text="x"),
                         _ctx("x"))
    assert absent.action == "ask"


def test_layout_is_dry_run_and_gated_on_new_names():
    ok = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                     _ctx("call the upper paragraph Top"))
    assert ok.action == "edit" and ok.op == {"op": "rename_paragraph", "paragraph": "Upper", "to": "Top"}
    bad = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Lower"),
                      _ctx("call it Lower"))
    assert bad.action == "ask"
    guess = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                        _ctx("rename the upper paragraph"))
    assert guess.action == "card" and guess.card["kind"] == "proposal"
    inside_a_word = CH.validate("layout", CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top"),
                                _ctx("stop using the upper name"))
    assert inside_a_word.action == "card"


def test_unsure_is_a_card_and_confirmed_skips_the_gate():
    unsure = CH.validate("value", CH.ValueChange(name="Width", to="relevant", sure=False), _ctx("width sometimes"))
    assert unsure.action == "card" and not unsure.invented
    tapped = CH.validate("value", CH.ValueChange(name="Height", to="every"), _ctx("", confirmed=True))
    assert tapped.action == "ledger"


def test_to_card_and_claim_for():
    v = CH.validate("value", CH.ValueChange(name="Width", to="every"), _ctx("width"))
    assert CH.to_card(v).card["ledger_kind"] == "value"
    assert CH.claim_for("fixed", "A line.", {"keep": "dictated"}) == '"A line." is now printed only when dictated.'
    assert CH.claim_for("normal", L.normal_key("Upper", "alpha"), {"text": ""}) == (
        "Upper: alpha is no longer stated when normal.")
