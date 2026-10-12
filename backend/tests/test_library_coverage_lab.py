import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "coverage_lab", Path(__file__).resolve().parents[1] / "scripts" / "guidelines" / "coverage_lab.py")
CL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CL)


def test_abnormal_units_become_findings_with_frontend_ids():
    units = [{"id": 0, "text": "Clinical history.", "heading": True, "abnormal": True},
             {"id": 1, "text": "8 mm nodule.", "abnormal": True},
             {"id": 2, "text": "Normal liver.", "abnormal": False},
             {"id": 3, "text": "Kidneys: a 2 cm cyst; normal spleen.", "abnormal": True,
              "parts": [{"text": "a 2 cm cyst", "group": "kidneys", "abnormal": True},
                        {"text": "normal spleen", "group": "spleen", "abnormal": False}]}]
    assert CL.findings(units) == [{"id": "u1", "text": "8 mm nodule."}, {"id": "u3.0", "text": "a 2 cm cyst"}]


def test_metabase_rows_become_cases():
    body = {"data": {"cols": [{"name": "id"}, {"name": "scan_type"}, {"name": "units"}],
                     "rows": [["a", "CT chest", '[{"id": 1, "text": "8 mm nodule.", "abnormal": true}]'],
                              ["b", "CT head", "[]"]]}}
    assert CL.cases_from_metabase(body) == [
        {"id": "a", "scan_type": "CT chest", "clinical_history": "", "findings": [{"id": "u1", "text": "8 mm nodule."}]}]


def test_report_rows_become_sentence_cases():
    body = {"data": {"cols": [{"name": "id"}, {"name": "scan_type"}, {"name": "clinical_history"}, {"name": "findings"}],
                     "rows": [["a", "CT chest", "cough", "FINDINGS:\n8 mm nodule in the right upper lobe. Liver is normal."],
                              ["b", "CT head", "", ""]]}}
    got = CL.cases_from_reports(body)
    assert got == [{"id": "a", "scan_type": "CT chest", "clinical_history": "cough", "findings": [
        {"id": "s0", "text": "8 mm nodule in the right upper lobe."}, {"id": "s1", "text": "Liver is normal."}]}]
