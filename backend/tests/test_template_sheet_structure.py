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
    assert seen["user_prompt"].endswith(tss.numbered(SHEET)) and "IF [condition]" in seen["system_prompt"]
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
    # the line says when it applies ("when …"), so the item must carry a condition
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No free fluid", source_lines=[GUIDANCE],
                                    condition="The dictated findings report no free fluid"))
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


# ── regression round 3: statement shape allow-list, conditions in any form ──────

@pytest.mark.parametrize("line,text", [
    ('- Prefer "Small volume free fluid, not previously seen." for new fluid.', "Small volume free fluid, not previously seen."),
    ('- Use "Clear evidence of perforation." when present.', "Clear evidence of perforation."),
    ('- Write "The bowel is dilated with normal wall enhancement." for obstruction.',
     "The bowel is dilated with normal wall enhancement."),
    ('- Report as "Free fluid is present, no collection."', "Free fluid is present, no collection."),
])
def test_guidance_shaped_positive_line_is_neither_a_stated_normal_nor_required(line, text):
    sheet = with_nfr_line(line)
    assert line not in tss.negative_lines(sheet)         # the gate never demands a positive statement
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text=text, source_lines=[line]))
    s = build(d, sheet)
    assert "n9" not in [n.id for n in s.negatives] and s.usable


@pytest.mark.parametrize("line", [
    '- "The portal vein is patent."',
    '- "The portal vein is patent." (targets portal venous assessment)',
    '- "The portal vein is patent." [needs verification]',
    '- **Mandatory negatives**: "The portal vein is patent."',
])
def test_listed_statement_shape_keeps_a_stated_normal(line):
    sheet = with_nfr_line(line)
    assert line in tss.negative_lines(sheet)
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="The portal vein is patent.", source_lines=[line]))
    s = build(d, sheet)
    assert [n.kind for n in s.negatives if n.id == "n9"] == ["stated_normal"] and s.usable


@pytest.mark.parametrize("text", ["Clear evidence of perforation.", "Small fluid, not previously seen."])
def test_stated_normal_needs_a_normal_state_not_a_bare_word(text):
    line = f'- "{text}"'
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text=text, source_lines=[line]))
    s = build(d, with_nfr_line(line))
    assert "n9" not in [n.id for n in s.negatives] and not s.usable


@pytest.mark.parametrize("line", [
    '- "No periappendiceal abscess." — if appendicitis',
    '- "No periappendiceal abscess." (when appendicitis)',
    '- "No periappendiceal abscess." (only in suspected appendicitis)',
    '- if appendicitis: "No periappendiceal abscess."',
    '- "No periappendiceal abscess." [if appendicitis]',
    '- "No periappendiceal abscess." (in appendicitis cases)',
    '- "No periappendiceal abscess." (If appendicitis)',
])
def test_a_condition_in_any_form_must_be_carried(line):
    sheet = with_nfr_line(line)
    for condition, usable in ((None, False), ("The dictated findings report appendicitis", True)):
        d = good_draft()
        d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No periappendiceal abscess.",
                                        condition=condition, source_lines=[line]))
        s = build(d, sheet)
        assert ("n9" in [n.id for n in s.negatives]) is usable and s.usable is usable


@pytest.mark.parametrize("line", ['- "No abscess."', '- "No abscess." (targets the pelvis)',
                                  '- "No abscess." — excludes collections'])
def test_a_condition_not_on_the_line_is_rejected(line):
    sheet = with_nfr_line(line)
    for condition, usable in (("The dictated findings report appendicitis", False), (None, True)):
        d = good_draft()
        d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No abscess.", condition=condition,
                                        source_lines=[line]))
        assert build(d, sheet).usable is usable


# ── E1 tuning: line references, statement containment, heading titles, empty drafts ──

def line_no(line: str, sheet: str = SHEET) -> int:
    return sheet.splitlines().index(line) + 1


