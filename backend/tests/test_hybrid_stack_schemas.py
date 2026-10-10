from rapid_reports_ai.hybrid_stack import schemas as s


def test_every_family_resolves_with_unique_names_and_ends_with_other():
    for fam in list(s.library()["families"]):
        names = [r.name for r in s.family_regions(fam)]
        assert len(names) == len(set(n.lower() for n in names)), fam
        assert names[-1] == s.OTHER, fam


def test_levels_expand():
    names = [r.name for r in s.family_regions("lumbar_spine")]
    assert "L4/5" in names and "L5/S1" in names


def test_generic_is_not_offered_as_a_choice():
    assert s.GENERIC_FAMILY not in s.family_keys()
    assert "abdomen_pelvis" in s.family_keys()


def test_groups_and_pills():
    regions = s.family_regions("knee")
    groups = s.groups_for(regions)
    assert groups[0] == s.TECHNIQUE and groups[-2:] == [s.GENERAL, s.CONCLUSION]
    assert s.OTHER not in s.pill_regions(regions)


def test_scan_key_normalises():
    assert s.scan_key("  MRI   Left  Ankle ") == "mri left ankle"
