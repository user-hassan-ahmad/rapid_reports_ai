"""Save-time structure: verification and the coverage gate (spec §2)."""
from __future__ import annotations

import asyncio
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database.models import Template, User

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

        def with_for_update(self):
            return self

        def first(self):
            return T

        def commit(self):
            DB.committed = True

        def rollback(self):
            pass

        def close(self):
            pass
    assert tss.store_structure(DB(), "00000000-0000-0000-0000-000000000000", s) is False
    assert DB.committed is False


# ── regression: verification fails closed (review of Tasks 6-7) ─────────────────

ONCOLOGY_IF = '- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.'
NORMAL_LINE = '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'


def build(d, sheet=SHEET):
    return tss.build_structure(sheet, d, model="m")


def with_rule2_source(lines):
    d = good_draft()
    d.rules[2] = d.rules[2].model_copy(update={"source_lines": lines})
    return d


@pytest.mark.parametrize("lines", [
    ["oncology"],                                                             # tiny substring
    ['- **IF [oncology context]** THEN use "no suspicious osseous'],          # 60% prefix
    [SHEET[SHEET.index("## Interpretive"):SHEET.index("## Impression")]],     # superset block
    [SHEET],                                                                   # the whole sheet
])
def test_rule_source_must_be_one_whole_conditional_line(lines):
    s = build(with_rule2_source(lines))
    assert [r.id for r in s.rules] == ["r0", "r1"]
    assert not s.usable and ONCOLOGY_IF.strip() in s.coverage.uncovered


def test_whole_sheet_as_every_source_covers_nothing():
    d = good_draft()
    d.rules = [d.rules[0].model_copy(update={"source_lines": [SHEET]})]
    d.negatives = [d.negatives[0].model_copy(update={"source_lines": [SHEET]})]
    s = build(d)
    assert not s.rules and not s.negatives and not s.usable


def test_two_joined_conditional_lines_are_not_one_source_line():
    d = good_draft()
    d.rules = [d.rules[0], d.rules[1].model_copy(update={"source_lines": [IF_SUPPRESS + "\n" + ONCOLOGY_IF]})]
    s = build(d)
    assert [r.id for r in s.rules] == ["r0"] and not s.usable


@pytest.mark.parametrize("neg", [
    # a quoted line outside any negative region
    tss.Negative(id="n7", section="FINDINGS", text="No acute intra-abdominal abnormality.",
                 source_lines=['- "No acute intra-abdominal abnormality."']),
    # a positive statement, not a whole line
    tss.Negative(id="n7", section="FINDINGS", text="Free intra-abdominal air",
                 source_lines=["Free intra-abdominal air is present."]),
    # text spanning two lines
    tss.Negative(id="n7", section="FINDINGS", text='No pneumoperitoneum." - "No periappendiceal',
                 source_lines=['- "No pneumoperitoneum."']),
    # text not on its own source line
    tss.Negative(id="n7", section="FINDINGS", text="No periappendiceal collection.",
                 source_lines=['- "No pneumoperitoneum."']),
    # positive text lifted from a conditional line
    tss.Negative(id="n7", section="FINDINGS", text="Free intra-abdominal air is present.",
                 source_lines=[IF_SUPPRESS]),
    tss.Negative(id="n7", section="FINDINGS", text="", source_lines=[]),
    tss.Negative(id="n7", section="FINDINGS", text="  ", source_lines=["  "]),
])
def test_unverifiable_negative_is_dropped(neg):
    d = good_draft()
    d.negatives.append(neg)
    s = build(d)
    assert [n.id for n in s.negatives] == ["n0", "n1", "n2"] and s.usable
    assert any("n7" in f for f in s.coverage.verbatim_failures)


def test_quoted_mandatory_normal_on_a_negative_line_is_kept():
    sheet = SHEET.replace('  - "No periappendiceal collection." (if appendicitis)',
                          '  - "No periappendiceal collection." (if appendicitis)\n  - "The portal vein is patent."')
    d = good_draft()
    d.negatives.append(tss.Negative(id="n3", section="FINDINGS", text="The portal vein is patent.",
                                    source_lines=['  - "The portal vein is patent."']))
    s = build(d, sheet)
    assert "n3" in [n.id for n in s.negatives] and s.usable


INVERTING = '- **Normal pattern**: "No hydronephrosis or renal calculus."'


