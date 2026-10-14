# Skill Sheet: CT Coronary Angiogram (Siemens Dual Source)

## Scan Context
Modality: CT Coronary Angiogram (CTCA) on a Siemens Dual Source Flash multidetector scanner. Technique: prospective ECG-gated acquisition, axial cross sections, supine position, inspiratory breath hold, with 3D reformation on a separate workstation. Clinical setting: chest pain assessment, oncology/risk factor surveillance, pre-operative planning (e.g. valve replacement).

## Voice
Concise, telegraphic radiology prose. In a normal study, vessel descriptions are one or two short declarative sentences ("Normal proximal segment.", "Good calibre normal OM2 with vestigial LCx."). Abnormal findings open with "There is" or "There are" followed by the specific finding and its location. Vessel descriptions are sequenced anatomically and kept as brief as possible, using "Normal" as a one-word qualifier before the segment or vessel. Measurements are embedded in the sentence without a separate label. Stenosis is always stated as a qualitative descriptor followed by "stenosis" and a bracketed percentage range (e.g. "minimal stenosis (1-24%)", "mild stenosis (25-49%)"). The word "calibre" is used consistently (British spelling). Comparison with prior imaging uses "since the previous [modality] from [date]" or "the previous [modality] from [date] demonstrated…" Recommendations are integrated as a final clause in the finding sentence (e.g. "requires follow-up with a CT thorax in 3 months time", "recommend further assessment with ultrasound").

## Report Structure
SECTION FINDINGS | header: none | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
TERM PREFER "calibre"

## Paragraph: Coronary Calcium Scoring (FINDINGS) | header: "Coronary calcium scoring:"
COVERS ["coronary calcium score"]
Opening: "Prospective ECG-gated coronary calcium scoring was performed initially using a Siemens Dual Source Flash multidetector scanner. The Agatston score is {score}."
Order: Fixed technique sentence, then Agatston score, then the breakdown "(LMS={x}; LAD={y}; LCx={z}; RCA={w})" for a score above 0.
Measurement: The score follows the technique sentence: "The Agatston score is {score}."
FIXED "Prospective ECG-gated coronary calcium scoring was performed initially using a Siemens Dual Source Flash multidetector scanner."
RULE WHEN [context: coronary calcium scoring was not performed] REPLACE "Prospective ECG-gated coronary calcium scoring was performed initially using a Siemens Dual Source Flash multidetector scanner." WITH "Coronary calcium scoring was not performed due to {reason}."

## Paragraph: CTCA Procedure (FINDINGS) | header: "CTCA Procedure:"
COVERS ["CTCA technique"]
Opening: "Prospective ECG gated coronary CT angiography was performed using a Siemens Dual Source Flash multidetector scanner."
Order: Fixed technique text (three sentences).
FIXED "Prospective ECG gated coronary CT angiography was performed using a Siemens Dual Source Flash multidetector scanner. Axial cross sections of the heart were acquired with the patient in the supine position upon inspiratory breath hold. A separate workstation was used for 3D reformation of the dataset."
RULE WHEN [context: CTCA was not performed] REPLACE "Prospective ECG gated coronary CT angiography was performed using a Siemens Dual Source Flash multidetector scanner. Axial cross sections of the heart were acquired with the patient in the supine position upon inspiratory breath hold. A separate workstation was used for 3D reformation of the dataset." WITH "CT coronary angiography was not performed due to {reason}."

## Paragraph: Scan Parameters (FINDINGS)
COVERS ["medication" | "scan quality" | "heart rate" | "radiation dose"]
Order: Medication given, scan quality, average heart rate, total radiation dose — one line each, in that order.
RULE WHEN [context: CTCA was performed and the medication given is stated] USE "Medication given: {medication}."
RULE WHEN [context: CTCA was performed and the scan quality is stated] USE "Scan quality: {quality}"
RULE WHEN [context: CTCA was performed and the average heart rate is stated] USE "Average HR: {rate} bpm."
RULE WHEN [context: the total radiation dose is stated] USE "Total radiation dose: {dose} mGycm."