def by_number(d: tss.StructureDraft, sheet: str = SHEET) -> tss.StructureDraft:
    for x in [*d.rules, *d.negatives]:
        x.source_lines = [line_no(ln, sheet) for ln in x.source_lines]
    for n in d.normals:
        n.source_line = f"L{line_no(n.source_line, sheet)}"
    return d


def test_numbered_prompt_matches_the_resolver():
    first = tss.numbered(SHEET).splitlines()[line_no(IF_SUPPRESS) - 1]
    assert first == f"L{line_no(IF_SUPPRESS)}| {IF_SUPPRESS}"


def test_cited_line_numbers_resolve_to_the_exact_lines_and_are_stored_as_text():
    s = build(by_number(good_draft()))
    assert s.usable, s.coverage
    assert s.rules[1].source_lines == [IF_SUPPRESS] and s.normals[0].source_line == NORMAL_LINE


@pytest.mark.parametrize("ref", [line_no(ONCOLOGY_IF), line_no("## Negative Finding Rules"), 0, 10_000, "L10000"])
def test_a_wrong_line_number_is_verified_like_wrong_text(ref):
    d = by_number(good_draft())
    d.negatives[2].source_lines = [ref]          # the conditional negative now cites the wrong line
    s = build(d)
    assert "n2" not in [n.id for n in s.negatives] and not s.usable


@pytest.mark.parametrize("target,kept", [
    ("No pneumoperitoneum", True),                   # the stop inside the quote may be dropped
    ("No pneumoperitoneum.", True),
    ("o pneumoperitoneum.", False),                  # must start at a word boundary
    ("No free intra-abdominal air", False),          # front part of a longer statement
    ("No pneumoperitoneum. AND", False),
])
def test_rule_target_is_a_whole_statement_of_its_line(target, kept):
    d = good_draft()
    d.rules[1] = d.rules[1].model_copy(update={"target": target})
    assert ("r1" in [r.id for r in build(d).rules]) is kept


@pytest.mark.parametrize("text,kept", [
    ("No periappendiceal collection", True),
    ("No free intra-abdominal air", False),
    ("No free intra-abdominal air or fluid. (if appendicitis)", False),
])
def test_negative_text_is_a_whole_statement_of_its_line(text, kept):
    d = good_draft()
    line = d.negatives[1].source_lines[0] if "air" in text else d.negatives[2].source_lines[0]
    cond = None if "air" in text else "The dictated findings report appendicitis"
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text=text, condition=cond, source_lines=[line]))
    s = build(d)                                    # a kept repeat folds into the item with that statement
    assert (tss._key(text) in [tss._key(n.text) for n in s.negatives]) is kept
    assert not any("n9: " in f and "source line" not in f for f in s.coverage.verbatim_failures) is kept


def test_backtick_quoted_target_is_a_statement_boundary():
    assert tss._in_line("No central defect", "- IF [x] THEN suppress `No central defect.` AND replace with `Y.`")
    assert not tss._in_line("No central", "- IF [x] THEN suppress `No central defect.` AND replace with `Y.`")


HEADED = SHEET.replace("### Primary Pathology Paragraph", "### FINDINGS - Paragraph 1: Primary Pathology (Main)")


@pytest.mark.parametrize("name,kept", [
    ("Primary Pathology", True),
    ("FINDINGS - Paragraph 1: Primary Pathology (Main)", True),
    ("[Primary Pathology]", True),
    ("Primary", False),
    ("Paragraph 1", False),
    ("FINDINGS", False),
])
def test_paragraph_name_is_the_heading_or_its_title(name, kept):
    d = good_draft()
    d.paragraphs[0] = d.paragraphs[0].model_copy(update={"name": name})
    assert (build(d, HEADED).paragraphs != []) is kept


def test_bracketed_heading_title():
    sheet = SHEET.replace("### Primary Pathology Paragraph", "### [Primary Pathology Paragraph]")
    assert build(good_draft(), sheet).paragraphs[0].id == "p0"


