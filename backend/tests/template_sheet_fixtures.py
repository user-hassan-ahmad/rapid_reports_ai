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
