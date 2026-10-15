"""apply_ledger: the ledger applied to a grammar sheet by code (Rules-step spec, "Decision ledger")."""
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_ledger_apply as tla
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import GOOD, HABIT_SHEET, LEDGER_SHEET


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
    met, _, _, per = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert 'FIXED "Compared with the previous {modality} of {date}."' in met and per[0]["outcome"] == "applied"
    not_met, _, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
    assert 'FIXED "No previous imaging available."' in not_met and "RULE WHEN" not in not_met


def test_a_default_only_concept_gets_a_drop_rule_item_one_resolves():
    # D2: every concept is found by its condition; the default line is dropped when the dictation contradicts it
    led = _led(("concept", "comparison", {"use": True, "default": "No previous imaging available.", "when_met": ""}))
    sheet = tla.apply_ledger(LEDGER_SHEET, led).sheet
    rule = next(r for r in _clean(sheet).rules if r.condition_source == "context")
    assert (rule.condition, rule.effect, rule.target) == (PRIOR, "suppress", "No previous imaging available.")
    rules = tcr.rules_in_scope(sheet)
    met, _, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: True})
    assert "No previous imaging available." not in met and "RULE WHEN" not in met
    not_met, _, _, _ = tcr.apply_rules(sheet, rules, {PRIOR: False})
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


def test_a_paragraph_that_comes_back_keeps_its_entries_provenance():
    led, _ = td.set_decision([], "normal", "Liver :: liver", {"text": "The liver is normal in size."},
                             source="default", by="code", at="t")
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatic (FINDINGS)")
    for before, after in ((renamed, LEDGER_SHEET), (LEDGER_SHEET, renamed)):
        new, changes, cards = tla.reconcile_chat(before, after, led)
        assert new == led and changes == [] and cards == []


def test_undoing_a_value_change_puts_the_value_back_in_its_place():
    led = _led(("value", "A", {"need": "every"}), ("value", "B", {"need": "every"}), ("value", "C", {"need": "every"}))
    before = tla.apply_ledger(LEDGER_SHEET, led).sheet
    after = before.replace('LIST_MISSING ["A" | "B" | "C"]', 'LIST_MISSING ["A" | "C"]')
    new, changes, _ = tla.reconcile_chat(before, after, led)
    undone = td.undo_change(new, changes[0])
    assert 'LIST_MISSING ["A" | "B" | "C"]' in tla.apply_ledger(after, undone).sheet


# ── habit (spec 2026-10-13-findings-triggered-rows-design) ──
HK = "Liver :: a focal liver abnormality is reported"
HASK = {"mode": "ask", "question": "Extension into the gallbladder?",
        "yes": "The abnormality extends into the gallbladder.", "no": "No extension into the gallbladder."}
ASK_LINE = ('RULE WHEN [findings: a focal liver abnormality is reported] ASK "Extension into the gallbladder?" '
            'YES "The abnormality extends into the gallbladder." NO "No extension into the gallbladder."')
STATE_LINE = 'NEGATIVE "No extension into the gallbladder." WHEN [findings: a focal liver abnormality is reported]'


def _liver(sheet):
    return sheet.split("## Paragraph: Liver (FINDINGS)")[1].split("## Paragraph: Lower")[0]


def test_habit_fixture_is_clean():
    _clean(HABIT_SHEET)


def test_a_habit_is_inserted_at_the_end_of_its_paragraph_and_read_back():
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", HK, HASK)))
    st = _clean(res.sheet)
    assert res.applied == [{"kind": "habit", "key": HK, "action": "inserted"}]
    assert _liver(res.sheet).rstrip().endswith(ASK_LINE)
    assert tla.observe(st, "habit", HK) == HASK
    again = tla.apply_ledger(res.sheet, _led(("habit", HK, HASK)))
    assert again.sheet == res.sheet and again.applied == [{"kind": "habit", "key": HK, "action": "kept"}]


def test_state_rewrites_the_question_and_removed_takes_it_out():
    asked = tla.apply_ledger(HABIT_SHEET, _led(("habit", HK, HASK))).sheet
    stated = tla.apply_ledger(asked, _led(("habit", HK, {**HASK, "mode": "state"})))
    assert stated.applied[0]["action"] == "rewritten" and STATE_LINE in stated.sheet and " ASK " not in stated.sheet
    assert tla.observe(_clean(stated.sheet), "habit", HK) == {
        "mode": "state", "question": "", "yes": "", "no": "No extension into the gallbladder."}
    gone = tla.apply_ledger(stated.sheet, _led(("habit", HK, {**HASK, "mode": "removed"})))
    assert gone.applied[0]["action"] == "removed" and "WHEN [findings: a focal" not in gone.sheet
    assert tla.observe(_clean(gone.sheet), "habit", HK)["mode"] == "removed"


