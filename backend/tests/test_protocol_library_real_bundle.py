"""Checks against the real (private) bundle. Skipped in CI and whenever RR_PROTOCOL_LIBRARY_PATH is unset."""
import os
import re

import pytest

from rapid_reports_ai.hybrid_stack.protocol_library import bundle as PB
from rapid_reports_ai.hybrid_stack.protocol_library import compose as C
from rapid_reports_ai.hybrid_stack.protocol_library import match as M
from rapid_reports_ai.hybrid_stack.protocol_library.compose import STANDARD_SECTIONS
from rapid_reports_ai.quick_report_brief import stack_fallback

pytestmark = pytest.mark.skipif(not os.environ.get("RR_PROTOCOL_LIBRARY_PATH"), reason="private bundle not available")
SEX_ONLY = {"Pelvic organs"}


@pytest.fixture(scope="module")
def b():
    PB.reset_cache()
    bundle = PB.get_bundle()
    assert bundle is not None, "bundle failed to load; see the log"
    return bundle


def test_every_pick_resolves_and_composes(b):
    bad = []
    for e in b.entries:
        lat = "left" if e.laterality == "required" else None
        for ph in e.phase_sets():
            res = C.resolve(b, e.id, ph, lat)
            s = C.compose_sheet(b, res)
            kd = b.keys[e.sheet_key]
            grouped = {r.name for r in kd.regions if r.level_group} | set(kd.level_groups) \
                | {n for v in kd.level_groups.values() for n in v}
            missing = [r.name for r in res.regions if not r.quiet and r.name != "Other findings"
                       and r.name not in s.region_normals and r.name not in SEX_ONLY and r.name not in grouped]
            if missing:   # every non-quiet region has a normal; a region with none is derived quiet
                bad.append((e.id, ph, missing[:4]))
            brief = stack_fallback(s.markdown, "", []).text
            assert STANDARD_SECTIONS in brief and "Section rules" in brief and "Technique statement" in brief, e.id
            assert f"- **Sections:** {STANDARD_SECTIONS}" in s.markdown.splitlines(), (e.id, ph)
            assert s.markdown.count("## Structural Pattern") == 1 and "- **Section rules:**" in s.markdown
            assert STANDARD_SECTIONS.endswith("; Findings; Conclusion") and C.CONCLUSION_RULE in brief, e.id
            sweep = [ln for ln in s.markdown.splitlines() if ln.startswith("- **Sweep order:**")]
            want = " → ".join(r.name for r in res.regions if not r.quiet and r.name != "Other findings")
            assert sweep == [f"- **Sweep order:** {want}"], (e.id, ph, sweep)
            assert sweep[0] in brief, e.id
            tech = [ln for ln in s.markdown.splitlines() if ln.startswith("- **Technique statement:**")]
            assert len(tech) == 1, (e.id, ph)
            t = tech[0].removeprefix("- **Technique statement:** ")
            assert t.endswith(".") and " with " not in t and "contrast contrast" not in t, (e.id, ph, t)
            assert not re.search(r"(?i)\b(?:with|without)\s+(?:[\w-]+\s+){0,2}contrast\b.*\b(?:with|without|following)\b", t), t
            enhanced = C.effective_agent(e, ph) != "none"
            if e.modality.upper() in ("MR", "MRI"):
                assert t.startswith("Multiplanar multisequence "), (e.id, ph, t)
                assert (" following " in t) == enhanced, (e.id, ph, t)
                assert "without" not in t and "phase" not in t, (e.id, ph, t)
            else:
                assert t.startswith("CT "), (e.id, ph, t)
                if enhanced:
                    assert " following " in t and "without" not in t, (e.id, ph, t)
                    if ph:
                        assert re.search(r": .+ phases?\.$", t), (e.id, ph, t)
                else:
                    assert t.endswith(" without intravenous contrast."), (e.id, ph, t)
            if lat:
                assert lat in t, (e.id, ph, t)
            if ph:
                mod = [ln for ln in s.markdown.splitlines() if ln.startswith("- **Modality:**")]
                assert len(mod) == 1, (e.id, ph)
                if set(ph) <= C.UNENHANCED:
                    assert "without contrast" in mod[0] and " with " not in mod[0].replace("without", ""), (e.id, ph)
                else:
                    assert "without contrast" not in mod[0] and " with " in mod[0], (e.id, ph)
    assert not bad, bad[:10]


def test_display_names_find_themselves(b):
    misses = [e.id for e in b.entries if e.id not in [o.id for _, o in M.local_search(b, e.display_name, 3)]]
    assert len(misses) <= len(b.entries) // 50, misses[:10]


def test_regions_with_no_normal_are_derived_quiet(b):
    """MDWBN (default phases: a limited DWI study) and MIRCA|t2star (liver and myocardial iron only) leave regions
    with no normal: they are quiet (no pill, no assumed normal), not listed as unfilled checklist regions."""
    for entry_id, ph in (("MDWBN", None), ("MIRCA", ["t2star"])):
        e = b.entry(entry_id)
        res = C.resolve(b, entry_id, ph, "left" if e.laterality == "required" else None)
        declared = {r.name for r in b.keys[e.sheet_key].regions if r.quiet}
        derived = [q for q in res.quiet if q not in declared]
        assert derived, (entry_id, ph)
        assert not set(derived) & set(C.compose_sheet(b, res).region_normals), (entry_id, ph)
