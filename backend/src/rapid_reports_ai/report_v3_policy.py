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

### Hedging that does no work
Two constructions are never acceptable, because each defers a judgement without leaving anyone
able to act on it:
- "cannot be excluded" without both a confidence term and something that would resolve it
- "clinical correlation recommended" standing alone, with nothing named to correlate against

### Scope
A report states what the imaging establishes and stops there. That boundary follows from two
facts, not from a list of forbidden words: the study contains only what it contains, and the
radiologist is not the clinician answerable for the patient.

Within scope, because the images bear on it: what is present, absent, or not assessable, and
where; what it most likely means and at what confidence; whether it accounts for the
presentation; what would resolve what remains open — a further investigation, tissue, a named
correlation, a prior study; and who should see this, how urgently.

Outside it, because deciding these needs what the study does not contain: what is then done about
that understanding. Treatment, drug and dose, operative versus conservative choice, procedural
technique, hardware, immobilisation, rehabilitation, the intensity and interval of clinical
monitoring — each turns on physiology, comorbidity, fitness, and the patient's own wishes. The
images show none of that, and whoever weighs it carries a responsibility the reporting
radiologist does not.

The test for any sentence you are about to write: does it report what the imaging establishes, or
decide what someone should do about it? Naming the specialty that should review is the first.
Naming what that specialty should then do is the second.
"""

POLICY_REPORT = """## REPORT POLICY — the report itself

### What earns a place in the impression
FINDINGS documents everything the study shows. The impression is narrower by design: it carries
what changes the reader's understanding or their next move, and a sentence that does neither
lengthens the report without improving it.

An incidental therefore reaches the impression when it requires an action, carries malignant
potential, or crosses a threshold to which a guideline attaches consequence. An incidental
meeting none of those is fully reported in FINDINGS and belongs nowhere else. Leaving it out of
the impression is editorial judgement, not an omission — selectivity about what deserves the
referrer's attention is a skill the report is expected to exercise.

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

COMPARISON names the prior study and its date. Nothing else: no findings, no measurements, no
interval commentary.

### Interval change
Where the dictation reports a lesion as changed or unchanged against a prior, the numbers go in
FINDINGS beside the lesion they describe — "8 mm, previously 6 mm on 12/02/2026" — never
"stable" on its own. A bare "stable" states a judgement while withholding what it rests on, so
the reader cannot check it.

### TECHNIQUE
Strictly protocol description. Never carries assessment disclosures or limitation commentary.
"""

# Detection heuristics for the gate. NOT a mirror of the prose above: the prompt
# teaches scope from first principles precisely because a blocklist only ever
# catches what someone already enumerated (L-28's lesson about the contradiction
# pair list, whose silence read as safety for the whole programme).
#
# The two hedging entries do correspond to stated rules. `management_trespass`
# deliberately does not - it is a cheap screen for the residue the scope
# principle fails to prevent, and its hit rate is itself a measurement of whether
# the principle is working. A rising rate means the prose needs strengthening,
# not that the regex needs more words.
#
# `cannot_be_excluded` is context-sensitive and refined in report_checks.py.
BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cannot_be_excluded", re.compile(r"cannot be excluded", re.I)),
    ("bare_clinical_correlation", re.compile(
        r"clinical correlation (?:is )?(?:recommended|advised|suggested)", re.I)),
    ("management_trespass", re.compile(
        r"\b(?:physiotherapy|rehabilitation|immobilisation|analgesia|"
        r"conservative management|operative management|surgical technique)\b", re.I)),
)

# Confidence terms from the lexicon, used to decide whether a hedge is calibrated.
LEXICON_TERMS: tuple[str, ...] = (
    "diagnostic of", "consistent with", "probable", "likely represents",
    "possible", "may represent", "unlikely",
)
