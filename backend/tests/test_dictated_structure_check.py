"""Structure-name check (spec 2026-10-17, dictated fidelity step 3): code pass, Jev judge, items, edit. SYNTHETIC."""
import asyncio
import logging

import pytest

from rapid_reports_ai import dictated_structure_check as dsc
from rapid_reports_ai.dictated_number_check import Pair


def _ask(p_of=None, default=0.95):
    """A stand-in for the Jev call: P(same site) per report sentence (default 0.95), recording what was asked."""
    seen = {"calls": 0, "pairs": []}

    async def ask(ps):
        seen["calls"] += 1
        seen["pairs"] = [(p.dictated, p.report) for p in ps]
        return [(p_of or {}).get(p.report, default) for p in ps]
    return ask, seen


async def run(report, *sources, removed=(), p_of=None, default=0.95):
    ask, seen = _ask(p_of, default)
    return await dsc.changed_structures(report, list(sources), removed, ask=ask), seen


def test_question_wording_is_w1_verbatim_and_state_numbers_the_pairs():
    assert dsc.question("pair_1")["instructions"].startswith(
        "In pair_1, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
        "level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does "
        "not. ")
    assert dsc.state([Pair("a 1 cm.", "b 1 cm.", "1 cm")]) == {
        "pair_1": {"dictated": "a 1 cm.", "dictated_region": "", "report": "b 1 cm."}}


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("RR_DICTATED_STRUCTURES", raising=False)
    assert dsc.enabled() is False
    monkeypatch.setenv("RR_DICTATED_STRUCTURES", "1")
    assert dsc.enabled() is True


async def test_a_sentence_holding_the_dictated_words_passes_in_code_without_jev():
    items, seen = await run("FINDINGS\nAORTA: The aortic sinus 4.1 cm, stable.", "Aortic sinus 4.1 cm.", default=0.0)
    assert items == [] and seen["calls"] == 0


async def test_a_moved_value_is_one_high_severity_item_on_its_findings_sentence():
    report = "FINDINGS\nAortic root 4.1 cm.\nLiver normal."
    items, seen = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.2})
    assert seen["pairs"] == [("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.")]
    assert [(i["kind"], i["severity"], i["text"], i["sentence"], i["dictated_quote"]) for i in items] == [
        ("dictated_structure_changed", "high", "4.1 cm", "Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.")]


@pytest.mark.parametrize("p, flagged", [(0.69, True), (0.7, False), (0.95, False)])
async def test_threshold_is_p_below_0_7(p, flagged):
    items, _ = await run("Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", default=p)
    assert bool(items) is flagged


async def test_a_chain_passes_if_any_of_its_findings_sentences_is_the_same_site():
    report = "Aortic root 4.1 cm. The sinus of Valsalva measures 4.1 cm."
    items, _ = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.1})
    assert items == []