## Paragraph: Coronary Findings (FINDINGS) | header: "Coronary Findings:"
COVERS ["CORONARY DOMINANCE" | "LMS" | "LAD" | "LCx" | "RCA"]
Opening: Dominance and origins statement, e.g. "Right coronary dominance with normal coronary artery origins." or "Right dominant system." or "Left coronary dominance. Normal coronary origins."
Order: Dominance/origins → LMS → LAD (including D1, D2, etc.) → Ramus Intermedius (optional, with branches) → LCx (including OM1, OM2, etc.) → RCA (with branches). Each main vessel starts on a new line prefixed with the vessel name and a colon. Branch vessels (D1, D2, OM1, OM2, PDA, PLV) are described within the parent vessel line and do not start on a new line.
Abnormal pattern: "There is minimal myocardial bridging within the mid LAD which measures maximally 3 mm in depth and 19 mm in length."
Abnormal pattern: "Assessment is limited due to small calibre vessels; there is non-calcified plaque within the mid LAD and at the origin of D2 resulting in stenosis (1-24%)."
Abnormal pattern: "There is an acute angulation to the right immediately after the origin with normal appearances of the proximal and mid RCA."
Abnormal pattern: "There is a supra dominant wraparound anatomy which supplies the inferior aspect of the heart."
Interpretive phrasing: "in keeping with the infarct as seen on {modality/date}"
Measurement: Stenosis is stated as qualitative descriptor + "stenosis" + bracketed percentage range: "minimal stenosis (1-24%)", "mild stenosis (25-49%)". Vessel calibre is described qualitatively ("small calibre", "good calibre", "large calibre"). Myocardial bridging is measured in depth and length: "measures maximally {depth} mm in depth and {length} mm in length."
NORMAL [LMS] "LMS: Normal."
NORMAL [LAD] "LAD: Normal proximal, mid and distal LAD."
NORMAL [LCx] "LCx: Normal proximal and distal LCx."
NORMAL [RCA] "RCA: Normal proximal, mid and distal RCA."

## Paragraph: Other Findings (FINDINGS) | header: "Other findings:"
COVERS ["CARDIAC CHAMBERS" | "LEFT ATRIAL APPENDAGE" | "LUNGS" | "MEDIASTINAL LYMPH NODES" | "EFFUSIONS" | "GREAT VESSELS" | "UPPER ABDOMINAL VISCERA" | "BONES"]
Opening: "Normal appearance of the cardiac chambers." (normal) or an abnormal chamber statement (e.g. "The right ventricle is slightly enlarged.").
Order: Cardiac chambers → LAA (thrombus or visualization status) → Lungs/Mediastinum → Effusions → Great vessels (aorta/PA) → Upper abdomen → Bones.
Abnormal pattern: "The tip of the left atrial appendage is not completely visualised."
Abnormal pattern: "This is a partially expiratory phase study with no suspicious parenchymal nodules or pleurally-based abnormality."
Abnormal pattern: "There is mild generalised bronchial wall thickening."
Abnormal pattern: "There are multiple subacute right-sided rib fractures with periosteal reaction/callus formation."
Abnormal pattern: "Shallow left pleural effusion with mild bibasal atelectasis."
Abnormal pattern: "There is an ill-defined liver lesion which is partially visualised (series {series} image {image})."
Abnormal pattern: "There is appearance of mosaicism within the lungs which may be attributable to pulmonary hypertension."
Abnormal pattern: "The pulmonary artery is prominent measuring up to {measurement} mm (the aorta measures up to {measurement} mm)."
Interpretive phrasing: "that is likely infective/inflammatory"
Interpretive phrasing: "I note that the previous echo from {date} demonstrated a normal-sized PA."
NORMAL [CARDIAC CHAMBERS] "Normal appearance of the cardiac chambers."
NEGATIVE "No left atrial appendage thrombus."
NEGATIVE "No suspicious parenchymal nodules."
NEGATIVE "No mediastinal or hilar lymph enlargement."
NEGATIVE "No pleural or pericardial effusion."
NORMAL [GREAT VESSELS] "Normal calibre aortic root and pulmonary trunk."
NORMAL [UPPER ABDOMINAL VISCERA] "Normal upper abdominal viscera."
NEGATIVE "No aggressive osseous lesion."
RULE WHEN [context: the tip of the left atrial appendage is not completely visualised] REPLACE "No left atrial appendage thrombus." WITH "The tip of the left atrial appendage is not completely visualised."

