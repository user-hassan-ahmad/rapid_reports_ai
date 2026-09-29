from __future__ import annotations

from rapid_reports_ai.two_pass import (
    SWITCH_MIN_CONF, Span, disagreements, recovered_prefix, switch_allowed, switch_questions,
)


def _w(word, conf=0.99, punct=None):
    return {"word": word.lower().strip(".,"), "punctuated_word": punct or word, "confidence": conf, "start": 0, "end": 0}


LIVE = [_w("Further"), _w("supplemental"), _w("emboli"), _w("are"), _w("seen"), _w("in"), _w("the"), _w("lingula.", punct="lingula.")]


def test_content_word_disagreements_become_spans_with_both_readings():
    spans = disagreements(LIVE, {"gpt": "Further subsegmental emboli are seen in the lingula."})
    assert spans == [Span(live="supplemental", options=("subsegmental",), left="further", right="emboli are seen in the lingula")]


def test_format_words_numbers_and_units_are_never_switched():
    live = [_w("L5"), _w("slash"), _w("S1"), _w("measures"), _w("9"), _w("mm.")]
    assert disagreements(live, {"gpt": "L5 S1 measures 19 mm."}) == []


def test_readings_from_two_engines_merge_into_one_question():
    spans = disagreements(LIVE, {"gpt": "Further subsegmental emboli are seen in the lingula.",
                                 "batch": "Further segmental emboli are seen in the lingula."})
    assert spans[0].options == ("subsegmental", "segmental")


def test_one_two_way_jev_question_per_alternative_reading():
    # three-way choices spread Jev's confidence (live: Tarlov picked at 0.83 against "tidal" and
    # "tunnel of"); the 31/34 experiment asked two-way — live against one other reading
    spans = disagreements(LIVE, {"gpt": "Further subsegmental emboli are seen in the lingula.",
                                 "batch": "Further segmental emboli are seen in the lingula."})
    qs = switch_questions(spans)
    assert list(qs) == ["span_0_0", "span_0_1"]
    assert qs["span_0_0"]["type"] == "choice"
    assert qs["span_0_0"]["criteria"] == {"as_heard": "further supplemental emboli are seen in the lingula",
                                          "option": "further subsegmental emboli are seen in the lingula"}
    assert qs["span_0_1"]["criteria"]["option"] == "further segmental emboli are seen in the lingula"


def test_a_switch_needs_confidence_and_must_not_lose_a_negation_side_or_number():
    assert switch_allowed("supplemental", "subsegmental", SWITCH_MIN_CONF) is True
    assert switch_allowed("supplemental", "subsegmental", SWITCH_MIN_CONF - 0.01) is False
    assert switch_allowed("no", "lumbar", 0.99) is False  # lab: gpt-4o-mini turned "No" into "lumbar"
    assert switch_allowed("left", "lung", 0.99) is False


def test_speech_the_stream_dropped_is_recovered_from_the_batch_pass():
    live = [_w("Actually"), _w("make"), _w("that"), _w("54"), _w("millimetres.")]
    batch = [_w(x) for x in ["Actually,", "make", "that", "54", "millimetres.", "Actually,", "make", "that", "54", "millimetres."]]
    assert recovered_prefix(live, batch) == "Actually, make that 54 millimetres."


def test_no_recovery_from_a_single_or_unsure_word():
    live = [_w("No"), _w("effusion.")]
    assert recovered_prefix(live, [_w("The", 0.99), _w("No"), _w("effusion.")]) is None
    assert recovered_prefix(live, [_w("Small", 0.5), _w("left", 0.6), _w("No"), _w("effusion.")]) is None


# --- orchestration ---------------------------------------------------------------------------
import asyncio
import io
import wave

from rapid_reports_ai.two_pass import TwoPass


def _alt(text, words):
    return {"transcript": text, "words": words}


def _timed(word, start, end):
    return {"word": word.lower().strip(".,"), "punctuated_word": word, "confidence": 0.99, "start": start, "end": end}


FINAL = _alt("Further supplemental emboli.", [_timed("Further", 0.2, 0.5), _timed("supplemental", 0.6, 1.2), _timed("emboli.", 1.3, 1.8)])


