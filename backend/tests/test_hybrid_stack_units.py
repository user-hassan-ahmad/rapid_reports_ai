from rapid_reports_ai.hybrid_stack.units import StackUnit, match_units, sentences


def test_split_keeps_decimals_and_breaks_lines():
    assert sentences("A 5.2 cm mass. It is new.\nNo effusion.") == ["A 5.2 cm mass.", "It is new.", "No effusion."]


def test_new_text_gives_new_units():
    units, new = match_units("Liver normal. Spleen normal.", [])
    assert [u.text for u in units] == ["Liver normal.", "Spleen normal."] and new == [0, 1]


def test_sticky_keeps_placement_and_remaps_links():
    prev = [StackUnit(id=0, text="A mass.", group="Liver"),
            StackUnit(id=1, text="It measures 2 cm.", group="Liver", attach_to=0)]
    units, new = match_units("Technique line. A mass. It measures 2 cm.", prev)
    assert new == [0]
    assert units[1].group == "Liver" and units[1].id == 1
    assert units[2].attach_to == 1


def test_link_to_a_removed_sentence_is_cut():
    prev = [StackUnit(id=0, text="A mass.", group="Liver"),
            StackUnit(id=1, text="It measures 2 cm.", group="Liver", attach_to=0)]
    units, new = match_units("It measures 2 cm.", prev)
    assert units[0].attach_to is None and new == []


def test_heading_only_sentences_are_flagged():
    units, _ = match_units("Conclusion. Acute appendicitis.", [])
    assert units[0].heading is True and units[1].heading is False