@pytest.mark.parametrize("line,text", [
    (INVERTING, "Renal calculus."),                                               # negation dropped
    (INVERTING, ""),                                                              # empty
    ('- **Normal pattern**: "No abnormality of the liver. The kidneys are not unremarkable."',
     "The kidneys are unremarkable."),                                            # 'not' dropped
    (NORMAL_LINE, "Kidneys unremarkable appearances of the gallbladder spleen."), # word order
    ('- "No pneumoperitoneum."', "No pneumoperitoneum."),                         # not a Normal pattern line
])
def test_atomic_normal_cannot_invert_or_reorder(line, text):
    sheet = SHEET.replace(NORMAL_LINE, line) if line != '- "No pneumoperitoneum."' else SHEET
    d = good_draft()
    d.normals = [tss.Normal(id="m9", section="FINDINGS", structure="x", text=text, source_line=line)]
    assert build(d, sheet).normals == []


def test_atomic_normal_keeping_its_negation_is_kept():
    sheet = SHEET.replace(NORMAL_LINE, INVERTING)
    d = good_draft()
    d.normals = [tss.Normal(id="m9", section="FINDINGS", structure="kidneys", text="No renal calculus.",
                            source_line=INVERTING)]
    assert [n.id for n in build(d, sheet).normals] == ["m9"]


def test_duplicate_ids_keep_the_first_and_are_logged():
    d = good_draft()
    d.rules.append(d.rules[0].model_copy(update={"id": "r1"}))
    d.negatives.append(d.negatives[0].model_copy(update={"id": "n1"}))
    s = build(d)
    assert [r.id for r in s.rules] == ["r0", "r1", "r2"] and [n.id for n in s.negatives] == ["n0", "n1", "n2"]
    assert s.rules[1].target == "No pneumoperitoneum."
    assert {"duplicate rule id r1", "duplicate negative id n1"} <= set(s.coverage.verbatim_failures)


def test_empty_fixed_block_and_terms_are_dropped():
    d = good_draft()
    d.rules.append(tss.Rule(id="r5", section="FINDINGS", condition="x", effect="suppress", source_lines=[]))
    d.fixed_blocks.append(tss.FixedBlock(id="f0", section="FINDINGS", text=""))
    d.terminology.suppressed += ["", "  ", "pneumoperitoneum", "NORMAL"]   # empty, blank, outside section, dup
    d.terminology.preferred += ["a"]
    s = build(d)
    assert [r.id for r in s.rules] == ["r0", "r1", "r2"] and s.fixed_blocks == []
    assert s.terminology.suppressed == ["normal"] and s.terminology.preferred == ["unremarkable", "size significant"]


def test_rule_target_must_come_from_its_own_line():
    d = good_draft()
    d.rules[0] = d.rules[0].model_copy(update={"effect": "suppress", "target": "No free intra-abdominal air or fluid."})
    s = build(d)
    assert "r0" not in [r.id for r in s.rules] and not s.usable


def test_section_names_match_whole_listed_names_only():
    d = good_draft()
    d.sections += [tss.StructSection(name="IN", role="other", order=9),
                   tss.StructSection(name="", role="other", order=10),
                   tss.StructSection(name="FINDINGS (implicit header)", role="findings", order=11)]
    s = build(d)   # the last is FINDINGS again by name key: a duplicate, first kept
    assert [x.name for x in s.sections] == ["CLINICAL HISTORY", "FINDINGS", "IMPRESSION"]
    assert "duplicate section: FINDINGS (implicit header)" in s.coverage.verbatim_failures


@pytest.mark.parametrize("pattern,names", [
    ("- Sections included, in order: FINDINGS, IMPRESSION\n", {"findings", "impression"}),
    ("- **Sections included, in order:**\n  1.  **COMPARISON** — `header: none` (Always)\n"
     "  2. Body (Neck, Chest) (Header varies)\n     - Sub paragraph\n- For each section:\n  - OTHER\n",
     {"comparison", "body"}),
    ("- **FINDINGS**\n  - Always present\n- **CONCLUSION**\n  - `header: \"Conclusion\"`\n",
     {"findings", "conclusion"}),
])
def test_section_names_parse_the_listed_shapes(pattern, names):
    assert tss.section_names(f"## Structural Pattern\n{pattern}\n## Next\n- X\n") == names


def test_if_present_dedupes_against_every_quoted_sheet_negative_and_caps_at_three():
    d = good_draft()
    d.if_present[0].negatives += [tss.IfPresentNeg(text=t, tag="core") for t in (
        "No free intra-abdominal air or fluid", "No pneumoperitoneum!", "no  Pneumoperitoneum .",
        "No acute intra-abdominal abnormality", "No appendicolith.", "No abscess", "No perforation",
        "No fat stranding")]
    assert [n.text for n in build(d).if_present[0].negatives] == ["No appendicolith", "No abscess", "No perforation"]