def test_an_empty_draft_fails_validation_so_the_call_retries():
    with pytest.raises(Exception):
        tss.StructureDraft.model_validate({"sections": [], "rules": [], "negatives": []})
    with pytest.raises(Exception):
        tss.StructureDraft.model_validate({"rules": []})
    d = good_draft()
    d.sections = [tss.StructSection(name="LIMITATIONS", role="other", order=0)]
    s = build(d)                                    # every section rejected: stored, but unusable
    assert s.sections == [] and not s.usable
    assert tss.SheetStructure.model_validate(s.model_dump(mode="json")).sections == []


@pytest.mark.parametrize("word", ["null", "None", " n/a ", ""])
def test_a_null_word_is_no_condition(word):
    d = good_draft()
    d.negatives[0] = d.negatives[0].model_copy(update={"condition": None})
    d.negatives[0] = tss.Negative.model_validate({**d.negatives[0].model_dump(), "condition": word})
    assert d.negatives[0].condition is None and build(d).usable
    d = good_draft()                                    # counter: the conditional line still needs a real one
    d.negatives[2] = tss.Negative.model_validate({**d.negatives[2].model_dump(), "condition": word})
    assert not build(d).usable


def test_a_negative_citing_its_rules_if_line_keeps_its_own_line():
    d = good_draft()
    d.negatives[0].source_lines = [*d.negatives[0].source_lines, IF_SUPPRESS]
    s = build(d)
    assert s.usable and IF_SUPPRESS not in s.negatives[0].source_lines
    assert any("source line not cited" in f for f in s.coverage.verbatim_failures)


def test_a_dropped_if_line_citation_never_covers_the_if_line():
    d = good_draft()
    d.rules = [r for r in d.rules if r.id != "r1"]
    d.negatives[0].source_lines = [*d.negatives[0].source_lines, IF_SUPPRESS]
    s = build(d)
    assert not s.usable and IF_SUPPRESS.strip() in s.coverage.uncovered


MAND_BOTH = '  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."'


def test_a_repeated_statement_is_linked_to_its_verified_item():
    d = good_draft()
    d.negatives[0].source_lines = [MAND_BOTH]          # the model cited one of the two places
    s = build(d)
    assert s.usable and s.negatives[0].source_lines == [MAND_BOTH, '- "No pneumoperitoneum."']


@pytest.mark.parametrize("line", [
    '- "No pneumoperitoneum." (if perforation suspected)',         # conditional line
    '- "No pneumoperitoneum." (when relevant)',
    '- Avoid "No pneumoperitoneum." in post-operative studies',       # guidance
    '- "No pneumoperitoneum or portal venous gas."',                  # a longer statement
])
def test_a_repeat_is_never_linked_across_a_condition_guidance_or_a_different_statement(line):
    sheet = SHEET.replace(NFR_HEAD, "## Negative Finding Rules\n" + line)
    d = good_draft()
    d.negatives[0].source_lines = [MAND_BOTH]
    s = build(d, sheet)
    assert not s.usable and line.strip() in s.coverage.uncovered


def test_a_conditional_item_is_never_linked():
    line = '  - "No periappendiceal collection."'
    sheet = SHEET.replace(NFR_HEAD, NFR_HEAD + "\n" + line)
    s = build(good_draft(), sheet)                     # n2 is conditional: the unconditional repeat stays uncovered
    assert not s.usable and line.strip() in s.coverage.uncovered


def test_bracketed_placeholder_then_text_is_a_unit():
    line = '- IF [x] THEN append [location description] (e.g. "example text").'
    assert tss._in_line("[location description]", line)
    assert not tss._in_line("[location", line)


def test_a_citation_outside_the_negative_regions_is_dropped_not_the_item():
    d = good_draft()
    d.negatives[0].source_lines = [*d.negatives[0].source_lines, '- "No acute intra-abdominal abnormality."', ""]
    s = build(d)
    assert s.usable and s.negatives[0].source_lines == ['  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."',
                                                        '- "No pneumoperitoneum."']


def test_an_item_left_without_a_valid_citation_is_rejected():
    d = good_draft()
    d.negatives[2].source_lines = ['- "No acute intra-abdominal abnormality."', IF_SUPPRESS]
    s = build(d)
    assert "n2" not in [n.id for n in s.negatives] and not s.usable


