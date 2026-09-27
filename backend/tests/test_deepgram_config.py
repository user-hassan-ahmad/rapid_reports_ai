from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from rapid_reports_ai.deepgram_config import CORE_KEYTERMS, deepgram_listen_url, keyterm_tokens


def _q(url):
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def test_model_language_and_audited_parameters():
    q = _q(deepgram_listen_url(sample_rate=48000, dictation=True))
    assert q["model"] == ["nova-3-medical"] and q["language"] == ["en-GB"]
    assert q["smart_format"] == ["true"] and q["measurements"] == ["true"]
    assert q["numerals"] == ["true"]  # 'segment seven' → 'segment 7' (docs audit 2026-09-27)
    assert q["mip_opt_out"] == ["true"]  # not in Deepgram's Model Improvement Program
    assert "punctuate" not in q  # smart_format includes it; commands verified live without it
    assert q["dictation"] == ["true"] and q["interim_results"] == ["true"]
    assert q["endpointing"] == ["200"] and q["utterance_end_ms"] == ["1000"]
    assert q["encoding"] == ["linear16"] and q["sample_rate"] == ["48000"] and q["channels"] == ["1"]


def test_container_audio_has_no_pcm_parameters():
    q = _q(deepgram_listen_url(sample_rate=None, dictation=False))
    assert "encoding" not in q and q["dictation"] == ["false"]


def test_keyterms_default_to_the_core_list_and_can_be_replaced():
    assert _q(deepgram_listen_url(sample_rate=None, dictation=True))["keyterm"] == list(CORE_KEYTERMS)
    q = _q(deepgram_listen_url(sample_rate=None, dictation=True, keyterms=["adrenal glands", "hypodense"]))
    assert q["keyterm"] == ["adrenal glands", "hypodense"]


def test_uk_spelling_adds_replace_pairs():
    q = _q(deepgram_listen_url(sample_rate=None, dictation=True, uk_spelling=True))
    assert "hematoma:haematoma" in q["replace"]


def test_the_core_list_is_within_deepgrams_keyterm_budget():
    assert keyterm_tokens(CORE_KEYTERMS) < 500
