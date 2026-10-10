from pathlib import Path

from rapid_reports_ai.hybrid_stack.pills import derived_pills
from rapid_reports_ai.hybrid_stack.schemas import OTHER, Region
from rapid_reports_ai.hybrid_stack.template import template_regions
from rapid_reports_ai.hybrid_stack.units import StackUnit
from rapid_reports_ai.template_sheet_grammar import parse_sheet

FIX = Path(__file__).parent / "fixtures" / "template_pipeline" / "lean_cmr.md"


def test_pills_follow_covers_in_region_order_and_skip_other():
    regions = [Region(name="Liver", includes="l"), Region(name="Kidneys", includes="k"), Region(name=OTHER, includes="o")]
    units = [StackUnit(id=0, text="a", covers=["Kidneys", OTHER]), StackUnit(id=1, text="b", covers=["Liver"])]
    assert derived_pills(units, regions) == ["Liver", "Kidneys"]


def test_template_regions_are_findings_paragraphs_with_covers():
    st = parse_sheet(FIX.read_text(), mode="template").structure
    regions = template_regions(st)
    names = [r.name for r in regions]
    assert names[:2] == ["Left Ventricle", "Right Ventricle"]
    assert "Late Gadolinium Enhancement" in names and names[-1] == OTHER
    assert "Clinical Details" not in names and "Conclusion" not in names
    assert "myocardium" in next(r.includes for r in regions if r.name == "Tissue Characterisation")
