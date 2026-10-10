from rapid_reports_ai.hybrid_stack.grouper import Part, Placement, apply_placements, valid_parts
from rapid_reports_ai.hybrid_stack.units import StackUnit

GROUPS = ["Technique", "Liver", "Kidneys", "Other findings", "General", "Conclusion"]


def _units(*texts):
    return [StackUnit(id=i, text=t) for i, t in enumerate(texts)]


def test_parts_must_cover_the_sentence_exactly():
    s = "Kidneys are normal, and there is a 3 cm liver cyst."
    assert valid_parts(s, [Part(text="Kidneys are normal,", group="Kidneys"),
                           Part(text="and there is a 3 cm liver cyst.", group="Liver")])
    assert not valid_parts(s, [Part(text="Kidneys are normal", group="Kidneys"),
                               Part(text="there is a 3 cm liver cyst.", group="Liver")])  # ", and" dropped
    assert not valid_parts(s, [Part(text=s, group="Kidneys")])  # one part is not a split


def test_attached_sentence_takes_parent_group_and_covers_are_filtered():
    units = _units("A liver lesion.", "It measures 2 cm.")
    problems = apply_placements(units, [
        Placement(id=0, group="Liver", structure="liver", covers=["Liver", "General", "Nope"]),
        Placement(id=1, group="Kidneys", attach_to=0, covers=["Liver"]),
    ], [0, 1], GROUPS)
    assert units[0].covers == ["Liver"]
    assert units[1].group == "Liver" and units[1].attach_to == 0
    assert problems == []


def test_unknown_group_and_missing_placement_go_to_general():
    units = _units("One.", "Two.")
    problems = apply_placements(units, [Placement(id=0, group="Spleen")], [0, 1], GROUPS)
    assert units[0].group == "General" and units[1].group == "General"
    assert len(problems) == 2


def test_forward_or_self_link_is_cut():
    units = _units("One.", "Two.")
    apply_placements(units, [Placement(id=0, group="Liver", attach_to=1), Placement(id=1, group="Liver", attach_to=1)],
                     [0, 1], GROUPS)
    assert units[0].attach_to is None and units[1].attach_to is None


def test_split_into_one_group_is_not_a_split():
    units = _units("Liver and spleen normal.")
    apply_placements(units, [Placement(id=0, group="Liver", parts=[Part(text="Liver", group="Liver"),
                                                                   Part(text="and spleen normal.", group="Liver")])],
                     [0], GROUPS)
    assert units[0].parts is None


def test_placements_for_old_or_pinned_units_are_ignored():
    units = [StackUnit(id=0, text="Old.", group="Liver", pinned=True), StackUnit(id=1, text="New.")]
    apply_placements(units, [Placement(id=0, group="Kidneys"), Placement(id=1, group="Kidneys")], [1], GROUPS)
    assert units[0].group == "Liver" and units[1].group == "Kidneys"