def _engines(gpt_text="Further subsegmental emboli.", choice="option", conf=0.97, fail=False):
    seen = {"clips": [], "jev": []}

    async def batch(wav):
        seen["clips"].append(wav)
        if fail:
            raise RuntimeError("down")
        return "Further supplemental emboli.", FINAL["words"]

    async def gpt(wav):
        if fail:
            raise RuntimeError("down")
        return gpt_text

    async def jev(body):
        seen["jev"].append(body)
        return {q: {"choice": choice, "confidence": conf} for q in body["questions"]}  # choice: option / as_heard
    return seen, dict(batch=batch, gpt=gpt, jev=jev)


def test_a_confident_jev_choice_becomes_a_switch():
    seen, eng = _engines()
    tp = TwoPass(16000, scan_type="CT pulmonary angiogram", **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(7, FINAL))
    assert rev["final_seq"] == 7 and rev["spans"] == 1
    assert rev["switches"] == [{"from": "supplemental", "to": "subsegmental", "confidence": 0.97}]
    assert seen["jev"][0]["state"]["scan_type"] == "CT pulmonary angiogram"
    with wave.open(io.BytesIO(seen["clips"][0])) as w:  # audio since the last final, to its end + 0.3 s
        assert w.getframerate() == 16000 and abs(w.getnframes() / 16000 - 2.1) < 0.01


def test_an_unsure_choice_keeps_the_live_words():
    _, eng = _engines(conf=0.64)
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == [] and rev["spans"] == 1


def test_agreement_asks_jev_nothing():
    seen, eng = _engines(gpt_text="Further supplemental emboli.")
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == [] and rev["spans"] == 0 and seen["jev"] == []


def test_engine_failures_fail_open():
    _, eng = _engines(fail=True)
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == [] and rev["recovered"] is None and rev["errors"] == ["batch", "gpt"]


def test_the_next_clip_starts_where_the_last_one_ended():
    seen, eng = _engines()
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 6)
    asyncio.run(tp.revise(1, FINAL))
    second = _alt("No effusion.", [_timed("No", 3.0, 3.2), _timed("effusion.", 3.3, 3.9)])
    asyncio.run(tp.revise(2, second))
    with wave.open(io.BytesIO(seen["clips"][1])) as w:  # 2.1 s → 4.2 s
        assert abs(w.getnframes() / 16000 - 2.1) < 0.01



def test_the_alternative_jev_prefers_most_confidently_wins():
    async def batch(wav):
        return "Further segmental emboli.", FINAL["words"]

    async def gpt(wav):
        return "Further subsegmental emboli."

    async def jev(body):
        return {"span_0_0": {"choice": "option", "confidence": 0.93},   # batch's "segmental"
                "span_0_1": {"choice": "option", "confidence": 0.98}}   # gpt's "subsegmental"
    tp = TwoPass(16000, batch=batch, gpt=gpt, jev=jev)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == [{"from": "supplemental", "to": "subsegmental", "confidence": 0.98}]


def test_a_preference_below_the_switch_bar_becomes_a_suggestion():
    # live: Jev preferred "tarlov" over "tidal" at 0.84 — shown, not swapped
    _, eng = _engines(conf=0.84)
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == []
    assert rev["suggestions"] == [{"from": "supplemental", "to": "subsegmental", "confidence": 0.84}]


def test_a_weak_preference_is_neither():
    _, eng = _engines(conf=0.55)
    tp = TwoPass(16000, **eng)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, FINAL))
    assert rev["switches"] == [] and rev["suggestions"] == []


def test_a_reading_the_guard_blocks_is_not_suggested_either():
    live = [_w("No"), _w("disc"), _w("extrusion.")]

    async def gpt(wav):
        return "Lumbar disc extrusion."

    async def jev(body):
        return {q: {"choice": "option", "confidence": 0.7} for q in body["questions"]}
    tp = TwoPass(16000, gpt=gpt, jev=jev)
    tp.feed(b"\x00\x00" * 16000 * 3)
    rev = asyncio.run(tp.revise(1, _alt("No disc extrusion.", [dict(w, start=0.1, end=0.5) for w in live])))
    assert rev["switches"] == [] and rev["suggestions"] == []
