"""Quick reports and template reports are separate paths (split 2026-09-29): each owns its
generator and prompt stack, and neither imports the other's. Template prompts are pinned so a
quick-report change can never land on templates by accident."""
from __future__ import annotations

import ast
import hashlib
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai"
QR_MODULES = ("quick_report_generator.py", "quick_report_prompts.py", "quick_report_api.py")
TEMPLATE_PROMPTS = {"GLOBAL_STYLE_GUIDE": "94aa643c", "PRE_WRITING_ANALYSIS": "c45d9d5d",
                    "VERIFICATION_CHECKLIST": "20e21f1f", "SYSTEM_PREAMBLE": None}


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module.lstrip("."))
        elif isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
    return out


def test_quick_report_modules_do_not_use_template_prompts_or_generator():
    for f in QR_MODULES:
        imps = _imports(SRC / f)
        assert "global_style_guide" not in imps, f
        assert "template_manager" not in imps, f


def test_template_path_does_not_use_quick_report_prompts():
    assert "quick_report_prompts" not in _imports(SRC / "template_manager.py")
    assert "quick_report_generator" not in _imports(SRC / "template_manager.py")


def test_template_prompts_unchanged():
    from rapid_reports_ai import global_style_guide as g
    for name, digest in TEMPLATE_PROMPTS.items():
        if digest:
            assert hashlib.sha256(getattr(g, name).encode()).hexdigest()[:8] == digest, name


def test_quick_report_prompts_carry_no_template_only_instructions():
    from rapid_reports_ai import quick_report_prompts as q
    text = (q.QR_STYLE_GUIDE + q.QR_PRE_WRITING_ANALYSIS + q.QR_VERIFICATION_CHECKLIST).lower()
    for marker in ("fixed block", "needs verification", "placeholder", "clinical history section is defined",
                   "interpretive clause"):
        assert marker not in text, marker


def test_quick_report_generator_has_its_own_role():
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, MODEL_PROVIDERS
    for role in ("QUICK_REPORT_GENERATOR", "QUICK_REPORT_GENERATOR_FALLBACK"):
        assert MODEL_CONFIG[role] in MODEL_PROVIDERS