def test_a_habit_finds_its_paragraph_by_a_covered_structure_else_it_is_unmatched():
    key = "delta :: a focal delta abnormality is reported"
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", key, {"mode": "state", "no": "No delta extension."})))
    lower = res.sheet.split("## Paragraph: Lower (FINDINGS)")[1]
    assert 'NEGATIVE "No delta extension." WHEN [findings: a focal delta abnormality is reported]' in lower
    miss = tla.apply_ledger(HABIT_SHEET, _led(("habit", "Nowhere :: a focal liver abnormality is reported", HASK)))
    assert miss.sheet == HABIT_SHEET and [e["key"] for e in miss.unmatched] == [
        "Nowhere :: a focal liver abnormality is reported"]


def test_a_habit_line_the_ledger_does_not_hold_stays_inactive_and_pending():
    # Hassan H3: never stripped silently; inactive until a card at the next review confirms it
    stray = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n',
                                'NEGATIVE "No focal liver lesion."\n' + STATE_LINE + "\n")
    st = _clean(stray)
    res = tla.apply_ledger(stray, [])
    assert res.sheet == stray and res.applied == []
    assert res.pending == [{"kind": "habit", "key": HK, "choice": {
        "mode": "state", "question": "", "yes": "", "no": "No extension into the gallbladder."}}]
    assert tla.confirmed_habits(st, []) == set()
    led = _led(("habit", HK, {**HASK, "mode": "state"}))
    confirmed = tla.apply_ledger(stray, led)
    assert confirmed.sheet == stray and confirmed.pending == []
    liver = next(p.id for p in st.paragraphs if p.name == "Liver")
    assert tla.confirmed_habits(st, led) == {(liver, "a focal liver abnormality is reported")}
    removed = _led(("habit", HK, {**HASK, "mode": "removed"}))   # "Not needed" on its card
    gone = tla.apply_ledger(stray, removed)
    assert STATE_LINE not in gone.sheet and gone.pending == []
    assert tla.confirmed_habits(_clean(gone.sheet), removed) == set()


def test_a_paragraph_negative_entry_never_reads_a_required_statement():
    sheet = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n',
                                'NEGATIVE "No focal liver lesion."\n'
                                'NEGATIVE "No focal liver lesion." WHEN [findings: a focal liver abnormality is reported]\n')
    st = _clean(sheet)
    key = td.negative_key("Liver", "No focal liver lesion.")
    assert tla.observe(st, "normal", key) == {"text": "No focal liver lesion."}
    no_plain = sheet.replace('NEGATIVE "No focal liver lesion."\nNEGATIVE', "NEGATIVE")
    assert tla.observe(_clean(no_plain), "normal", key) == {"text": ""}


def test_a_habit_the_grammar_refuses_is_not_saved_and_comes_back_as_a_card():
    key = "Technique :: a focal liver abnormality is reported"   # a technique paragraph: NOT_LEAN there
    res = tla.apply_ledger(HABIT_SHEET, _led(("habit", key, HASK)))
    assert res.sheet == HABIT_SHEET
    assert [e["key"] for e in res.failed] == [key] and [e["key"] for e in res.unmatched] == [key]


def test_a_chat_rewrite_that_drops_a_confirmed_habit_is_kept_and_asked():
    led = _led(("habit", HK, HASK))
    before = tla.apply_ledger(HABIT_SHEET, led).sheet
    after = before.replace(ASK_LINE + "\n", "").replace(ASK_LINE, "")
    out, changes, cards = tla.reconcile_chat(before, after, led)
    assert out == led and changes == [] and [c["kind"] for c in cards] == ["habit"]
    restated = before.replace(ASK_LINE, STATE_LINE)
    out, changes, cards = tla.reconcile_chat(before, restated, led)
    assert cards == [] and out[0]["choice"] == {**HASK, "mode": "state"} and out[0]["source"] == "chat"


def test_a_chat_reword_of_a_confirmed_habits_condition_is_folded_as_a_reword():
    led = _led(("habit", HK, HASK))
    before = tla.apply_ledger(HABIT_SHEET, led).sheet
    new_cond = "a focal liver mass abnormality is reported"
    after = before.replace("[findings: a focal liver abnormality is reported]", f"[findings: {new_cond}]")
    out, changes, cards = tla.reconcile_chat(before, after, led)
    assert cards == [] and len(changes) == 1 and changes[0]["old"]["key"] == HK
    assert [(e["key"], e["choice"], e["source"]) for e in out] == [(f"Liver :: {new_cond}", HASK, "chat")]
    applied = tla.apply_ledger(after, out)
    assert applied.sheet == after and applied.pending == []   # one line, not two
    reworded_q = after.replace('"Extension into the gallbladder?"', '"Gallbladder extension?"')
    out, _, _ = tla.reconcile_chat(before, reworded_q, led)   # condition and question reworded together
    assert out[0]["key"] == f"Liver :: {new_cond}" and out[0]["choice"]["question"] == "Gallbladder extension?"


