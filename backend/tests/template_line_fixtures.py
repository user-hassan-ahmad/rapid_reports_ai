"""Two writer outputs for the same synthetic example reports (stable line IDs spec, rebuild fixture). REBUILD_B is a
rebuild of REBUILD_A with planted changes: paragraphs reordered, one renamed (same COVERS), small rewordings (a dropped
full stop, a filler; new slots under exact matching, decision 7), a reworded NORMAL, real wording changes, adversarial
near-misses (pleural/pericardial, left/right), a dropped and an added line. SAME lists every (A line, B line) pair that
is the same slot; any other uid carried from A is a wrong match."""

REBUILD_A = """# Skill Sheet: Rebuild fixture

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired after contrast."
FIXED "No previous imaging is available."

## Paragraph: Liver (FINDINGS)
COVERS ["liver" | "gallbladder"]
NORMAL [liver] "The liver is normal in size and attenuation."
NORMAL [gallbladder] "The gallbladder is unremarkable."
NEGATIVE "No focal liver lesion."
NEGATIVE "No biliary dilatation."

## Paragraph: Chest base (FINDINGS)
COVERS ["lung bases" | "pleura"]
NORMAL [lung bases] "The lung bases are clear."
NEGATIVE "No pleural effusion."
NEGATIVE "No left basal consolidation."

## Paragraph: Kidneys (FINDINGS)
COVERS ["kidneys"]
NORMAL [kidneys] "The kidneys are normal."
NEGATIVE "No hydronephrosis."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""

REBUILD_B = """# Skill Sheet: Rebuild fixture

## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Technique (TECHNIQUE)
FIXED "Axial images were acquired after contrast"
FIXED "No prior imaging available."

## Paragraph: Hepatobiliary (FINDINGS)
COVERS ["liver" | "gallbladder"]
NORMAL [liver] "Normal liver size and attenuation."
NORMAL [gallbladder] "The gallbladder is unremarkable."
NEGATIVE "There is no focal liver lesion"
NEGATIVE "No biliary duct dilatation."

## Paragraph: Kidneys (FINDINGS)
COVERS ["kidneys" | "ureters"]
NORMAL [kidneys] "The kidneys are normal."
NORMAL [ureters] "The ureters are normal."
NEGATIVE "No hydronephrosis."

## Paragraph: Chest base (FINDINGS)
COVERS ["lung bases" | "pleura"]
NORMAL [lung bases] "The lung bases are clear."
NEGATIVE "No pericardial effusion."
NEGATIVE "No right basal consolidation."

## Paragraph: Impression (IMPRESSION)
Opening: "Normal study."
"""

# (A line, B line) of every line-bound unit that is the same slot in both (paragraphs by name). The reworded liver
# NORMAL in the renamed paragraph is NOT the same slot (spec decision 5: across a rename a normal needs its own text),
# nor are the FIXED line that lost its full stop and the NEGATIVE that gained "There is" (decision 7: exact matching).
SAME = [
    ('NORMAL [gallbladder] "The gallbladder is unremarkable."', 'NORMAL [gallbladder] "The gallbladder is unremarkable."'),
    ('NORMAL [lung bases] "The lung bases are clear."', 'NORMAL [lung bases] "The lung bases are clear."'),
    ('NORMAL [kidneys] "The kidneys are normal."', 'NORMAL [kidneys] "The kidneys are normal."'),
    ('NEGATIVE "No hydronephrosis."', 'NEGATIVE "No hydronephrosis."'),
    ("Paragraph: Liver", "Paragraph: Hepatobiliary"),
    ("Paragraph: Chest base", "Paragraph: Chest base"),
    ("Paragraph: Kidneys", "Paragraph: Kidneys"),
    ("Paragraph: Technique", "Paragraph: Technique"),
    ("Paragraph: Impression", "Paragraph: Impression"),
]