async def test_findings_wrong_and_impression_right_is_still_an_item():
    report = "FINDINGS\nAortic root 4.1 cm.\n\nIMPRESSION\nAortic sinus 4.1 cm."
    items, seen = await run(report, "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["sentence"] for i in items] == ["Aortic root 4.1 cm."]
    assert seen["pairs"] == [("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.")]


async def test_at_most_twelve_pairs_are_asked_and_the_rest_logged_unchecked(caplog):
    sources = [f"Node {n} mm at station {n}." for n in range(11, 25)]   # 14 values
    report = " ".join(f"Nodule {n} mm." for n in range(11, 25))
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.dictated_structure_check")
    items, seen = await run(report, *sources, default=0.1)
    assert len(seen["pairs"]) == 12 and seen["pairs"][0][1] == "Nodule 11 mm."
    assert [i["text"] for i in items] == [f"{n} mm" for n in range(11, 23)]   # the 2 unasked give no item
    assert "structure_name_unchecked" in caplog.text


@pytest.mark.parametrize("fail", ["raise", "short", "timeout"])
async def test_a_jev_failure_gives_no_item_and_is_logged(fail, monkeypatch, caplog):
    async def ask(ps):
        if fail == "raise":
            raise RuntimeError("down")
        if fail == "timeout":
            await asyncio.sleep(1)
        return []
    monkeypatch.setattr(dsc, "TIMEOUT_S", 0.05)
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.dictated_structure_check")
    assert await dsc.changed_structures("Aortic root 4.1 cm.", ["Aortic sinus 4.1 cm."], ask=ask) == []
    assert "structure_name_check_unavailable" in caplog.text


async def test_two_failing_values_in_one_sentence_are_two_items():
    items, _ = await run("Right kidney 11 cm and right adrenal 2 cm.",
                         "Left kidney 11 cm.", "Left adrenal 2 cm.", default=0.1)
    assert [(i["text"], i["sentence"]) for i in items] == [
        ("11 cm", "Right kidney 11 cm and right adrenal 2 cm."), ("2 cm", "Right kidney 11 cm and right adrenal 2 cm.")]


async def test_a_removed_sentence_is_never_checked():
    items, seen = await run("Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", removed=["Aortic sinus 4.1 cm."],
                            default=0.1)
    assert items == [] and seen["calls"] == 0


async def test_an_abbreviation_does_not_split_the_dictated_or_report_sentence():
    items, seen = await run("Cyst approx. 4 cm in the left lobe.", "Cyst approx. 4 cm in segment 6.", default=0.1)
    assert seen["pairs"] == [("Cyst approx. 4 cm in segment 6.", "Cyst approx. 4 cm in the left lobe.")]
    assert len(items) == 1


async def test_never_raises():
    assert await dsc.changed_structures(None, [None, ""]) == []


async def test_ask_same_site_sends_one_request_and_refuses_a_partial_answer(monkeypatch):
    from rapid_reports_ai import jev_client
    sent = []

    class R:
        def __init__(self, ans):
            self.ans = ans

        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": self.ans}

    def post(ans):
        async def f(body, key, timeout, transport=None):
            sent.append((body, timeout))
            return R(ans)
        return f
    ps = [Pair("Aortic sinus 4.1 cm.", "Aortic root 4.1 cm.", "4.1 cm"), Pair("Spleen 13 cm.", "Spleen 13 cm.", "13 cm")]
    monkeypatch.setattr(jev_client, "jev_post", post({"pair_1": {"noul": 0.2}, "pair_2": {"noul": 0.9}}))
    assert await dsc.ask_same_site(ps) == [0.2, 0.9]
    body, timeout = sent[0]
    assert len(sent) == 1 and body["model"] == jev_client.JEV_MODEL and timeout == 3.0
    assert body["state"]["pair_1"] == {"dictated": "Aortic sinus 4.1 cm.", "dictated_region": "",
                                       "report": "Aortic root 4.1 cm."}
    assert body["questions"]["pair_2"] == dsc.question("pair_2")
    monkeypatch.setattr(jev_client, "jev_post", post({"pair_1": {"noul": 0.2}}))
    with pytest.raises(ValueError):
        await dsc.ask_same_site(ps)



# --- the edit (spec §3.5) ---

async def test_a_moved_value_carries_the_edit_and_the_apply_label():
    report = "FINDINGS\nAortic root 4.1 cm.\nLiver normal."
    items, _ = await run(report, "Aortic sinus 4.1 cm.", p_of={"Aortic root 4.1 cm.": 0.2})
    assert items == [{"kind": "dictated_structure_changed", "severity": "high", "text": "4.1 cm",
                      "sentence": "Aortic root 4.1 cm.", "dictated_quote": "Aortic sinus 4.1 cm.",
                      "message": "Different site from your dictation? Apply puts your sentence back.",
                      "edit": {"mode": "replace", "find": "Aortic root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}}]


async def test_the_edit_capitalises_the_dictated_sentence_and_adds_a_full_stop():
    items, _ = await run("Cyst approx. 4 cm in the left lobe.", "cyst approx. 4 cm in segment 6", default=0.1)
    assert items[0]["edit"] == {"mode": "replace", "find": "Cyst approx. 4 cm in the left lobe.",
                                "replace": "Cyst approx. 4 cm in segment 6."}


async def test_no_edit_when_the_find_occurs_twice():
    items, _ = await run("Aortic root 4.1 cm. Prior: Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]
    assert items[0]["message"] == "Different site from your dictation? Check this sentence."


async def test_no_edit_when_a_number_free_clause_was_merged_in():
    items, _ = await run("Aortic root 4.1 cm with no aortic regurgitation.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_no_edit_when_the_writer_merged_a_word_from_another_statement():
    items, _ = await run("Simple cyst 3 cm in the right lobe.", "Cyst 3 cm in segment 6.", "The cyst is simple.",
                         default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_no_edit_on_a_reverse_split():
    # dictated as one sentence with two values, written as two: the report sentence lacks a dictated chain
    items, _ = await run("Right kidney 11 cm. Spleen 13 cm.", "Left kidney 11 cm, spleen 13 cm.",
                         p_of={"Right kidney 11 cm.": 0.1})
    assert [(i["text"], i["edit"]) for i in items] == [("11 cm", None)]


async def test_no_edit_when_two_values_share_the_report_sentence():
    items, _ = await run("Right kidney 11 cm and right adrenal 2 cm.",
                         "Left kidney 11 cm.", "Left adrenal 2 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None, None]


async def test_no_edit_with_an_extra_joiner():
    items, _ = await run("Aortic root, ascending, 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert [i["edit"] for i in items] == [None]


async def test_side_words_from_another_statement_do_not_withhold_the_edit():
    items, _ = await run("Left kidney 11 cm. Right kidney 10 cm.", "Right kidney 11 cm.", "Left kidney 10 cm.",
                         default=0.1)
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Left kidney 11 cm.", "replace": "Right kidney 11 cm."},
        {"mode": "replace", "find": "Right kidney 10 cm.", "replace": "Left kidney 10 cm."}]
    items, _ = await run("Bilateral renal cyst 2 cm.", "Left renal cyst 2 cm.", "Bilateral pleural effusions.",
                         default=0.1)
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Bilateral renal cyst 2 cm.", "replace": "Left renal cyst 2 cm."}]


async def test_a_vertebral_level_is_never_a_merged_word():
    # levels hold digits, so they are never content words: the other statement's L5/S1 cannot withhold the edit
    items, _ = await run("Disc protrusion at L5/S1 4 mm.", "Disc protrusion at L4/5 4 mm.", "L5/S1 disc normal.",
                         default=0.1)
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Disc protrusion at L5/S1 4 mm.", "replace": "Disc protrusion at L4/5 4 mm."}]


async def test_no_edit_for_a_joined_value_only_fragment():
    items, seen = await run("Liver normal. Cyst 2 cm.", "Segment 6 cyst 2 cm.", default=0.1)
    assert seen["pairs"] == [("Segment 6 cyst 2 cm.", "Liver normal. Cyst 2 cm.")]
    assert [(i["sentence"], i["edit"]) for i in items] == [("Liver normal. Cyst 2 cm.", None)]


async def test_jev_sees_the_line_label_and_a_label_naming_another_site_withholds_the_edit():
    items, seen = await run("FINDINGS\nRIGHT KIDNEY: Cyst 2 cm.", "Left kidney cyst 2 cm.", default=0.1)
    assert seen["pairs"] == [("Left kidney cyst 2 cm.", "RIGHT KIDNEY: Cyst 2 cm.")]
    assert [(i["sentence"], i["edit"]) for i in items] == [("RIGHT KIDNEY: Cyst 2 cm.", None)]


async def test_a_label_the_dictated_sentence_also_names_keeps_the_edit_on_the_unlabelled_text():
    items, _ = await run("FINDINGS\nAORTIC SINUS: Root 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert items[0]["sentence"] == "AORTIC SINUS: Root 4.1 cm."
    assert items[0]["edit"] == {"mode": "replace", "find": "Root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}


# --- end review fix 1: Apply never drops merged content ---

@pytest.mark.parametrize("report, dictated", [
    ("Aortic root 4.1 cm without aortic regurgitation.", "Aortic sinus 4.1 cm."),
    ("The aortic root measures 4.1 cm but is otherwise normal.", "Aortic sinus 4.1 cm."),
    ("Aortic root 4.1 cm (no regurgitation).", "Aortic sinus 4.1 cm."),
    ("Aortic root 4.1 cm whereas the ascending aorta is normal.", "Aortic sinus 4.1 cm."),
    ("Hepatic cyst 2 cm which is simple.", "Segment 6 cyst 2 cm."),
    ("Aortic root 4.1 cm - stable.", "Aortic sinus 4.1 cm."),
    ("Aortic root 4.1 cm—stable.", "Aortic sinus 4.1 cm."),
    ("The left kidney contains a 2 cm cyst.", "Cyst 2 cm."),
])
async def test_merged_content_keeps_the_item_but_withholds_the_edit(report, dictated):
    items, _ = await run(report, dictated, default=0.1)
    assert [(i["text"] != "", i["edit"]) for i in items] == [(True, None)]
    assert items[0]["message"] == dsc.LABEL_NO_EDIT


async def test_a_plain_rename_still_gets_the_edit():
    items, _ = await run("Aortic root 4.1 cm.", "Aortic sinus 4.1 cm.", default=0.1)
    assert items[0]["edit"] == {"mode": "replace", "find": "Aortic root 4.1 cm.", "replace": "Aortic sinus 4.1 cm."}


async def test_an_assumed_normal_merged_in_withholds_the_edit_but_is_never_paired():
    ask, seen = _ask(default=0.1)
    report = "Trileaflet aortic root 4.1 cm."
    items = await dsc.changed_structures(report, ["Aortic sinus 4.1 cm."], ask=ask)
    assert items[0]["edit"] is not None   # without the assumed normal: two new words, under the backstop
    items = await dsc.changed_structures(report, ["Aortic sinus 4.1 cm."],
                                         assumed=["Aortic valve trileaflet, annulus 4.1 cm."], ask=ask)
    assert [i["edit"] for i in items] == [None]
    assert seen["pairs"] == [("Aortic sinus 4.1 cm.", "Trileaflet aortic root 4.1 cm.")]   # never a pair source


# --- end review fix 2: the dictated sentence's region ---

def test_the_question_constant_is_w1_plus_the_region_sentence():
    assert dsc.QUESTION == (
        "In {key}, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
        "level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does "
        "not. The DICTATED sentence was said under the region named in dictated_region; read it as about that region "
        "when it names no structure itself.")
    assert dsc.question("pair_2") == {"type": "noul", "instructions": dsc.QUESTION.format(key="pair_2")}


def test_state_carries_the_dictated_region():
    assert dsc.state([Pair("Cyst 2 cm.", "Left kidney: cyst 2 cm.", "2 cm", "Right kidney"),
                      Pair("a 1 cm.", "b 1 cm.", "1 cm")]) == {
        "pair_1": {"dictated": "Cyst 2 cm.", "dictated_region": "Right kidney", "report": "Left kidney: cyst 2 cm."},
        "pair_2": {"dictated": "a 1 cm.", "dictated_region": "", "report": "b 1 cm."}}


async def test_a_regioned_sentence_whose_region_the_report_lacks_goes_to_jev():
    got = []

    async def ask(ps):
        got.extend((p.dictated, p.region, p.report) for p in ps)
        return [0.1 for _ in ps]
    items = await dsc.changed_structures("FINDINGS\nLeft kidney: cyst 2 cm.", [("Right kidney", "Cyst 2 cm.")],
                                         ask=ask)
    assert got == [("Cyst 2 cm.", "Right kidney", "Left kidney: cyst 2 cm.")]
    assert [(i["dictated_quote"], i["edit"]) for i in items] == [("Cyst 2 cm.", None)]


async def test_a_regioned_sentence_passes_in_code_when_the_report_names_the_region():
    ask, seen = _ask(default=0.0)
    items = await dsc.changed_structures("FINDINGS\nRight kidney: cyst 2 cm.", [("Right kidney", "Cyst 2 cm.")],
                                         ask=ask)
    assert items == [] and seen["calls"] == 0


# --- lab v3: a region the dictated sentence does not name withholds the edit ---

@pytest.mark.parametrize("region, dictated, report", [
    ("Left kidney", "Cyst 2 cm.", "A 2 cm cyst is seen in the left kidney."),
    ("Spleen", "Measures 9 mm.", "The liver measures 9 mm."),
])
async def test_a_region_the_dictated_sentence_does_not_name_withholds_the_edit(region, dictated, report):
    items = await dsc.changed_structures(report, [(region, dictated)], ask=_ask(default=0.1)[0])
    assert [(i["dictated_quote"], i["edit"]) for i in items] == [(dictated, None)]


async def test_a_dictated_sentence_naming_its_region_keeps_the_edit():
    # (with a kept "Right kidney:" line label the label rule withholds it: Apply would leave "Right kidney: Left ...")
    items = await dsc.changed_structures("FINDINGS\nRight kidney cyst 2 cm.", [("Left kidney", "Left kidney cyst 2 cm.")],
                                         ask=_ask(default=0.1)[0])
    assert [i["edit"] for i in items] == [
        {"mode": "replace", "find": "Right kidney cyst 2 cm.", "replace": "Left kidney cyst 2 cm."}]