def test_paragraph_refs_are_validated():
    d = good_draft()
    d.paragraphs.append(tss.Paragraph(id="p9", section="FINDINGS", name="invented"))
    d.rules[0] = d.rules[0].model_copy(update={"paragraph": "p77"})
    s = build(d)
    assert [p.id for p in s.paragraphs] == ["p0"] and s.rules[0].paragraph == "" and s.negatives[0].paragraph == "p0"


@pytest.mark.parametrize("sheet,expected", [
    ('### P\n- **Mandatory negatives**:\n  - "No a."\n  - "No b."\n- **Normal pattern**: "x"\n',
     ['  - "No a."', '  - "No b."']),
    ('### P\n- **Mandatory negatives:** "No a.", "No b."\n- **Normal pattern**: "x"\n',
     ['- **Mandatory negatives:** "No a.", "No b."']),
    ('### P\n**Mandatory negatives:**\n- "No a."\n- "No b."\n\n**Normal pattern:**\n- "Unremarkable x."\n',
     ['- "No a."', '- "No b."']),
    ('### P\n- **Mandatory negatives**:\n  * "No a."\n', ['  * "No a."']),
    ('### P\n- **Mandatory negatives**:\n  - No a.\n  - No b (if x).\n', ['  - No a.', '  - No b (if x).']),
    ('### P\n- **Mandatory negatives**:\n\n  - "No a."\n', ['  - "No a."']),
    ('### P\n- **mandatory negatives**:\n  - "No a."\n', ['  - "No a."']),
    ('## Negative Finding Rules\n1. "No a."\n- Always state "No b."\n  - "No c."\n',
     ['1. "No a."', '- Always state "No b."', '  - "No c."']),
    ('## Negative Finding Rules\n- "No a."\n## Negative Finding Rules (global)\n- "No b."\n', ['- "No a."', '- "No b."']),
    ('### P\n- **Mandatory negatives**:\n  - “No a.”\n', ['  - “No a.”']),
    ('### P\n\t- **Mandatory negatives**:\n\t\t- "No a."\n\t- **Normal**: "x"\n', ['\t\t- "No a."']),
    ('### P\n- **Mandatory negatives**: None specific; described positively or as "unchanged".\n'
     '- **Mandatory negatives**: None, but "No a." when relevant.\n',
     ['- **Mandatory negatives**: None, but "No a." when relevant.']),
    ('## Negative Finding Rules\n- **Lungs**: "Lungs clear. No effusion."\n- IF [x] THEN suppress "No a."\n',
     ['- **Lungs**: "Lungs clear. No effusion."']),
])
def test_negative_lines_fail_closed_on_real_shapes(sheet, expected):
    assert tss.negative_lines(sheet) == expected


# ── store and schedule ───────────────────────────────────────────────────────────

class FakeDB:
    def __init__(self, tpl):
        self.tpl, self.locked, self.committed = tpl, False, False

    def query(self, *_):
        return self

    def filter(self, *_):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def first(self):
        return self.tpl

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class Tpl:
    def __init__(self, sheet):
        self.template_config = {"skill_sheet": sheet, "generation_mode": "skill_sheet_guided"}


TID = "00000000-0000-0000-0000-000000000000"


def test_store_writes_locks_flags_and_commits(monkeypatch):
    flagged = []
    monkeypatch.setattr(tss, "flag_modified", lambda obj, key: flagged.append(key))
    tpl, s = Tpl(SHEET), tss.build_structure(SHEET, good_draft(), model="m")
    db = FakeDB(tpl)
    assert tss.store_structure(db, TID, s) is True
    assert db.locked and db.committed and flagged == ["template_config"]
    assert tss.fresh(tpl.template_config) is not None
    assert tpl.template_config["generation_mode"] == "skill_sheet_guided"


def test_failure_marker_stops_retries_until_the_sheet_changes(monkeypatch):
    monkeypatch.setattr(tss, "flag_modified", lambda *_: None)
    tpl = Tpl(SHEET)
    assert tss.store_failure(FakeDB(tpl), TID, SHEET, "RuntimeError: model down") is True
    cfg = tpl.template_config
    assert cfg["sheet_structure"]["failed"] is True
    assert tss.fresh(cfg) is None and not tss.needs_restructure(cfg)
    assert tss.needs_restructure({**cfg, "skill_sheet": SHEET + "\n- edited"})


