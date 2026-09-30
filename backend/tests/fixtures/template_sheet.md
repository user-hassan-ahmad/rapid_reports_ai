# Skill Sheet: CT Abdomen and Pelvis

## Scan Context
- Modality: CT Abdomen and Pelvis

## Structural Pattern
- Sections included, in order:
  - CLINICAL HISTORY
  - FINDINGS (implicit header)
  - IMPRESSION
- For each section:
  - CLINICAL HISTORY: `header: "CLINICAL HISTORY"`
  - FINDINGS: always present, `header: none`
  - IMPRESSION: always present, `header: "Impression"`

## Fixed Blocks
None identified in provided examples.

## Per-Section Construction Rules

### Primary Pathology Paragraph
- **header**: `none`
- **Mandatory negatives**:
  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."
  - "No periappendiceal collection." (if appendicitis)
- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."

## Terminology Rules
- **Preferred terms**: "unremarkable", "size significant".
- **Suppressed terms**: "normal" (prefers "unremarkable").

## Interpretive Clause Rules
- IF [inflammatory morphology] THEN append "consistent with {diagnosis}."

## Conditional Suppression Rules
- IF [pneumoperitoneum is present] THEN suppress "No pneumoperitoneum." AND replace with "Free intra-abdominal air is present."
- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.

## Impression Construction Rules

### Quoted examples
1. "Uncomplicated acute appendicitis."

### Inclusion logic
- Promoted to Impression: primary pathology.

### Normal study impression
- "No acute intra-abdominal abnormality."

## Negative Finding Rules
- "No pneumoperitoneum."
