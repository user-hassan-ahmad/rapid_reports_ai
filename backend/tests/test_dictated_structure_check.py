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
    assert dsc.question("pair_1") == {"type": "noul", "instructions":
        "In pair_1, the REPORT sentence gives the value for exactly the same anatomical structure, site, side and "
        "level as the DICTATED sentence; synonyms and rewording count as the same, a broader or narrower site does "
        "not."}
    assert dsc.state([Pair("a 1 cm.", "b 1 cm.", "1 cm")]) == {"pair_1": {"dictated": "a 1 cm.", "report": "b 1 cm."}}


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
    assert body["state"]["pair_1"] == {"dictated": "Aortic sinus 4.1 cm.", "report": "Aortic root 4.1 cm."}
    assert body["questions"]["pair_2"] == dsc.question("pair_2")
    monkeypatch.setattr(jev_client, "jev_post", post({"pair_1": {"noul": 0.2}}))
    with pytest.raises(ValueError):
        await dsc.ask_same_site(ps)

