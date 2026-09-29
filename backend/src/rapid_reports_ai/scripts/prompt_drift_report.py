"""Which prompt sections exist in both the quick-report and the template stack, and do they match?

The two paths were split on 2026-09-29 and are expected to diverge. This is informational, not
a test: it lists shared sections so that a rule meant for both is not changed in only one.

    python -m rapid_reports_ai.scripts.prompt_drift_report
"""
from __future__ import annotations

import re

from rapid_reports_ai import global_style_guide as template
from rapid_reports_ai import quick_report_prompts as quick

PAIRS = [
    ("system preamble", template.SYSTEM_PREAMBLE, quick.QR_SYSTEM_PREAMBLE),
    ("style guide", template.GLOBAL_STYLE_GUIDE, quick.QR_STYLE_GUIDE),
    ("pre-writing analysis", template.PRE_WRITING_ANALYSIS, quick.QR_PRE_WRITING_ANALYSIS),
    ("verification checklist", template.VERIFICATION_CHECKLIST, quick.QR_VERIFICATION_CHECKLIST),
]
_HEAD = re.compile(r"^(#{2,4} .+|\d+\. \*\*[^*]+\*\*.*|- .+)$", re.M)


def sections(text: str) -> dict[str, str]:
    """Split on headings, numbered steps and checklist lines; key by the heading line."""
    marks = [(m.start(), m.group(0).strip()) for m in _HEAD.finditer(text)]
    out = {}
    for i, (pos, head) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        key = head if not head.startswith("- ") else head[:60]
        out[key] = text[pos:end].strip()
    return out


def main() -> None:
    for name, t, q in PAIRS:
        ts, qs = sections(t) or {"(whole text)": t.strip()}, sections(q) or {"(whole text)": q.strip()}
        same = [k for k in ts if k in qs and ts[k] == qs[k]]
        diverged = [k for k in ts if k in qs and ts[k] != qs[k]]
        template_only = [k for k in ts if k not in qs]
        quick_only = [k for k in qs if k not in ts]
        print(f"\n== {name}: {len(same)} identical, {len(diverged)} diverged, "
              f"{len(template_only)} template-only, {len(quick_only)} quick-report-only")
        for label, keys in (("diverged", diverged), ("template-only", template_only), ("quick-report-only", quick_only)):
            for k in keys:
                print(f"   {label:18} {k[:90]}")


if __name__ == "__main__":
    main()
