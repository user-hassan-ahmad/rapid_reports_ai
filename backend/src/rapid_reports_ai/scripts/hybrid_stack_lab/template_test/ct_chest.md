# Skill Sheet: CT Chest with Contrast

## Scan Context
Contrast-enhanced CT of the thorax for respiratory symptoms, staging and follow-up. Findings are grouped into a few broad regional paragraphs.

## Report Structure
SECTION INDICATION | header: "Indication:" | role: history
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION COMPARISON | header: "Comparison:" | role: comparison | optional: yes
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression

## Paragraph: Indication (INDICATION)
Opening: The clinical question as given by the referrer.

## Paragraph: Technique (TECHNIQUE)
FIXED "CT thorax following intravenous contrast."

## Paragraph: Comparison (COMPARISON)
Opening: The date and modality of the prior study.

## Paragraph: Lungs and Airways (FINDINGS)
COVERS ["lung parenchyma" | "pulmonary nodules" | "trachea" | "main bronchi" | "segmental airways"]
NORMAL [lungs] "The lungs are clear with no suspicious pulmonary nodule or consolidation. The central airways are patent."

## Paragraph: Mediastinum, Hila and Heart (FINDINGS)
COVERS ["mediastinal lymph nodes" | "hilar lymph nodes" | "heart" | "pericardium" | "thoracic aorta" | "pulmonary arteries" | "oesophagus" | "thyroid"]
NORMAL [mediastinum] "There is no mediastinal or hilar lymphadenopathy. The heart is normal in size with no pericardial effusion. The thoracic aorta and pulmonary arteries are normal in calibre."

## Paragraph: Pleura and Chest Wall (FINDINGS)
COVERS ["pleura" | "chest wall" | "axillae" | "breasts"]
NORMAL [pleura] "There is no pleural effusion or thickening. The chest wall and axillae are unremarkable."

## Paragraph: Upper Abdomen and Bones (FINDINGS)
COVERS ["upper abdomen" | "liver" | "adrenal glands" | "thoracic spine" | "ribs" | "sternum" | "shoulder girdles"]
NORMAL [upper abdomen] "The included upper abdomen is unremarkable. There is no aggressive bone lesion."

## Paragraph: Impression (IMPRESSION)
Opening: Normal study: "No significant thoracic abnormality." Abnormal study: numbered list, primary finding first, recommendation last.