## Paragraph: Conclusion (CONCLUSION)
Opening: In a normal study, a single sentence: "The Agatston score is {score} with no evidence of coronary artery disease." In an abnormal study, a numbered list beginning "1) …"
Order: Item 1: Calcium score (with breakdown if score > 0, with percentile if elevated) or the applicable study statement. Item 2: Coronary stenosis summary by vessel/severity, or "Normal coronary arteries.", or dominance + normal coronaries. Item 3 (optional): Significant incidental findings or urgent findings with recommendations.

## Impression Construction
### Quoted examples

1. "The Agatston score is 0 with no evidence of coronary artery disease."

2. "1) Agatston score is 139 (LMS=0; LAD=9; LCx=0; RCA=130). This lies above the 75th percentile for age and gender matched controls. 2) minimal stenosis (1-24%) within the proximal D1 due to calcified plaque. mild stenosis (25-49%) in the LAD, LCx and RCA due to calcified/partially calcified plaque. 3) There is right lower lobe ground glass opacification which is likely infective/inflammatory. There is also a 13 mm lower paratracheal node which appears stable since the previous CMR from October 2025 but requires follow-up with a CT thorax in 3 months time."

3. "1) Technically very limited study. The proximal coronaries arteries appear patent but beyond this assessment is limited. 2) Bilateral lower zone collapse/consolidation with debris/mucus plugging of the right middle and lower lobe bronchus."

4. "1) The Agatston score is 0. 2) Minimal stenosis (1-24%) within the mid LAD and at the origin of D2 due to non-calcified plaque. 3) Multiple subacute right-sided rib fractures with periosteal reaction/callus formation are demonstrated, likely accounting for the chest pain."

5. "1) Agatston score is 0. 2) Normal coronary arteries. 3) Shallow left pleural effusion with mild bibasal atelectasis."

6. "1) Coronary calcium scoring was not performed due to patient age. 2) Left coronary dominance. Normal coronary arteries. The right ventricle is slightly enlarged. 3) There is an ill-defined liver lesion which is partially visualised and cannot be seen on the previous CT abdomen and pelvis from 2016; recommend further assessment with ultrasound."

7. "1) The Agatston score is 86 (LMS=15; LAD=70; LCx=0; RCA=1). 2) CT coronary angiography was not performed due to uncontrolled atrial fibrillation with tachycardia. 3) Prominent pulmonary artery and pulmonary mosaicism which may be attributable to pulmonary hypertension; this differs from the previous echo in November 2025 which demonstrated a normal-sized pulmonary artery."

### Sentence construction pattern
In a normal study: a single sentence combining the calcium score and the main diagnosis. Pattern: "The Agatston score is {score} with no evidence of coronary artery disease." (Parenthetical breakdown included only if score > 0.)
In an abnormal study: a numbered list.
- Item 1: Calcium score details + percentile (if applicable), or statement of what was not performed (calcium scoring or CTCA).
- Item 2: Summary of coronary stenosis by vessel and severity, or "Normal coronary arteries.", or dominance + "Normal coronary arteries."
- Item 3 (optional): Significant incidental findings or urgent findings with recommendations.

### Inclusion logic
Impression-worthy: any stenosis, Agatston score elevation (with percentile), significant extracardiac pathology (infection, lymph nodes requiring follow-up, consolidation, rib fractures accounting for symptoms), urgent findings (pleural effusion), technical limitations, CTCA or calcium scoring not performed.
Findings only: normal variant anatomy (vestigial vessels), non-specific mild findings without clinical impact, stable small nodes not requiring follow-up.

