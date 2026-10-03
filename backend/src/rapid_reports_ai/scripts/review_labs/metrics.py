"""Gate metrics (spec §11). Calibration (brier, ece, auc) and McNemar come from jev_tool_lab.score."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from rapid_reports_ai.scripts.jev_tool_lab.score import auc, brier, ece, mcnemar_exact  # noqa: F401  (re-export)

SHOWN = {"action", "minor"}


def gate_a(runs: List[Dict[str, str]], labels: Dict[str, dict], report_of: Dict[str, str]) -> dict:
    """runs: [{item_id: cls}] (run 1 first). labels: Hassan's {item_id: {verdict, material?}}."""
    r1 = runs[0]
    missing = sorted(i for i in r1 if i not in report_of)
    if missing:
        raise ValueError(f"run-1 items missing from report_of: {missing[:5]}")
    action = [i for i, l in labels.items() if l.get("verdict") == "action"]
    material = [i for i, l in labels.items() if l.get("material")]
    engine_action = [i for i, c in r1.items() if c == "action" and i in labels]
    per_report = defaultdict(int)
    for i, c in r1.items():
        if c == "minor":
            per_report[report_of.get(i, "?")] += 1
    reports = set(report_of.values())
    minors = [per_report.get(r, 0) for r in reports] or [0]
    out = {
        "n_labelled": len(labels),
        "n_action_labels": len(action),
        "action_recall": sum(r1.get(i) in SHOWN for i in action) / len(action) if action else None,
        "material_missed": [i for i in material if r1.get(i) not in SHOWN],
        "action_precision": (sum(labels[i]["verdict"] == "action" for i in engine_action) / len(engine_action)
                             if engine_action else None),
        "minor_per_report_median": float(statistics.median(minors)),
        "class_change_share": None,
        "crossed_shown_hidden": [],
        "n_missing_run2": 0,
    }
    if len(runs) > 1:
        r2 = runs[1]
        out["n_missing_run2"] = sum(i not in r2 for i in r1)
        common_ids = [i for i in r1 if i in r2]
        out["class_change_share"] = sum(r1[i] != r2[i] for i in common_ids) / len(common_ids) if common_ids else None
        out["crossed_shown_hidden"] = sorted(i for i in common_ids if (r1[i] in SHOWN) != (r2[i] in SHOWN))
    return out


def gate_a_pass(m: dict) -> Dict[str, bool]:
    return {"recall": (m["action_recall"] or 0) >= 0.90,
            "material": not m["material_missed"],
            "precision": (m["action_precision"] or 0) >= 0.85,
            "noise": m["minor_per_report_median"] <= 2,
            "stability": m["class_change_share"] is not None and m["class_change_share"] <= 0.10
                         and not m["crossed_shown_hidden"]}


def binary(rows: Sequence[Tuple[bool, bool]]) -> dict:
    """rows of (label_positive, predicted_positive)."""
    pos = [p for l, p in rows if l]
    neg = [p for l, p in rows if not l]
    return {"n_pos": len(pos), "n_neg": len(neg),
            "recall": sum(pos) / len(pos) if pos else None,
            "false_alarm": sum(neg) / len(neg) if neg else None}


def band(p: float, lo: float, hi: float) -> str:
    return "yes" if p >= hi else "no" if p < lo else "unsure"


def errors_by_band(probs: Sequence[float], labels: Sequence[bool], lo: float, hi: float) -> Dict[str, dict]:
    """Where Jev's errors fall (§11 point 2): an unsure answer counts as an error when its side of 0.5 is wrong."""
    out = {b: {"n": 0, "errors": 0} for b in ("yes", "unsure", "no")}
    for p, l in zip(probs, labels):
        b = band(p, lo, hi)
        out[b]["n"] += 1
        out[b]["errors"] += int((p >= 0.5) != l)
    return out