def test_editing_a_pending_habit_card_leaves_exactly_one_habit_line():
    # the Rules step sends the old key as removed, then the reworded one (frontend cards.changesFor)
    stray = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."\n',
                                'NEGATIVE "No focal liver lesion."\n' + STATE_LINE + "\n")
    new_key = "Liver :: a focal liver abnormality in the left part is reported"
    changes = [{"kind": "habit", "key": HK, "choice": {"mode": "removed", "question": "", "yes": "",
                                                        "no": "No extension into the gallbladder."}},
               {"kind": "habit", "key": new_key, "choice": {"mode": "state", "question": "", "yes": "",
                                                             "no": "No extension into the gallbladder."}}]
    led, errors = td.ledger_from_changes(changes, source="first_use_review")
    assert errors == []
    res = tla.apply_ledger(stray, led)
    st = _clean(res.sheet)
    habit_lines = [n for n in st.negatives if n.condition] + [r for r in st.rules if r.effect == "ask"]
    assert [(u.condition) for u in habit_lines] == ["a focal liver abnormality in the left part is reported"]
    assert res.pending == []


# ── stable line IDs: uid first, key second (spec 2026-10-15-stable-line-ids-design, "Ledger changes") ───────────

from rapid_reports_ai import template_line_registry as tlr

NEG = td.negative_key("Liver", "No focal liver lesion.")
SUPPRESS = 'RULE WHEN [context: the dictation states contrast was given] SUPPRESS "No focal liver lesion."'


def _reg(sheet):
    return tlr.rebind(None, _clean(sheet), now="T")[0]


def _uid(sheet, reg, ref):
    return tlr.uids_for(_clean(sheet), reg)[ref]


def _with_uid(entry, uid):
    return {**entry, "uid": uid}


def test_registry_none_is_todays_key_matching():
    led = _led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}))
    a, b = tla.apply_ledger(LEDGER_SHEET, led), tla.apply_ledger(LEDGER_SHEET, led, registry=None)
    assert (a.sheet, a.applied, a.unmatched) == (b.sheet, b.applied, b.unmatched)
    assert b.carried == {} and b.satisfied == [] and b.rekeyed == [] and b.ledger == led


def test_uid_first_finds_a_negative_the_writer_reworded_and_rekeys_it():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal liver lesion."}))[0], uid)]
    rebuilt = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    assert tla.apply_ledger(rebuilt, led).unmatched == led                 # today: lost, a card
    res = tla.apply_ledger(rebuilt, led, registry=reg)
    assert not res.unmatched and 'NEGATIVE "No focal liver lesion."' in res.sheet
    assert res.ledger[0]["key"] == 'Liver :: "There is no focal liver lesion"' and res.ledger[0]["uid"] == uid
    assert res.rekeyed == [{"kind": "normal", "uid": uid, "old": NEG, "new": res.ledger[0]["key"]}]
    assert res.carried == {uid: 'NEGATIVE "No focal liver lesion."'}


def test_across_a_paragraph_rename_a_normal_entry_follows_only_an_unchanged_line():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "m0")
    led = [_with_uid(_led(("normal", td.normal_key("Liver", "liver"), {"text": "The liver is unremarkable."}))[0], uid)]
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    assert tla.apply_ledger(renamed, led).unmatched == led                 # today: paragraph not found
    res = tla.apply_ledger(renamed, led, registry=reg)                     # the line unchanged: its uid finds it
    assert 'NORMAL [liver] "The liver is unremarkable."' in res.sheet and not res.unmatched
    assert res.ledger[0]["key"] == "Hepatobiliary :: liver" and uid in res.carried
    reworded = renamed.replace('"The liver is normal in size."\nNEGATIVE', '"Normal liver size."\nNEGATIVE')
    res2 = tla.apply_ledger(reworded, led, registry=reg)                   # renamed and reworded: asked again
    assert res2.unmatched == led and res2.sheet == reworded


def test_a_uid_the_registry_does_not_know_is_no_uid():
    reg = _reg(LEDGER_SHEET)
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal hepatic lesion."}))[0], "g_zzzzzz")]
    res = tla.apply_ledger(LEDGER_SHEET, led, registry=reg)
    assert 'NEGATIVE "No focal hepatic lesion."' in res.sheet and res.rekeyed == []


