"""Quick-report post-generation check. The engine is shared with templated reports and lives in
report_review; this module keeps the quick path's import name (scripts and the generator use it)."""
from .report_review import *  # noqa: F401,F403
from .report_review import (  # noqa: F401 — private helpers the eval scripts read
    _HEADER, _NEGATION, _OMIT_CHOICES, _OMIT_KIND, _SEL_CHOICES, _SEL_KEEP, _content_words, _diff_edits,
    _negative_allowed, _only_normal, _problem, _restates, _sentences,
)
