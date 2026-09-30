"""Save-time structure: verification and the coverage gate (spec §2)."""
from __future__ import annotations

import pathlib

from rapid_reports_ai import template_sheet_structure as tss

SHEET = (pathlib.Path(__file__).parent / "fixtures" / "template_sheet.md").read_text()
IF_SUPPRESS = '- IF [pneumoperitoneum is present] THEN suppress "No pneumoperitoneum." AND replace with "Free intra-abdominal air is present."'


def good_draft() -> tss.StructureDraft:
    return tss.StructureDraft(
        sections=[{"name": "CLINICAL HISTORY", "role": "history", "header": "CLINICAL HISTORY", "order": 0},
                  {"name": "FINDINGS", "role": "findings", "header": None, "order": 1},
                  {"name": "IMPRESSION", "role": "impression", "header": "Impression", "order": 2}],
        paragraphs=[{"id": "p0", "section": "FINDINGS", "name": "Primary Pathology Paragraph"}],
        rules=[{"id": "r0", "section": "FINDINGS", "paragraph": "p0", "condition": "The dictated findings report inflammatory morphology",
                "condition_source": "findings", "effect": "append", "then_text": "consistent with {diagnosis}.",
                "source_lines": ['- IF [inflammatory morphology] THEN append "consistent with {diagnosis}."']},
               {"id": "r1", "section": "FINDINGS", "paragraph": "p0", "condition": "The dictated findings report pneumoperitoneum",
                "condition_source": "findings", "effect": "replace", "target": "No pneumoperitoneum.",
                "then_text": "Free intra-abdominal air is present.", "source_lines": [IF_SUPPRESS]},
               {"id": "r2", "section": "FINDINGS", "paragraph": "", "condition": "The clinical context is oncology",
                "condition_source": "context", "effect": "use", "then_text": "no suspicious osseous lesion",
                "source_lines": ['- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.']}],
        negatives=[{"id": "n0", "section": "FINDINGS", "paragraph": "p0", "text": "No pneumoperitoneum.",
                    "source_lines": ['  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."', '- "No pneumoperitoneum."']},
                   {"id": "n1", "section": "FINDINGS", "paragraph": "p0", "text": "No free intra-abdominal air or fluid.",
                    "source_lines": ['  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."']},
                   {"id": "n2", "section": "FINDINGS", "paragraph": "p0", "text": "No periappendiceal collection.",
                    "condition": "The dictated findings report appendicitis",
                    "source_lines": ['  - "No periappendiceal collection." (if appendicitis)']}],
        normals=[{"id": "m0", "section": "FINDINGS", "paragraph": "p0", "structure": "gallbladder",
                  "text": "Unremarkable appearances of the gallbladder.",
                  "source_line": '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'},
                 {"id": "m1", "section": "FINDINGS", "paragraph": "p0", "structure": "spleen",
                  "text": "Unremarkable appearances of the spleen.",
                  "source_line": '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'}],
        terminology={"preferred": ["unremarkable", "size significant"], "suppressed": ["normal"]},
        if_present=[{"finding": "appendicitis", "section": "FINDINGS", "paragraph": "p0",
                     "negatives": [{"text": "No appendicolith", "tag": "contextual"}]}])


def test_good_draft_is_usable_and_covered():
    s = tss.build_structure(SHEET, good_draft(), model="m")
    assert s.usable, s.coverage
    assert s.coverage.if_lines == 3 and s.coverage.if_covered == 3
    assert s.coverage.negative_lines == 3 and s.coverage.negative_covered == 3
    assert s.sheet_hash == tss.sheet_hash(SHEET)


def test_invented_negative_is_dropped_and_logged():
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No bowel obstruction.", source_lines=['- "No bowel obstruction."']))
    s = tss.build_structure(SHEET, d, model="m")
    assert all(n.id != "n9" for n in s.negatives)
    assert any("No bowel obstruction" in v for v in s.coverage.verbatim_failures)


def test_uncovered_if_line_fails_the_gate():
    d = good_draft()
    d.rules = [r for r in d.rules if r.id != "r2"]
    s = tss.build_structure(SHEET, d, model="m")
    assert not s.usable and any("oncology" in u for u in s.coverage.uncovered)