def test_carried_includes_the_context_rule_a_normal_rewrite_retargets():
    sheet = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', f'NEGATIVE "No focal liver lesion."\n{SUPPRESS}\n')
    reg = _reg(sheet)
    neg, rule = _uid(sheet, reg, "n0"), _uid(sheet, reg, "r0")
    led = [_with_uid(_led(("normal", NEG, {"text": "No focal hepatic lesion."}))[0], neg)]
    res = tla.apply_ledger(sheet, led, registry=reg)
    assert res.carried == {neg: 'NEGATIVE "No focal hepatic lesion."',
                           rule: SUPPRESS.replace("liver lesion", "hepatic lesion")}
    _, rep = tlr.rebind(reg, _clean(res.sheet), res.carried, now="T")
    assert sorted(rep["carried"]) == sorted([neg, rule]) and rep["gone"] == [] and rep["new"] == []


def test_a_line_edited_by_two_steps_carries_its_final_text(monkeypatch):
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    first, second = 'NEGATIVE "No focal hepatic lesion."', 'NEGATIVE "No hepatic lesion."'

    def step(old, new):
        def op(lines, st, entry):
            out = [new if ln == old else ln for ln in lines]
            return out, [{"kind": entry["kind"], "key": entry["key"], "action": "rewritten"}], [], [], [(old, new)]
        return op
    monkeypatch.setattr(tla, "_OPS", [("fixed", step('NEGATIVE "No focal liver lesion."', first)),
                                      ("normal", step(first, second))])
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}),
               ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size."}))
    res = tla.apply_ledger(LEDGER_SHEET, led, registry=reg)
    assert res.carried == {uid: second}


def test_a_carried_line_deleted_later_never_moves_its_uid_to_an_identical_line_elsewhere(monkeypatch):
    other, mine = 'NEGATIVE "No hepatic lesion."', 'NEGATIVE "No focal liver lesion."'
    sheet = HABIT_SHEET.replace('NORMAL [delta] "Delta is normal."', f'NORMAL [delta] "Delta is normal."\n{other}')
    reg = _reg(sheet)
    liver, lower = _uid(sheet, reg, "n0"), _uid(sheet, reg, "n1")

    def rewrite(lines, st, entry):      # step 1: the Liver negative takes the Lower negative's exact text
        out = list(lines)
        out[out.index(mine)] = other
        return out, [{"kind": entry["kind"], "key": entry["key"], "action": "rewritten"}], [], [], [(mine, other)]

    def delete(lines, st, entry):       # step 2: the first copy (the Liver one) is removed
        i = lines.index(other)
        return lines[:i] + lines[i + 1:], [{"kind": entry["kind"], "key": entry["key"], "action": "removed"}], [], []
    monkeypatch.setattr(tla, "_OPS", [("fixed", rewrite), ("normal", delete)])
    led = _led(("fixed", "Axial images were acquired.", {"keep": "always"}),
               ("normal", td.normal_key("Liver", "liver"), {"text": "The liver is normal in size."}))
    res = tla.apply_ledger(sheet, led, registry=reg)
    assert res.carried == {liver: other}
    st = _clean(res.sheet)
    assert tla._uid_map(st, reg, res.carried)["n0"] == lower        # the Lower line keeps its own uid
    _, rep = tlr.rebind(reg, st, res.carried, now="T")
    assert liver in rep["gone"] and lower in rep["exact"] and not rep["carried"]


def test_a_removal_is_satisfied_only_when_its_line_is_shown_absent():
    reg = _reg(LEDGER_SHEET)
    uid = _uid(LEDGER_SHEET, reg, "n0")
    removal = _led(("normal", NEG, {"text": ""}))[0]
    reworded = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    # no uid: nothing shows the line is gone (a reworded negative) -> a card, as today
    assert [e["key"] for e in tla.apply_ledger(reworded, [removal], registry=reg).unmatched] == [NEG]
    # its uid names no unit of this sheet: the line is gone -> satisfied, never a card
    res = tla.apply_ledger(reworded, [_with_uid(removal, uid)], registry=reg)
    assert res.sheet == reworded and res.unmatched == [] and [e["key"] for e in res.satisfied] == [NEG]
    # paragraph renamed with the negative still there, no uid: a card (never silently satisfied)
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Abdomen (FINDINGS)")
    assert [e["key"] for e in tla.apply_ledger(renamed, [removal], registry=_reg(renamed)).unmatched] == [NEG]
    # the same rename with the uid: the line is found through it and removed
    out = tla.apply_ledger(renamed, [_with_uid(removal, uid)], registry=reg)
    assert 'NEGATIVE "No focal liver lesion."' not in out.sheet and out.unmatched == []


def test_is_removal():
    assert tla.is_removal({"kind": "fixed", "choice": {"keep": "remove"}})
    assert tla.is_removal({"kind": "normal", "choice": {"text": ""}})
    assert not tla.is_removal({"kind": "normal", "choice": {"text": "x"}})
    assert not tla.is_removal({"kind": "habit", "choice": {"mode": "removed"}})
