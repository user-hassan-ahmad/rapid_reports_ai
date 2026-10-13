"""Shared grammar sheets for the template save, routes, writer and refine tests."""

GOOD = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Knee (FINDINGS)
COVERS ["menisci"]
NORMAL [menisci] "The menisci are intact."
"""
BAD_UNIT = GOOD + 'NORMAL [cartilage] "Mild chondral thinning."\n'


# A lint-clean sheet with a technique section, a findings paragraph (COVERS two structures, one NORMAL, one
# NEGATIVE, one patient-variable FIXED line) and a free-prose Voice block quoting the NORMAL.
LEDGER_SHEET = """# Skill Sheet: Ledger test

## Voice
Prose about the voice. Quoted: "The liver is normal in size."

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Report-wide
TERM PREFER "hepatic"

## Paragraph: Technique (TECHNIQUE)
Opening: "Axial images were acquired."
FIXED "Axial images were acquired."

## Paragraph: Liver (FINDINGS)
COVERS ["liver" | "gallbladder"]
Opening: "The liver"
NORMAL [liver] "The liver is normal in size."
NEGATIVE "No focal liver lesion."
FIXED "No previous imaging available."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""


# The chat-edit router's sheet: a value list, two FIXED lines, two findings paragraphs (one NORMAL + one NEGATIVE,
# and one NORMAL), prose blocks (Voice, an Opening line, Impression Construction) and a Scan Context the style call
# never sees. Abstract names keep the router's tests case-agnostic.
ROUTER_SHEET = """# Skill Sheet: Router test

## Scan Context
An imaging study of one body region.

## Voice
Sentences are short and declarative.

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Report-wide
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Width" | "Depth"] AT TOP | section: FINDINGS

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired."
FIXED "No previous imaging available."

## Paragraph: Upper (FINDINGS)
COVERS ["alpha" | "beta"]
Opening: The paragraph opens with alpha.
NORMAL [alpha] "Alpha is normal."
NEGATIVE "No beta abnormality."

## Paragraph: Lower (FINDINGS)
COVERS ["gamma"]
NORMAL [gamma] "Gamma is normal."

## Paragraph: Impression (IMPRESSION)
Opening: The impression opens with the main finding.

## Impression Construction
Lead with the most important finding.
Keep it brief.
"""

# The same sheet with the comparison concept written by the Rules step: its FIXED default plus a standard REPLACE.
ROUTER_SHEET_CONCEPT = ROUTER_SHEET.replace(
    'FIXED "No previous imaging available."\n',
    'FIXED "No previous imaging available."\n'
    'RULE WHEN [context: the dictation names a previous imaging study for comparison] '
    'REPLACE "No previous imaging available." WITH "Compared with the {study} of {date}."\n')


# LEDGER_SHEET with a second findings paragraph ("Lower", covering "delta"), so a habit can be placed by paragraph name
# or by a structure a paragraph covers.
HABIT_SHEET = LEDGER_SHEET.replace(
    "## Paragraph: Impression (IMPRESSION)",
    '## Paragraph: Lower (FINDINGS)\nCOVERS ["delta"]\nNORMAL [delta] "Delta is normal."\n\n'
    "## Paragraph: Impression (IMPRESSION)")