async def test_schedule_dedupes_and_records_failure(monkeypatch):
    calls, stored = [], []

    async def boom(sheet):
        calls.append(sheet)
        await asyncio.sleep(0)
        raise RuntimeError("model down")
    monkeypatch.setattr(tss, "structure_sheet", boom)
    monkeypatch.setattr(tss, "SessionLocal", lambda: FakeDB(Tpl(SHEET)))
    monkeypatch.setattr(tss, "store_failure", lambda db, tid, sheet, err: stored.append(err) or True)
    tss.schedule_structure(TID, SHEET)
    tss.schedule_structure(TID, SHEET)
    await asyncio.gather(*list(tss._tasks))
    assert len(calls) == 1 and stored == ["RuntimeError: model down"]
    assert not tss._inflight and not tss._tasks


async def test_schedule_stores_a_built_structure(monkeypatch):
    stored = []

    async def ok(sheet):
        return tss.build_structure(sheet, good_draft(), model="m")
    monkeypatch.setattr(tss, "structure_sheet", ok)
    monkeypatch.setattr(tss, "SessionLocal", lambda: FakeDB(Tpl(SHEET)))
    monkeypatch.setattr(tss, "store_structure", lambda db, tid, s: stored.append(s.usable) or True)
    tss.schedule_structure(TID, SHEET)
    await asyncio.gather(*list(tss._tasks))
    assert stored == [True] and not tss._inflight


def test_schedule_without_a_loop_warns_and_clears(monkeypatch):
    # record directly: other suites reconfigure logging, so caplog is not reliable here
    warned = []
    monkeypatch.setattr(tss.logger, "warning", lambda msg, *a: warned.append(msg % a))
    tss.schedule_structure(TID, SHEET)
    assert not tss._inflight and not tss._tasks
    assert any("no running event loop" in w for w in warned)


# ── regression round 2: stated normals, section validation, conditions, retry ────

GUIDANCE = '- Never write "No free fluid" when fluid is seen; write "Small volume free fluid is present." instead.'
NFR_HEAD = '## Negative Finding Rules\n- "No pneumoperitoneum."'


def with_nfr_line(line: str) -> str:
    return SHEET.replace(NFR_HEAD, NFR_HEAD + "\n" + line)


def test_positive_statement_on_a_guidance_line_is_not_a_negative():
    sheet = with_nfr_line(GUIDANCE)
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="Small volume free fluid is present.",
                                    source_lines=[GUIDANCE]))
    s = build(d, sheet)
    assert "n9" not in [n.id for n in s.negatives]
    # the line quotes a negative statement, so it still has to be covered (fail closed)
    assert GUIDANCE in tss.negative_lines(sheet) and not s.usable


def test_guidance_line_negative_can_cover_it():
    sheet = with_nfr_line(GUIDANCE)
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No free fluid", source_lines=[GUIDANCE]))
    s = build(d, sheet)
    assert s.usable and [n.kind for n in s.negatives if n.id == "n9"] == ["negative"]


def test_guidance_line_without_a_negative_is_not_a_negative_line():
    line = '- Avoid "The appendix is normal."; prefer "The appendix is unremarkable." instead.'
    sheet = with_nfr_line(line)
    assert line not in tss.negative_lines(sheet)
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="The appendix is unremarkable.",
                                    source_lines=[line]))
    s = build(d, sheet)
    assert "n9" not in [n.id for n in s.negatives] and s.usable


def test_stated_normal_is_tagged_and_needs_a_normal_state_marker():
    sheet = SHEET.replace('  - "No periappendiceal collection." (if appendicitis)',
                          '  - "No periappendiceal collection." (if appendicitis)\n'
                          '  - "The portal vein is patent."\n  - "Small volume free fluid is present."')
    d = good_draft()
    d.negatives += [tss.Negative(id="n3", section="FINDINGS", text="The portal vein is patent.",
                                 source_lines=['  - "The portal vein is patent."']),
                    tss.Negative(id="n4", section="FINDINGS", text="Small volume free fluid is present.",
                                 source_lines=['  - "Small volume free fluid is present."'])]
    s = build(d, sheet)
    kinds = {n.id: n.kind for n in s.negatives}
    assert kinds == {"n0": "negative", "n1": "negative", "n2": "negative", "n3": "stated_normal"}
    assert not s.usable and '- "Small volume free fluid is present."' in s.coverage.uncovered