### Recommendation phrasing
Integrated into the finding sentence or as a final clause in the numbered item.
"requires follow-up with a CT thorax in 3 months time."
"recommend further assessment with ultrasound."

### Restatement rules
Agatston breakdown (if score > 0) and lymph node size are restated in the impression. Stenosis percentages and qualitative descriptors are restated. Comparison stability ("stable since the previous CMR") is added in the impression.

## Measurement and Grading
Agatston score: reported as "The Agatston score is {score}." with parenthetical breakdown "(LMS={x}; LAD={y}; LCx={z}; RCA={w})" when score is greater than 0. When the score is 0, the parenthetical breakdown is omitted.
Percentile: "This lies above the 75th percentile for age and gender matched controls." (used when the score is elevated).
Lymph nodes: measured in mm. "14 mm lower paratracheal lymph node."
Stenosis: qualitative descriptor + "stenosis" + bracketed percentage range. Tiers: "minimal stenosis (1-24%)", "mild stenosis (25-49%)".
Vessel calibre: qualitative only ("small calibre", "good calibre", "large calibre").
Myocardial bridging: "measures maximally {depth} mm in depth and {length} mm in length."
Pulmonary artery: "measuring up to {measurement} mm" with aortic comparison "(the aorta measures up to {measurement} mm)."

## Reference Values
75th percentile for age and gender matched controls: "This lies above the 75th percentile for age and gender matched controls."

## Incidental Findings
Placed within the "Other findings" paragraph. Described specifically and descriptively (e.g. "small sliding hiatus hernia", "interspersed intrapulmonary lymph nodes"). Inclusion threshold: pathology that requires follow-up or explains symptoms (e.g. pneumonia/consolidation, rib fractures accounting for chest pain). Findings requiring management or follow-up, or urgent findings (e.g. pleural effusion), are listed in the Conclusion.

## Domain Rules
Scanner specification: always "Siemens Dual Source Flash multidetector scanner."
LAA: always explicitly comment on thrombus or visualization status.
Bone: the standard statement is "No aggressive osseous lesion" (not "Normal bones").
Stenosis format: all stenosis mentions use the format [qualitative descriptor] stenosis ([percentage in brackets]).
When CTCA is not performed, the entire Coronary Findings paragraph (header and all vessel descriptions) is omitted from the report.
When coronary calcium scoring is not performed, the calcium scoring paragraph states the reason and the technique text is replaced with the not-performed sentence.
Branch vessels (D1, D2, OM1, OM2, PDA, PLV) are integrated into the parent vessel description line and do not start on a new line.

## Open Questions
[NEEDS CLARIFICATION] Report 3 omits the dominance/origins line at the start of Coronary Findings, but the old sheet lists dominance as a mandatory field. Unclear whether this is an acceptable omission or an error in the report.
[NEEDS CLARIFICATION] Report 4 places D1 and OM1 on their own lines with vessel-name prefixes, contradicting the old sheet rule that branch vessels "are included within the parent vessel description and do not start on new lines." The old sheet's rule is retained here.
[NEEDS CLARIFICATION] Report 4 shows a visible "FINDINGS" header at the top of the report, but the old sheet specifies the FINDINGS section has no header. Unclear whether the radiologist sometimes adds it.
[NEEDS CLARIFICATION] Report 1 contains "This is a partially expiratory phase study with no suspicious parenchymal nodules or pleurally-based abnormality." This sentence is not in the old sheet and appears to be a case-specific technical note about the acquisition phase. Its status as a routine statement or a one-off observation is unclear.
[NEEDS CLARIFICATION] The old sheet lists "No mediastinal or hilar lymph enlargement" under the "Lungs" heading in Negative Finding Rules, but the statement refers to lymph nodes rather than lung parenchyma. It has been assigned to the MEDIASTINAL LYMPH NODES structure.
