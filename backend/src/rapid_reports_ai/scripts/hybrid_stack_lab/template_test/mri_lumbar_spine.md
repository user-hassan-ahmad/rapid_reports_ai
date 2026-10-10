# Skill Sheet: MRI Lumbar Spine

## Scan Context
Non-contrast MRI of the lumbar spine for back pain and radiculopathy. Findings are reported level by level from T12/L1 to L5/S1, after alignment and the conus.

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history:" | role: history
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION COMPARISON | header: "Comparison:" | role: comparison | optional: yes
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Paragraph: Clinical History (CLINICAL HISTORY)
Opening: The referrer's history, including the side and distribution of symptoms.

## Paragraph: Technique (TECHNIQUE)
FIXED "Sagittal T1, T2 and STIR, and axial T2-weighted images of the lumbar spine."

## Paragraph: Comparison (COMPARISON)
Opening: The date and modality of the prior study.

## Paragraph: Alignment and Vertebrae (FINDINGS)
COVERS ["lumbar alignment" | "vertebral bodies" | "vertebral marrow" | "posterior elements"]
NORMAL [alignment] "Normal lumbar lordosis and alignment. The vertebral body heights and marrow signal are preserved."

## Paragraph: Conus and Cord (FINDINGS)
COVERS ["conus medullaris" | "distal spinal cord" | "cauda equina"]
NORMAL [conus] "The conus terminates normally at L1 and returns normal signal. The cauda equina nerve roots are normal."

## Paragraph: T12/L1 (FINDINGS)
COVERS ["T12/L1 disc" | "T12/L1 spinal canal" | "T12/L1 neural foramina" | "T12/L1 facet joints"]
NORMAL [T12/L1] "T12/L1: normal disc. No canal or foraminal stenosis."

## Paragraph: L1/2 (FINDINGS)
COVERS ["L1/2 disc" | "L1/2 spinal canal" | "L1/2 neural foramina" | "L1/2 facet joints"]
NORMAL [L1/2] "L1/2: normal disc. No canal or foraminal stenosis."

## Paragraph: L2/3 (FINDINGS)
COVERS ["L2/3 disc" | "L2/3 spinal canal" | "L2/3 neural foramina" | "L2/3 facet joints"]
NORMAL [L2/3] "L2/3: normal disc. No canal or foraminal stenosis."

## Paragraph: L3/4 (FINDINGS)
COVERS ["L3/4 disc" | "L3/4 spinal canal" | "L3/4 lateral recesses" | "L3/4 neural foramina" | "L3/4 facet joints"]
NORMAL [L3/4] "L3/4: normal disc. No canal or foraminal stenosis."

## Paragraph: L4/5 (FINDINGS)
COVERS ["L4/5 disc" | "L4/5 spinal canal" | "L4/5 lateral recesses" | "L4/5 neural foramina" | "L4/5 facet joints"]
NORMAL [L4/5] "L4/5: normal disc. No canal or foraminal stenosis."

## Paragraph: L5/S1 (FINDINGS)
COVERS ["L5/S1 disc" | "L5/S1 spinal canal" | "L5/S1 lateral recesses" | "L5/S1 neural foramina" | "L5/S1 facet joints"]
NORMAL [L5/S1] "L5/S1: normal disc. No canal or foraminal stenosis."

## Paragraph: Other Findings (FINDINGS)
COVERS ["sacroiliac joints" | "paraspinal muscles" | "retroperitoneum" | "kidneys"]
NORMAL [other] "The sacroiliac joints and paraspinal soft tissues are unremarkable."

## Paragraph: Conclusion (CONCLUSION)
Opening: Normal study: "Normal MRI lumbar spine." Abnormal study: numbered list by clinical significance, naming the level and the affected nerve root.