@pytest.mark.parametrize("mutate,usable", [
    (lambda d: d.negatives.__setitem__(0, d.negatives[0].model_copy(update={"section": "LIMITATIONS"})), False),
    (lambda d: d.rules.__setitem__(2, d.rules[2].model_copy(update={"section": "BONES"})), False),
    (lambda d: d.normals.__setitem__(0, d.normals[0].model_copy(update={"section": "LIMITATIONS"})), True),
    (lambda d: d.if_present.__setitem__(0, d.if_present[0].model_copy(update={"section": "LIMITATIONS"})), True),
    (lambda d: d.paragraphs.__setitem__(0, d.paragraphs[0].model_copy(update={"section": "LIMITATIONS"})), True),
])
def test_items_in_an_unknown_section_are_dropped_not_remapped(mutate, usable):
    d = good_draft()
    mutate(d)
    s = build(d)
    assert s.usable is usable
    assert any("unknown section" in f for f in s.coverage.verbatim_failures)
    assert all(x.section in {"CLINICAL HISTORY", "FINDINGS", "IMPRESSION"}
               for x in [*s.rules, *s.negatives, *s.normals, *s.if_present, *s.paragraphs])


def test_unknown_paragraph_section_blanks_its_items_paragraph():
    d = good_draft()
    d.paragraphs[0] = d.paragraphs[0].model_copy(update={"section": "LIMITATIONS"})
    s = build(d)
    assert s.paragraphs == [] and all(n.paragraph == "" for n in s.negatives)


def test_negative_condition_must_match_its_line():
    d = good_draft()
    d.negatives[2] = d.negatives[2].model_copy(update={"condition": None})      # (if appendicitis) ignored
    s = build(d)
    assert "n2" not in [n.id for n in s.negatives] and not s.usable
    d = good_draft()
    d.negatives[1] = d.negatives[1].model_copy(update={"condition": "The dictated findings report ascites"})
    s = build(d)                                    # condition not on its line (n0 still covers that line)
    assert "n1" not in [n.id for n in s.negatives]
    assert "negative n1: condition not on its line" in s.coverage.verbatim_failures


def test_failure_marker_never_replaces_a_usable_structure(monkeypatch):
    monkeypatch.setattr(tss, "flag_modified", lambda *_: None)
    tpl = Tpl(SHEET)
    assert tss.store_structure(FakeDB(tpl), TID, tss.build_structure(SHEET, good_draft(), model="m"))
    assert tss.store_failure(FakeDB(tpl), TID, SHEET, "TimeoutError: ") is False
    assert tss.fresh(tpl.template_config) is not None


def test_failure_marker_retries_after_an_hour(monkeypatch):
    monkeypatch.setattr(tss, "flag_modified", lambda *_: None)
    tpl = Tpl(SHEET)
    tss.store_failure(FakeDB(tpl), TID, SHEET, "RateLimited: 429")
    cfg = tpl.template_config
    assert "created_at" in cfg["sheet_structure"] and not tss.needs_restructure(cfg)
    old = datetime.now(timezone.utc) - timedelta(seconds=tss.RETRY_AFTER_S + 1)
    cfg["sheet_structure"]["created_at"] = old.isoformat()
    assert tss.needs_restructure(cfg)


def test_store_round_trip_on_a_real_session(db_session):
    user = User(email="t@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()
    tpl = Template(id=uuid.uuid4(), name="T", user_id=user.id,
                   template_config={"skill_sheet": SHEET, "generation_mode": "skill_sheet_guided"})
    db_session.add(tpl)
    db_session.commit()
    tid = str(tpl.id)

    def config():
        db_session.expire_all()
        return db_session.query(Template).filter(Template.id == tpl.id).first().template_config

    assert tss.store_structure(db_session, tid, tss.build_structure(SHEET, good_draft(), model="m"))
    assert tss.fresh(config()) is not None and config()["generation_mode"] == "skill_sheet_guided"
    assert tss.store_failure(db_session, tid, SHEET, "TimeoutError: ") is False     # usable kept
    assert tss.fresh(config()) is not None

    edited = SHEET + "\n- edited"
    row = db_session.query(Template).filter(Template.id == tpl.id).first()
    row.template_config = {**row.template_config, "skill_sheet": edited}
    db_session.commit()
    assert tss.needs_restructure(config())
    assert tss.store_structure(db_session, tid, tss.build_structure(SHEET, good_draft(), model="m")) is False
    assert tss.store_failure(db_session, tid, edited, "TimeoutError: ") is True
    cfg = config()
    assert cfg["sheet_structure"]["failed"] and tss.fresh(cfg) is None and not tss.needs_restructure(cfg)
