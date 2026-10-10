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


import pytest


@pytest.mark.parametrize("text,expected", [
    ("e.g. lungs clear.", ["e.g. lungs clear."]),
    ("vs. prior study.", ["vs. prior study."]),
    ("approx. 3 cm.", ["approx. 3 cm."]),
    ("i.e. normal.", ["i.e. normal."]),
    ("1. Liver normal. 2. Spleen ok.", ["1. Liver normal.", "2. Spleen ok."]),
    ("Clear. Liver normal.", ["Clear.", "Liver normal."]),
    ("None. Spleen normal.", ["None.", "Spleen normal."]),
    ("Dr. Smith noted.", ["Dr.", "Smith noted."]),  # accepted: a capital follows
    ("Measures 3.2 cm. Stable.", ["Measures 3.2 cm.", "Stable."]),
    ("Disc bulge at L4/5. Mild stenosis.", ["Disc bulge at L4/5.", "Mild stenosis."]),
])
def test_abbreviation_and_list_fragments_join_the_next_sentence(text, expected):
    assert sentences(text) == expected


def test_forward_link_is_cut():
    prev = [StackUnit(id=0, text="A mass.", group="Liver"),
            StackUnit(id=1, text="It measures 2 cm.", group="Liver", attach_to=0)]
    units, _ = match_units("It measures 2 cm. A mass.", prev)
    assert units[0].attach_to is None


def test_sticky_match_keeps_all_label_fields_and_does_not_alias():
    from rapid_reports_ai.hybrid_stack.units import PartOut
    prev = [StackUnit(id=0, text="A mass.", group="Liver", structure="s", pinned=True,
                      covers=["Liver"], parts=[PartOut(text="A", group="Liver")])]
    units, _ = match_units("A mass.", prev)
    u = units[0]
    assert (u.group, u.structure, u.pinned, u.covers) == ("Liver", "s", True, ["Liver"])
    assert u.parts and u.parts[0].group == "Liver"
    u.covers.append("x")
    u.parts[0].group = "Y"
    assert prev[0].covers == ["Liver"] and prev[0].parts[0].group == "Liver"


def test_duplicate_previous_ids_first_wins():
    prev = [StackUnit(id=0, text="Liver normal.", group="First"), StackUnit(id=0, text="Spleen normal.", group="Second")]
    units, new = match_units("Liver normal. Spleen normal.", prev)
    assert units[0].group == "First" and units[1].group is None and new == [1]
