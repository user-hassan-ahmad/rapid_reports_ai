"""apply_ledger: the ledger applied to a grammar sheet by code (Rules-step spec, "Decision ledger")."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import GOOD, LEDGER_SHEET


def _led(*changes):
    led = []
    for kind, key, choice in changes:
        led, _ = td.set_decision(led, kind, key, choice, source="creation", at="t")
    return led


def _clean(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def test_fixture_is_clean():
    _clean(LEDGER_SHEET)


def test_empty_ledger_or_non_grammar_sheet_is_unchanged():
    assert tla.apply_ledger(LEDGER_SHEET, []).sheet == LEDGER_SHEET
    led = _led(("value", "LVEF", {"need": "every"}))
    assert tla.apply_ledger("# Free\nprose", led).sheet == "# Free\nprose"


def test_every_values_are_inserted_under_report_wide():
    led = _led(("value", "LVEF", {"need": "every"}), ("value", "ECV", {"need": "relevant"}))
    res = tla.apply_ledger(LEDGER_SHEET, led)
    st = _clean(res.sheet)
    lm = [r for r in st.rules if r.effect == "list_missing"]
    assert [r.items for r in lm] == [["LVEF"]] and lm[0].section == "FINDINGS" and lm[0].position == "top"
    assert ('RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF"] AT TOP | section: FINDINGS'
            in res.sheet.split("## Report-wide")[1].split("## Paragraph")[0])
    assert res.applied == [{"kind": "value", "key": "*", "action": "inserted"}] and res.changed == 1


def test_a_sheet_without_report_wide_gets_the_block():
    res = tla.apply_ledger(GOOD, _led(("value", "Width", {"need": "every"})))
    assert "## Report-wide\nRULE WHEN" in res.sheet
    assert [r.items for r in _clean(res.sheet).rules if r.effect == "list_missing"] == [["Width"]]


def test_the_ledger_owns_the_list_existing_order_kept_extras_dropped():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["B" | "Extra" | "A"] '
        'AT END | section: FINDINGS\n')
    _clean(sheet)
    led = _led(("value", "a", {"need": "every"}), ("value", "b", {"need": "every"}), ("value", "C", {"need": "every"}),
               ("value", "Extra", {"need": "not_needed"}))
    res = tla.apply_ledger(sheet, led)
    lm = [r for r in _clean(res.sheet).rules if r.effect == "list_missing"]
    assert lm[0].items == ["b", "a", "C"] and lm[0].position == "end"   # sheet order, then new; ledger spelling
    assert res.applied[0]["action"] == "rewritten"


def test_no_every_value_removes_the_line():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value is not stated] LIST_MISSING ["A"] AT TOP '
        '| section: FINDINGS\n')
    res = tla.apply_ledger(sheet, _led(("value", "A", {"need": "not_needed"})))
    assert "LIST_MISSING" not in res.sheet and res.applied[0]["action"] == "removed"


def test_apply_is_idempotent():
    led = _led(("value", "LVEF", {"need": "every"}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0


from rapid_reports_ai import template_context_rules as tcr

PRIOR = "the dictation names a previous imaging study for comparison"
GIVEN = "the dictation states a contrast agent was given"
NOT_GIVEN = "the dictation states no contrast agent was given"
COMPARISON = {"use": True, "default": "No previous imaging available.",
              "when_met": "Compared with the previous {modality} of {date}.", "condition": PRIOR, "dictated": False}


def test_comparison_reuses_the_writers_fixed_line_and_adds_the_standard_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON)))
    st = _clean(res.sheet)
    rule = next(r for r in st.rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target, rule.then_text) == (
        PRIOR, "replace", "No previous imaging available.", "Compared with the previous {modality} of {date}.")
    assert rule.paragraph == "p1"                      # where the writer's FIXED line was
    assert [f.text for f in st.fixed_blocks].count("No previous imaging available.") == 1
    assert res.applied == [{"kind": "concept", "key": "comparison", "action": "rewritten"}]


def test_item_one_resolves_the_comparison_concept_both_ways():
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison", COMPARISON))).sheet
    rules = tcr.rules_in_scope(sheet)
    met, _, per = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert 'FIXED "Compared with the previous {modality} of {date}."' in met and per[0]["outcome"] == "applied"
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met and "RULE WHEN" not in not_met


def test_a_default_only_concept_gets_a_drop_rule_item_one_resolves():
    # D2: every concept is found by its condition; the default line is dropped when the dictation contradicts it
    led = _led(("concept", "comparison", {"use": True, "default": "No previous imaging available.", "when_met": ""}))
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    rule = next(r for r in _clean(sheet).rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target) == (PRIOR, "suppress", "No previous imaging available.")
    rules = tcr.rules_in_scope(sheet)
    met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert "No previous imaging available." not in met and "RULE WHEN" not in met
    not_met, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met


def test_contrast_takes_the_condition_opposite_its_default_either_way():
    usual_given = {"use": True, "default": "Following a contrast agent.", "when_met": "No contrast agent was given.",
                   "condition": NOT_GIVEN}
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_given)))
    tech = res.sheet.split("## Paragraph: Technique (TECHNIQUE)")[1].split("## Paragraph:")[0]
    assert ('FIXED "Following a contrast agent."\nRULE WHEN [context: the dictation states no contrast agent was given] '
            'REPLACE "Following a contrast agent." WITH "No contrast agent was given."') in tech
    assert res.applied[0]["action"] == "inserted"
    # a non-contrast protocol: the usual line is the no-agent wording; the other replaces it only when dictated
    usual_none = {"use": True, "default": "No contrast agent was given.", "when_met": "Following a contrast agent.",
                  "condition": GIVEN}
    sheet = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "contrast", usual_none))).sheet
    rules = tcr.rules_in_scope(sheet)
    assert [r.condition for r in rules] == [GIVEN]
    assert 'FIXED "No contrast agent was given."' in tcr.apply_rules(sheet, rules, {GIVEN: False})[0]
    assert 'FIXED "Following a contrast agent."' in tcr.apply_rules(sheet, rules, {GIVEN: True})[0]
    # switching the stored polarity rewrites the pair; nothing doubles
    back = tla.apply_ledger(sheet, _led(("concept", "contrast", usual_given)))
    assert len(tcr.rules_in_scope(back.sheet)) == 1 and back.applied[0]["action"] == "rewritten"


def test_a_when_met_only_concept_is_a_use_rule():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("concept", "limitation",
                                              {"use": True, "default": "", "when_met": "The study is limited by {cause}."})))
    rule = next(r for r in _clean(res.sheet).rules if r.condition_source == "context")
    assert rule.effect == "use" and rule.then_text == "The study is limited by {cause}."


def test_not_used_or_dictated_removes_the_concept_lines_and_a_writer_rule_on_its_target():
    sheet = LEDGER_SHEET.replace(
        'FIXED "No previous imaging available."\n',
        'FIXED "No previous imaging available."\n'
        'RULE WHEN [context: prior imaging is available for comparison] REPLACE "No previous imaging available." '
        'WITH "Compared with prior."\n')
    _clean(sheet)
    used = tla.apply_ledger(sheet, _led(("concept", "comparison", COMPARISON))).sheet
    assert "prior imaging is available" not in used               # the writer's own rule on the same line is gone
    assert len([r for r in _clean(used).rules if r.condition_source == "context"]) == 1
    for choice in ({"use": False}, {"use": False, "dictated": True}):
        gone = tla.apply_ledger(used, _led(("concept", "comparison", choice)))
        assert "No previous imaging available." not in gone.sheet and "RULE WHEN" not in gone.sheet
        assert gone.applied[0]["action"] == "removed"


def test_report_wide_lines_keep_their_own_section_suffix():
    sheet = LEDGER_SHEET.replace(
        'TERM PREFER "hepatic"\n',
        'TERM PREFER "hepatic"\nFIXED "No previous imaging available." | section: TECHNIQUE\n'
        'RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous '
        'imaging available." WITH "Compared with prior."\n').replace('FIXED "No previous imaging available."\n\n', '\n')
    _clean(sheet)
    res = tla.apply_ledger(sheet, _led(("concept", "comparison", {**COMPARISON, "when_met": "Compared with {date}."})))
    wide = res.sheet.split("## Report-wide")[1].split("## Paragraph")[0]
    assert 'FIXED "No previous imaging available." | section: TECHNIQUE\n' in wide
    assert 'WITH "Compared with {date}."\n' in wide                    # no section added to the rule line
    assert _clean(res.sheet) and tla.apply_ledger(res.sheet, _led(("concept", "comparison",
                                                                   {**COMPARISON, "when_met": "Compared with {date}."}))).changed == 0


def test_concepts_are_idempotent():
    led = _led(("concept", "comparison", COMPARISON),
               ("concept", "contrast", {"use": True, "default": "With a contrast agent.", "when_met": "",
                                        "condition": NOT_GIVEN}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and again.changed == 0


def test_fixed_remove_and_dictated_drop_the_line_and_rules_on_it():
    sheet = LEDGER_SHEET.replace(
        'FIXED "Axial images were acquired."\n',
        'FIXED "Axial images were acquired."\n'
        'RULE WHEN [context: the coronal series was not acquired] SUPPRESS "Axial images were acquired."\n')
    _clean(sheet)
    for keep in ("remove", "dictated"):
        res = tla.apply_ledger(sheet, _led(("fixed", "Axial images were acquired.", {"keep": keep})))
        st = _clean(res.sheet)
        assert "Axial images were acquired." not in [f.text for f in st.fixed_blocks]
        assert not [r for r in st.rules if r.condition_source == "context"]
        assert 'Opening: "Axial images were acquired."' in res.sheet       # prose is never rewritten


def test_fixed_always_on_a_missing_line_is_unmatched_not_guessed():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("fixed", "A line the sheet lacks.", {"keep": "always"})))
    assert res.sheet == LEDGER_SHEET and [e["key"] for e in res.unmatched] == ["A line the sheet lacks."]


def test_normal_rewrite_insert_and_remove():
    led = _led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}),
               ("normal", td.normal_key("Liver", "gallbladder"), {"text": "The gallbladder is unremarkable."}),
               ("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": ""}))
    res = tla.apply_ledger(LEDGER_SHEET, led)
    st = _clean(res.sheet)
    assert {(n.structure, n.text) for n in st.normals} == {("liver", "The liver is unremarkable."),
                                                           ("gallbladder", "The gallbladder is unremarkable.")}
    assert not st.negatives
    assert [a["action"] for a in res.applied] == ["rewritten", "inserted", "removed"]
    assert res.stale_quotes == ["The liver is normal in size."]      # the Voice block still quotes the old normal


def test_a_reworded_negative_stays_matched():
    key = td.negative_key("Liver", "No focal liver lesion.")
    led = _led(("normal", key, {"text": "No focal hepatic lesion."}))
    once = tla.apply_ledger(LEDGER_SHEET, led).sheet
    again = tla.apply_ledger(once, led)
    assert again.sheet == once and [n.text for n in _clean(once).negatives] == ["No focal hepatic lesion."]


def test_a_normal_in_a_missing_paragraph_is_unmatched():
    res = tla.apply_ledger(LEDGER_SHEET, _led(("normal", "Spleen :: spleen", {"text": "The spleen is normal."})))
    assert res.sheet == LEDGER_SHEET and len(res.unmatched) == 1


def test_an_edit_that_would_break_the_sheet_is_not_applied(monkeypatch):
    def broken(lines, st, entry):
        return [*lines, "NORMAL broken"], [{"kind": "normal", "key": entry["key"], "action": "inserted"}], [], []
    monkeypatch.setattr(tla, "_OPS", [("normal", broken)])
    res = tla.apply_ledger(LEDGER_SHEET, _led(("normal", "Liver :: liver", {"text": "The liver is fine."})))
    assert res.sheet == LEDGER_SHEET and len(res.failed) == 1 and not res.applied


def test_everything_together_is_idempotent_and_clean():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON),
               ("fixed", "Axial images were acquired.", {"keep": "remove"}),
               ("normal", td.normal_key("Liver", "gallbladder"), {"text": "The gallbladder is unremarkable."}))
    once = tla.apply_ledger(LEDGER_SHEET, led)
    _clean(once.sheet)
    assert not once.failed and not once.unmatched
    assert tla.apply_ledger(once.sheet, led).sheet == once.sheet


def test_a_negative_whose_wordings_are_both_gone_is_a_card_never_inserted():
    gone = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reword = _led(("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": "No focal hepatic lesion."}))
    res = tla.apply_ledger(gone, reword)
    assert res.sheet == gone and [e["key"] for e in res.unmatched] == ['Liver :: "No focal liver lesion."']
    remove = _led(("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": ""}))
    res = tla.apply_ledger(gone, remove)                                   # already gone: nothing to do, nothing added
    assert res.sheet == gone and not res.unmatched and res.changed == 0


def test_a_paragraph_name_used_twice_is_never_guessed():
    twice = LEDGER_SHEET.replace("## Paragraph: Impression (IMPRESSION)", "## Paragraph: Liver (IMPRESSION)")
    _clean(twice)
    res = tla.apply_ledger(twice, _led(("normal", "Liver :: liver", {"text": "The liver is unremarkable."})))
    assert res.sheet == twice and len(res.unmatched) == 1
    assert tla.observe(_clean(twice), "normal", "Liver :: liver") is None


def test_a_fixed_entry_on_a_concepts_line_is_skipped_not_fought_over():
    led = _led(("concept", "comparison", COMPARISON))
    led.append({"kind": "fixed", "key": "No previous imaging available.", "choice": {"keep": "remove"}, "by": "code",
                "at": "", "source": "default"})                       # a stored ledger from before the refusal
    once = tla.apply_ledger(LEDGER_SHEET, led)
    again = tla.apply_ledger(once.sheet, led)
    assert 'FIXED "No previous imaging available."' in once.sheet and again.sheet == once.sheet and again.changed == 0


def test_removing_a_fixed_entry_also_removes_a_use_rule_writing_it():
    sheet = LEDGER_SHEET.replace(
        'FIXED "Axial images were acquired."\n',
        'FIXED "Axial images were acquired."\nRULE WHEN [context: the coronal series was not acquired] USE '
        '"Coronal images were not acquired."\n')
    _clean(sheet)
    res = tla.apply_ledger(sheet, _led(("fixed", "Coronal images were not acquired.", {"keep": "remove"})))
    assert "Coronal images were not acquired." not in res.sheet and res.applied[0]["action"] == "removed"


def test_observe_reads_each_kind():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON))
    st = _clean(tla.apply_ledger(LEDGER_SHEET, led).sheet)
    assert tla.observe(st, "value", "lvef") == {"need": "every"}
    assert tla.observe(st, "value", "ECV") == {"need": "not_needed"}
    assert tla.observe(st, "concept", "comparison") == COMPARISON
    assert tla.observe(st, "concept", "contrast") == {"use": False, "default": "", "when_met": "", "condition": "",
                                                      "dictated": False}
    drop = _clean(tla.apply_ledger(LEDGER_SHEET, _led(("concept", "comparison",
                                                      {**COMPARISON, "when_met": ""}))).sheet)
    assert tla.observe(drop, "concept", "comparison") == {**COMPARISON, "when_met": ""}   # the drop rule is read too
    assert tla.observe(st, "fixed", "Axial images were acquired.") == {"keep": "always"}
    assert tla.observe(st, "normal", "Liver :: liver") == {"text": "The liver is normal in size."}
    assert tla.observe(st, "normal", "Liver :: gallbladder") == {"text": ""}
    assert tla.observe(st, "normal", "Spleen :: spleen") is None


def test_a_chat_rewrite_that_changes_a_decided_item_updates_the_ledger():
    led = _led(("value", "LVEF", {"need": "every"}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('LIST_MISSING ["LVEF"]', 'LIST_MISSING ["RVEF"]')
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert {(e["key"], e["choice"]["need"], e["source"]) for e in new} == {("LVEF", "not_needed", "chat"),
                                                                           ("RVEF", "every", "chat")}
    assert td.describe_change(changes[0]) == ("This changes something you confirmed: LVEF every report → "
                                              "not needed.")
    assert tla.apply_ledger(after, new).sheet == after                # the rewrite stands
    assert cards == []


def test_items_a_chat_rewrite_left_alone_keep_their_entry():
    led = _led(("value", "LVEF", {"need": "every"}), ("value", "ECV", {"need": "relevant"}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace("Opening: \"The liver\"", "Opening: \"The liver is described first\"")
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []


def test_no_value_entries_means_the_ledger_does_not_own_the_list():
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}))
    before = LEDGER_SHEET
    after = before.replace('TERM PREFER "hepatic"\n', 'TERM PREFER "hepatic"\nRULE WHEN [findings: any listed value '
                                                     'is not stated] LIST_MISSING ["A"] AT TOP | section: FINDINGS\n')
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []



def test_a_rewrite_that_drops_a_whole_decided_item_keeps_the_ledger_and_returns_a_card():
    led = _led(("value", "LVEF", {"need": "every"}), ("concept", "comparison", COMPARISON))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    lines = [ln for ln in before.split("\n") if "LIST_MISSING" not in ln and "previous" not in ln.lower()]
    after = "\n".join(lines)
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == []                                # D3: never folded in silently
    assert [c["id"] for c in cards] == ["value:lvef", "concept:comparison"]
    back = _clean(tla.apply_ledger(after, new).sheet)                 # the save writes the decided lines again
    assert tla.observe(back, "value", "LVEF") == {"need": "every"}
    assert tla.observe(back, "concept", "comparison") == COMPARISON


def test_a_reworded_concept_default_folds_into_the_ledger():
    led = _led(("concept", "comparison", COMPARISON))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('FIXED "No previous imaging available."', 'FIXED "No prior imaging."')
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert cards == [] and new[0]["choice"] == {**COMPARISON, "default": "No prior imaging."}
    assert new[0]["source"] == "chat" and td.describe_change(changes[0]) == (
        'This changes something you confirmed: Comparison with previous imaging "No previous imaging available." '
        '→ "No prior imaging.".')
    saved = tla.apply_ledger(after, new, before=before).sheet
    rule = next(r for r in _clean(saved).rules if r.condition_source == "context")
    assert rule.target == "No prior imaging." and "No previous imaging available." not in saved


def test_any_other_orphaned_concept_rule_keeps_the_ledger_and_returns_a_card():
    led = _led(("concept", "comparison", COMPARISON))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('FIXED "No previous imaging available."', 'FIXED "No prior imaging."').replace(
        'FIXED "Axial images were acquired."\n', "")                    # two lines gone, one added: not a reword
    new, changes, cards = tla.reconcile_chat(before, after, led)
    assert new == led and changes == [] and [c["id"] for c in cards] == ["concept:comparison"]
    res = tla.apply_ledger(after, new, before=before)
    assert "No prior imaging." not in res.sheet and 'FIXED "No previous imaging available."' in res.sheet
    assert [e["key"] for e in res.unmatched] == ["comparison"]


def test_without_a_before_sheet_the_line_beside_an_orphaned_rule_is_dropped_and_reported():
    led = _led(("concept", "comparison", COMPARISON))
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    res = tla.apply_ledger(sheet.replace('FIXED "No previous imaging available."', 'FIXED "No prior imaging."'), led)
    assert res.sheet == sheet and [e["key"] for e in res.unmatched] == ["comparison"]


def test_a_reworded_always_fixed_line_is_rekeyed_not_removed():
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}))
    after = LEDGER_SHEET.replace('FIXED "Axial images were acquired."', 'FIXED "Axial and coronal images were acquired."')
    new, changes, cards = tla.reconcile_chat(LEDGER_SHEET, after, led)
    assert [(e["key"], e["choice"], e["source"]) for e in new] == [
        ("Axial and coronal images were acquired.", {"keep": "always"}, "chat")] and cards == []
    assert td.describe_change(changes[0]) == ('This changes something you confirmed: "Axial images were acquired." '
                                              '→ "Axial and coronal images were acquired.".')
    assert tla.apply_ledger(after, new).sheet == after


def test_a_quoted_normal_label_is_a_normal_key():
    sheet = LEDGER_SHEET.replace('COVERS ["liver"', 'COVERS ["ROTATOR CUFF"').replace(
        "NORMAL [liver]", 'NORMAL ["ROTATOR CUFF"]')
    st = _clean(sheet)
    key = td.normal_key("Liver", st.normals[0].structure)
    assert key == "Liver :: ROTATOR CUFF"
    assert tla.observe(st, "normal", key) == {"text": "The liver is normal in size."}
    res = tla.apply_ledger(sheet, _led(("normal", key, {"text": "The cuff is intact."})))
    assert 'NORMAL ["ROTATOR CUFF"] "The cuff is intact."' in res.sheet and len(_clean(res.sheet).normals) == 1


def test_removing_a_negative_the_sheet_reworded_is_unmatched_not_kept():
    sheet = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    res = tla.apply_ledger(sheet, _led(("normal", td.negative_key("Liver", "No focal liver lesion."), {"text": ""})))
    assert res.sheet == sheet and res.changed == 0
    assert [e["key"] for e in res.unmatched] == ['Liver :: "No focal liver lesion."']
