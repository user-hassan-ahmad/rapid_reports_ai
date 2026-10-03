"""Unit tests for the review-engine gate labs (plan 2026-10-03-review-engine-gate-labs)."""
import os

import pytest

from rapid_reports_ai.scripts.review_labs import common


def test_decode_json_list_passes_lists_through():
    assert common.decode_json_list(["a", "b"]) == ["a", "b"]


def test_decode_json_list_decodes_string_encoded_list():
    assert common.decode_json_list('["a", "b"]') == ["a", "b"]


def test_decode_json_list_wraps_plain_string_and_drops_blank():
    assert common.decode_json_list("one item") == ["one item"]
    assert common.decode_json_list("  ") == []
    assert common.decode_json_list(None) == []


def test_lab_out_refuses_repo_paths(monkeypatch):
    monkeypatch.setenv("RR_LAB_OUT", str(common.REPO / "backend" / "tmp_lab"))
    with pytest.raises(SystemExit):
        common.lab_out("gate_a")


def test_lab_out_creates_gate_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = common.lab_out("gate_a")
    assert p == tmp_path / "gate_a" and p.is_dir()


def test_out_file_has_pid(monkeypatch, tmp_path):
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = common.out_file("gate_a", "run1", "jsonl")
    assert p.name.startswith("run1_") and p.suffix == ".jsonl" and str(os.getpid()) in p.name


def test_sentences_and_best_sentence():
    text = "FINDINGS:\nThe liver is normal. A 5 mm cyst is in the left kidney.\nIMPRESSION:\nNo acute finding."
    spans = common.sentences(text)
    assert any(text[a:b].strip() == "A 5 mm cyst is in the left kidney." for a, b in spans)
    a, b = common.best_sentence(text, "left kidney cyst 5 mm")
    assert "left kidney" in text[a:b]


def test_section_of_reads_nearest_heading():
    text = "FINDINGS:\nA.\nIMPRESSION:\nB."
    assert common.section_of(text, text.index("B.")) == "Impression"
    assert common.section_of(text, text.index("A.")) == "Findings"


def test_lab_out_refuses_resolved_repo_and_git_ancestors(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path / "scratch"))
    with pytest.raises(SystemExit):
        common.lab_out("gate_a")


def test_decode_json_list_quoted_json_string():
    assert common.decode_json_list('"just one"') == ["just one"]