def test_a_condition_borrowed_from_a_dropped_citation_is_rejected():
    d = good_draft()                                  # condition only on the dropped (non-negative) line
    d.negatives[1] = d.negatives[1].model_copy(update={
        "condition": "The dictated findings report ascites",
        "source_lines": [*d.negatives[1].source_lines, '- "No free intra-abdominal air or fluid." (if ascites)']})
    assert "n1" not in [n.id for n in build(d).negatives]


@pytest.mark.parametrize("text,kept", [
    ("The visualised structures demonstrate no suspicious lesion.", True),
    ("There is no focal abnormality.", True),
    ("Small fluid, there is no collection.", False),     # a clause before the negation
    ("Free fluid is present with no collection.", False),
])
def test_a_negated_predicate_statement_is_a_stated_normal(text, kept):
    line = f'- "{text}"'
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text=text, source_lines=[line]))
    s = build(d, with_nfr_line(line))
    assert ("n9" in [n.id for n in s.negatives]) is kept and s.usable is kept


def test_non_gated_fields_do_not_fail_the_whole_draft():
    raw = good_draft().model_dump(mode="json")
    raw["fixed_blocks"] = [{"id": "f0", "section": None, "text": "Unremarkable appearances of the gallbladder, spleen and kidneys."}]
    raw["if_present"][0]["negatives"] = [{"text": "No appendicolith"}]
    d = tss.StructureDraft.model_validate(raw)
    s = build(d)
    assert s.usable and s.fixed_blocks == [] and s.if_present[0].negatives[0].tag == "contextual"


def test_citations_disagreeing_with_the_items_condition_are_dropped():
    line = '  - "No pneumoperitoneum." (if perforation)'
    sheet = SHEET.replace(MAND_BOTH, MAND_BOTH + "\n" + line)
    d = good_draft()
    d.negatives[0].source_lines = [*d.negatives[0].source_lines, line]       # merged across a qualifier
    s = build(d, sheet)
    assert line not in s.negatives[0].source_lines and not s.usable          # the qualified line is uncovered
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No pneumoperitoneum.",
                                    condition="The dictated findings report perforation", source_lines=[line]))
    assert build(d, sheet).usable


def test_an_unqualified_item_citing_only_qualified_lines_is_still_rejected():
    d = good_draft()
    d.negatives[2] = d.negatives[2].model_copy(update={"condition": None})
    s = build(d)
    assert "n2" not in [n.id for n in s.negatives] and not s.usable


@pytest.mark.parametrize("update", [
    {"effect": "replace", "then_text": ""},               # replace with nothing
    {"effect": "suppress", "target": ""},                 # suppress nothing
])
def test_a_hollow_rule_never_covers_its_line(update):
    d = good_draft()
    d.rules[1] = d.rules[1].model_copy(update=update)
    s = build(d)
    assert "r1" not in [r.id for r in s.rules] and not s.usable
    assert any("r1:" in f and "without" in f for f in s.coverage.verbatim_failures)


def test_an_append_rule_needs_its_clause():
    d = good_draft()
    d.rules[0] = d.rules[0].model_copy(update={"then_text": ""})
    assert not build(d).usable


def repair_fake(monkeypatch, outputs, seen):
    async def fake_run(**kw):
        seen.append(kw["user_prompt"])
        out = outputs.pop(0)
        if isinstance(out, Exception):
            raise out

        class R:
            output = out
        return R
    monkeypatch.setattr(tss, "_run_agent_with_model", fake_run)


def missing_n2():
    d = good_draft()
    d.negatives = [n for n in d.negatives if n.id != "n2"]
    return d


def only_n2(**update):
    d = good_draft()
    return d.model_copy(update={"rules": [], "negatives": [d.negatives[2].model_copy(update=update)], "normals": []})


