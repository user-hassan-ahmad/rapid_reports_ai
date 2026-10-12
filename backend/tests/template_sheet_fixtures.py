"""Shared grammar sheets for the template save, routes, writer and refine tests."""

GOOD = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Knee (FINDINGS)
COVERS ["menisci"]
NORMAL [menisci] "The menisci are intact."
"""
BAD_UNIT = GOOD + 'NORMAL [cartilage] "Mild chondral thinning."\n'
