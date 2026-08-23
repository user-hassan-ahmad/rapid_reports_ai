"""Global report policy for the v3 pipeline.

Everything here is scan-type-invariant: the same bytes on every case. It is
prepended to the stage prompts rather than restated in the decision sheet
(spec R6 - if a rule is the same for every case, it never belongs in the sheet).

Supersedes, for v3 only, QUICK_REPORT_HARDENING_PREAMBLE and the quick path's
use of global_style_guide.GLOBAL_STYLE_GUIDE. Production still uses those; this
module is on the parallel track until a cutover is separately proposed.

**This layer must never name a sheet field.** That is the property the whole
design rests on. GLOBAL_STYLE_GUIDE and QUICK_REPORT_HARDENING_PREAMBLE name v1
fields directly - style exemplars, canonical line, mandatory negatives, fixed
blocks - so changing the sheet grammar necessarily breaks the layer above it.
That coupling is why report_v2.py had to go self-contained, and why v2 has never
once run inside the system scaffolding. Keeping this module grammar-agnostic is
what makes "change only the sheet" a coherent operation. Guarded by
test_policy_names_no_sheet_fields.

Split in two because the analyser writes report-register templates (so it needs
the register, the lexicon and the banned list) but never writes a COMPARISON
section (so the output-format half would be dead tokens on the analyser call).
"""
from __future__ import annotations

import re

POLICY_CORE = """## REPORT POLICY — core

Applies to every study and every modality. Never restated further down.

### Register
British English, UK/NHS practice. Impersonal, present tense for findings. Compressed
declaratives — a consultant states what is, at pace. Dates DD/MM/YYYY; mm and cm; consistent
units and sensible precision within a report, never false precision. Lead with the anatomical
subject or the imaging feature: existential openers ("there is", "there are") and padding verbs
("is noted", "is seen", "is demonstrated", "is appreciated") are filler. Direct copula plus
adjective ("the appendix is dilated") is not filler — it carries information.

Laterality and vertebral levels are checked, not assumed, and must agree between FINDINGS and
IMPRESSION. Laterality error is the classic radiology report defect.

### Calibrated uncertainty
Confidence is expressed with this lexicon and no other. Do not hedge outside it.

| phrase | confidence |
|---|---|
| diagnostic of / consistent with | above 90% |
| probable / likely represents | 70 to 90% |
| possible / may represent | 25 to 50% |
| unlikely | below 10% |
| no evidence of | below detection on this study — not proof of absence |

Uncertainty in the dictation is preserved, never resolved. A dictated hypodensity "not fully
characterised" is not a cyst. Naming an entity the dictation declined to name is fabrication,
however probable the entity. Where genuine uncertainty remains, name what would resolve it — a
specific test, a prior study, a clinical detail — rather than leaving it open.

### Banned constructions
- "cannot be excluded" without both a confidence term and a resolution path
- "clinical correlation recommended" standing alone, with nothing named to correlate
- "no significant abnormality" — significant to whom
- "stable" for a measurable lesion without the current value, the prior value and the prior's date
- management vocabulary: treatment, drugs, dosing, operative versus conservative choice, surgical
  technique, hardware, immobilisation, physiotherapy, rehabilitation. Naming the specialty that
  should review is in scope; naming what that specialty should then do is not.
"""

POLICY_REPORT = """## REPORT POLICY — output format

### Sections
Exactly these, in this order: COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION. Each header uppercase,
on its own line, terminated by a colon; content begins on the next line; one blank line between
sections. Never place content on the header line, never use markdown, never add or omit a
section. One-line sections keep the same layout:

TECHNIQUE:
Non-contrast CT of the lumbar spine.

FINDINGS:
...

### COMPARISON
Always present, first. Reflect whether the reading involved comparison, judged from the dictation
as a whole — not merely whether a prior is named at the top:
1. the dictation identifies a prior → carry it as given, with its date where stated
2. no prior named and no comparison-dependent language in the findings → emit exactly:
   "No prior imaging available for comparison."
3. no prior named but the findings use comparison-dependent language — new, stable, improved,
   progressed, decreased, unchanged, resolved → acknowledge generically, never inventing a scan
   type or a date, by emitting exactly:
   "Comparison made to previous imaging."

Any lesion under surveillance carries its current measurement and the prior measurement with the
prior's date.

### TECHNIQUE
Strictly protocol description. Never carries assessment disclosures or limitation commentary.
"""

# Machine-readable twin of the "Banned constructions" prose above. The gate and
# the prompt must never drift: this tuple is the single source of truth and the
# prose is its description. Context-sensitive entries (cannot_be_excluded,
# stable_without_numbers) are matched here and refined in report_checks.py.
BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cannot_be_excluded", re.compile(r"cannot be excluded", re.I)),
    ("bare_clinical_correlation", re.compile(
        r"clinical correlation (?:is )?(?:recommended|advised|suggested)", re.I)),
    ("no_significant_abnormality", re.compile(r"no significant abnormalit", re.I)),
    ("management_trespass", re.compile(
        r"\b(?:physiotherapy|rehabilitation|immobilisation|analgesia|"
        r"conservative management|operative management|surgical technique|"
        r"commence|prescribe|dosing)\b", re.I)),
)

# Confidence terms from the lexicon, used to decide whether a hedge is calibrated.
LEXICON_TERMS: tuple[str, ...] = (
    "diagnostic of", "consistent with", "probable", "likely represents",
    "possible", "may represent", "unlikely",
)