async def test_repair_asks_for_the_uncovered_lines_and_merges(monkeypatch):
    seen = []
    repair_fake(monkeypatch, [missing_n2(), only_n2()], seen)
    s = await tss.structure_sheet(SHEET, model="m")
    assert s.usable and [n.id for n in s.negatives] == ["n0", "n1", "nx0"]
    assert len(seen) == 2 and '(if appendicitis)' in seen[1].split("uncovered:")[1]


async def test_repair_items_are_verified_like_the_first_pass(monkeypatch):
    seen = []
    repair_fake(monkeypatch, [missing_n2(), only_n2(condition=None)], seen)   # the repair drops the condition
    s = await tss.structure_sheet(SHEET, model="m")
    assert not s.usable and [n.id for n in s.negatives] == ["n0", "n1"]


async def test_a_failed_repair_keeps_the_first_pass_and_a_usable_first_pass_is_not_repaired(monkeypatch):
    seen = []
    repair_fake(monkeypatch, [missing_n2(), RuntimeError("down")], seen)
    s = await tss.structure_sheet(SHEET, model="m")
    assert not s.usable and len(seen) == 2
    seen.clear()
    repair_fake(monkeypatch, [good_draft()], seen)
    assert (await tss.structure_sheet(SHEET, model="m")).usable and len(seen) == 1


@pytest.mark.parametrize("label,noted", [
    ("Routine case", True), ("Follow-up study", True), ("Right heart (screening context)", True),
    ("Lungs", False), ("Mandatory negatives", False),
])
def test_a_case_scoped_label_is_a_condition(label, noted):
    line = f'- {label}: "No pleural effusion."'
    assert tss._cond_noted(line) is noted
    sheet = with_nfr_line(line)
    for condition in (None, "The study is a routine case"):
        d = good_draft()
        d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No pleural effusion.",
                                        condition=condition, source_lines=[line]))
        assert build(d, sheet).usable is (noted == bool(condition))   # required when scoped, refused when not


ELLIPSIS_IF = '- IF [x] THEN suppress "No free intra-abdominal... or fluid" AND replace with "Y."'


@pytest.mark.parametrize("target,kept", [
    ("No free intra-abdominal air or fluid.", True),       # the sheet's own statement, abbreviated on the line
    ("No free intra-abdominal gas or fluid.", False),      # not a sheet statement
    ("No free intra-abdominal air.", False),               # wrong ending
])
def test_an_abbreviated_target_expands_only_to_a_sheet_statement(target, kept):
    sheet = SHEET.replace(ONCOLOGY_IF, ONCOLOGY_IF + "\n" + ELLIPSIS_IF)
    d = good_draft()
    d.rules.append(tss.Rule(id="r9", section="FINDINGS", condition="The dictated findings report x", effect="replace",
                            target=target, then_text="Y.", source_lines=[ELLIPSIS_IF]))
    s = build(d, sheet)
    assert ("r9" in [r.id for r in s.rules]) is kept and s.usable is kept


def test_repeated_items_fold_into_one():
    d = good_draft()
    d.negatives.append(d.negatives[0].model_copy(update={"id": "nx0", "source_lines": ['- "No pneumoperitoneum."']}))
    d.negatives.append(d.negatives[2].model_copy(update={"id": "nx1", "condition": None}))  # different condition: kept apart (and rejected)
    d.rules.append(d.rules[1].model_copy(update={"id": "rx0"}))
    s = build(d)
    assert [n.id for n in s.negatives] == ["n0", "n1", "n2"] and [r.id for r in s.rules] == ["r0", "r1", "r2"]
    assert s.usable


ALT_SHEET = SHEET.replace("  - IMPRESSION\n", "  - IMPRESSION or CONCLUSION\n")


@pytest.mark.parametrize("name,kept", [("IMPRESSION/CONCLUSION", True), ("IMPRESSION or CONCLUSION", True),
                                       ("IMPRESSION/SUMMARY", False), ("FINDINGS/LIMITATIONS", False)])
def test_a_section_named_by_its_listed_alternatives(name, kept):
    d = good_draft()
    d.sections[2] = d.sections[2].model_copy(update={"name": name})
    assert (name in [x.name for x in build(d, ALT_SHEET).sections]) is kept