def test_uncovered_negative_line_fails_the_gate():
    d = good_draft()
    d.negatives = [n for n in d.negatives if n.id != "n2"]
    assert not tss.build_structure(SHEET, d, model="m").usable


def test_atomic_normal_must_come_from_its_source_line():
    d = good_draft()
    d.normals[0].text = "Unremarkable appearances of the pancreas."
    s = tss.build_structure(SHEET, d, model="m")
    assert [n.id for n in s.normals] == ["m1"]


def test_if_present_must_be_a_negative_and_not_a_sheet_duplicate():
    d = good_draft()
    d.if_present[0].negatives += [tss.IfPresentNeg(text="Appendix dilated", tag="core"),
                                  tss.IfPresentNeg(text="No pneumoperitoneum", tag="core")]
    s = tss.build_structure(SHEET, d, model="m")
    assert [n.text for n in s.if_present[0].negatives] == ["No appendicolith"]


def test_section_not_in_structural_pattern_is_dropped():
    d = good_draft()
    d.sections.append(tss.StructSection(name="LIMITATIONS", role="other", header="LIMITATIONS", order=3))
    assert [x.name for x in tss.build_structure(SHEET, d, model="m").sections] == ["CLINICAL HISTORY", "FINDINGS", "IMPRESSION"]


def test_fresh_needs_matching_hash_version_and_usable():
    s = tss.build_structure(SHEET, good_draft(), model="m")
    cfg = {"skill_sheet": SHEET, "sheet_structure": s.model_dump(mode="json")}
    assert tss.fresh(cfg) is not None
    assert tss.fresh({**cfg, "skill_sheet": SHEET + "\n- edited"}) is None
    assert tss.fresh({"skill_sheet": SHEET}) is None
    assert tss.needs_restructure({**cfg, "skill_sheet": SHEET + "x"}) and not tss.needs_restructure(cfg)


REAL_IF_SHAPES = [
    '- **Conditional Suppression**: IF [Positive LAA finding] THEN suppress "No left atrial appendage thrombus."',
    "[IF Missing LV Indexed Volume OR LVEF ...]:",
    '- Aortic dimensions: IF abnormal THEN "The ascending aorta is dilated ..."',
    '- **IF [LGE present]** THEN suppress "there is no myocardial enhancement."',
]


def test_real_stored_if_line_shapes_are_conditional_and_coverable():
    sheet = "## Conditional Suppression Rules\n" + "\n".join(REAL_IF_SHAPES) + "\n### IF headings are not lines\n"
    assert tss.conditional_lines(sheet) == REAL_IF_SHAPES
    for ln in REAL_IF_SHAPES:
        assert tss._covers(ln, ln) and tss._covers(ln.replace("**", ""), ln)


async def test_structure_sheet_calls_the_model_and_verifies(monkeypatch):
    seen = {}

    class R:
        output = good_draft()

    async def fake_run(**kw):
        seen.update(kw)
        return R
    monkeypatch.setattr(tss, "_run_agent_with_model", fake_run)
    s = await tss.structure_sheet(SHEET, model="gpt-oss-120b")
    assert s.usable and s.model == "gpt-oss-120b"
    assert seen["user_prompt"].endswith(SHEET) and "IF [condition]" in seen["system_prompt"]
    for clinical in ("appendic", "pneumoperitoneum", "liver"):
        assert clinical not in tss.STRUCTURE_SYS.lower(), clinical


async def test_store_skips_when_the_sheet_changed_meanwhile(monkeypatch):
    s = tss.build_structure(SHEET, good_draft(), model="m")

    class T:
        template_config = {"skill_sheet": SHEET + "\nedited", "generation_mode": "skill_sheet_guided"}

    class DB:
        committed = False

        def query(self, *_):
            return self

        def filter(self, *_):
            return self

        def first(self):
            return T

        def commit(self):
            DB.committed = True

        def close(self):
            pass
    assert tss.store_structure(DB(), "00000000-0000-0000-0000-000000000000", s) is False
    assert DB.committed is False
