# Skill Sheet: Cardiac MRI – Cardiomyopathy / Viability (1.5 T)

## Scan Context
Cardiac MRI at 1.5 T for evaluation of suspected or known cardiomyopathy, myocardial viability, and related questions (aetiology, hypertrophic cardiomyopathy, myocarditis). Two protocol variants appear: the standard protocol (Cine SSFP, T2 STIR, native T1/T2 mapping, post-contrast T1 mapping, LGE) and the viability protocol (Cine SSFP and LGE only, with T2 and parametric mapping explicitly not acquired). The typical clinical question is aetiology of a dilated or hypertrophied ventricle, viability assessment prior to revascularisation, or characterisation of a first-degree relative in a familial cardiomyopathy.

## Voice
Sentences are short, declarative, and densely packed with quantitative data. Each anatomical compartment gets its own paragraph, opening with "The left ventricle is…" or "The right ventricle is…" followed immediately by size, wall, and function in a fixed order, then a run of measurements in a single sentence. Abnormal findings are stated without hedging ("severely impaired", "moderately dilated") and attributed mechanism is appended in a trailing clause ("due to global hypokinesia", "secondary to annular dilatation"). Interpretive language is concise and confident: "in keeping with", "fulfilling the updated Lake Louise criteria", "in a non-ischaemic distribution", "indicate diffuse interstitial expansion". Recommendations are always the final numbered item, introduced by "Suggest" followed by an infinitive phrase. The normal-study conclusion is a single two-sentence line with no numbering.

## Report Structure
SECTION CLINICAL DETAILS | header: "Clinical details:" | role: history
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION TISSUE CHARACTERISATION | header: "Tissue characterisation:" | role: findings
SECTION LATE GADOLINIUM ENHANCEMENT | header: "Late gadolinium enhancement:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
TERM PREFER "non-ischaemic"
TERM PREFER "interstitial expansion"
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEDVi" | "LVESVi" | "LVEF" | "LV mass index" | "RVEDVi" | "RVESVi" | "RVEF"] AT TOP
RULE WHEN [context: viability protocol was performed and T2-weighted imaging and parametric mapping were not acquired] SUPPRESS_SECTION TISSUE CHARACTERISATION | section: TISSUE CHARACTERISATION

## Paragraph: Clinical Details (CLINICAL DETAILS)
Opening: The section reproduces the referring clinician's text verbatim, beginning with the presenting complaint or prior imaging finding.

## Paragraph: Technique (TECHNIQUE)
Opening: Always begins "Cardiac MRI at 1.5 T."
FIXED "Cardiac MRI at 1.5 T. Cine SSFP imaging in standard long- and short-axis planes, T2-weighted STIR, native T1 and T2 mapping, post-contrast T1 mapping and late gadolinium enhancement imaging following 0.1 mmol/kg gadobutrol."
FIXED "Cardiac MRI at 1.5 T (viability protocol). Cine SSFP imaging in standard long- and short-axis planes and late gadolinium enhancement imaging following 0.1 mmol/kg gadobutrol. T2-weighted imaging and parametric mapping were not acquired."
RULE WHEN [context: viability protocol was performed] REPLACE "Cardiac MRI at 1.5 T. Cine SSFP imaging in standard long- and short-axis planes, T2-weighted STIR, native T1 and T2 mapping, post-contrast T1 mapping and late gadolinium enhancement imaging following 0.1 mmol/kg gadobutrol." WITH "Cardiac MRI at 1.5 T (viability protocol). Cine SSFP imaging in standard long- and short-axis planes and late gadolinium enhancement imaging following 0.1 mmol/kg gadobutrol. T2-weighted imaging and parametric mapping were not acquired."

## Paragraph: Left Ventricle (FINDINGS)
COVERS ["left ventricular chamber" | "left ventricular wall" | "left ventricular segments" | "left ventricular volumes" | "left ventricular mass" | "left ventricular outflow tract"]
Opening: "The left ventricle is normal in size and wall thickness with preserved systolic function and no regional wall motion abnormality." (normal); "The left ventricle is moderately dilated with normal wall thickness and severely impaired systolic function due to global hypokinesia." (abnormal); "The left ventricle is mildy dilated with thinning of the apical and mid anterior walls (end-diastolic thickness 4 mm) and severely impaired systolic function." (viability); "The left ventricle is normal in size with asymmetric septal hypertrophy, maximal end-diastolic wall thickness 19 mm in the basal anteroseptum (basal inferolateral wall 9 mm)." (HCM).
Order: chamber size → wall thickness (and specific segment if abnormal) → systolic function (qualifier) → regional wall motion (segmental description if abnormal) → LVOT/SAM (optional, HCM only) → measurements (LVEDVi, LVESVi, LVEF, LV mass index) in one sentence.
Abnormal pattern: "The left ventricle is moderately dilated with normal wall thickness and severely impaired systolic function due to global hypokinesia."
Abnormal pattern: "The left ventricle is mildly dilated with thinning of the apical and mid anterior walls (end-diastolic thickness 4 mm) and severely impaired systolic function. The apex and apical segments are akinetic with a small apical aneurysm; the mid anterior and anteroseptal segments are severely hypokinetic."
Abnormal pattern: "The left ventricle is normal in size with asymmetric septal hypertrophy, maximal end-diastolic wall thickness {measurement} mm in the {segment} ({contralateral segment} {measurement} mm). Systolic function is hyperdynamic with no regional wall motion abnormality."
Abnormal pattern: "The left ventricle is normal in size and wall thickness with low-normal systolic function and mild hypokinesia of the {segment}."
Interpretive phrasing: "due to global hypokinesia"
Interpretive phrasing: "Systolic function is hyperdynamic with no regional wall motion abnormality."
Measurement: "LVEDVi {value} ml/m², LVESVi {value} ml/m², LVEF {value}%, LV mass index {value} g/m²."
NORMAL [left ventricular chamber] "The left ventricle is normal in size and wall thickness with preserved systolic function and no regional wall motion abnormality."
NEGATIVE "No systolic anterior motion of the mitral valve and no flow acceleration in the left ventricular outflow tract at rest."
RULE WHEN [context: quantitative RV volumes were not acquired] USE "preserved systolic function on visual assessment"
IF_PRESENT [left ventricular hypertrophy] "No apical aneurysm" (contextual) | origin: case

## Paragraph: Right Ventricle (FINDINGS)
COVERS ["right ventricular chamber" | "right ventricular volumes"]
Opening: "The right ventricle is normal in size with preserved systolic function." (normal); "The right ventricle is normal in size with mildly impaired systolic function." (abnormal).
Order: chamber size → systolic function → measurements (RVEDVi, RVESVi, RVEF) in one sentence.
Abnormal pattern: "The right ventricle is normal in size with mildly impaired systolic function."
Measurement: "RVEDVi {value} ml/m², RVESVi {value} ml/m², RVEF {value}%."
NORMAL [right ventricular chamber] "The right ventricle is normal in size with preserved systolic function."
NEGATIVE "No right ventricular free wall thinning" TARGETS [ACM] | origin: case

## Paragraph: Atria and Valves (FINDINGS)
COVERS ["atria" | "heart valves"]
Opening: "The atria are not dilated." (normal); "The left atrium is moderately dilated." (abnormal).
Order: atrial size (both or single if asymmetric) → valvular assessment.
Abnormal pattern: "The left atrium is moderately dilated."
Abnormal pattern: "Moderate functional mitral regurgitation (regurgitant fraction {value}%) secondary to annular dilatation."
Interpretive phrasing: "secondary to annular dilatation"
NORMAL [atria] "The atria are not dilated."
NEGATIVE "No significant valvular regurgitation or stenosis."

## Paragraph: Pericardial and Extracardiac (FINDINGS)
COVERS ["pericardial space" | "pleural spaces" | "extracardiac structures"]
Opening: "No pericardial effusion." (normal); "Small pericardial effusion, up to {measurement} mm adjacent to the {segment}, without haemodynamic compromise." (abnormal).
Order: pericardial space → extracardiac (pleural, mediastinal).
Abnormal pattern: "Small pericardial effusion, up to {measurement} mm adjacent to the {segment}, without haemodynamic compromise."
Abnormal pattern: "Small bilateral pleural effusions."
Measurement: "up to {measurement} mm adjacent to the {segment}"
NEGATIVE "No pericardial effusion."
NEGATIVE "No significant extracardiac findings."

## Paragraph: Tissue Characterisation (TISSUE CHARACTERISATION)
COVERS ["myocardium"]
Opening: "Native T1 {value} ms (local reference range 950–1050 ms at 1.5 T)." (global); "Native T1 {value} ms in the {segment}, remote myocardium {value} ms (local reference range 950–1050 ms at 1.5 T)." (focal).
Order: native T1 (with reference range) → T2 (with reference range) → ECV (with normal threshold) → oedema statement → interpretive sentence if values raised.
Abnormal pattern: "Native T1 {value} ms in the {segment}, remote myocardium {value} ms (local reference range 950–1050 ms at 1.5 T). T2 {value} ms in the {segment} (local reference range 42–52 ms). ECV {value}% in the {segment} (normal <30%)."
Abnormal pattern: "Focal high STIR signal in the {segment}, in keeping with myocardial oedema."
Interpretive phrasing: "Raised native T1 and ECV indicate diffuse interstitial expansion."
Interpretive phrasing: "in keeping with myocardial oedema"
Measurement: "Native T1 {value} ms (local reference range 950–1050 ms at 1.5 T). T2 {value} ms (local reference range 42–52 ms). ECV {value}% (normal <30%)."
FIXED "(local reference range 950–1050 ms at 1.5 T)"
FIXED "(local reference range 42–52 ms)"
FIXED "(normal <30%)"
NEGATIVE "No myocardial oedema."

## Paragraph: Late Gadolinium Enhancement (LATE GADOLINIUM ENHANCEMENT)
COVERS ["myocardium" | "intracardiac space"]
Opening: "No late gadolinium enhancement." (normal); "Linear mid-wall enhancement of the {segment}, in a non-ischaemic distribution." (DCM); "Patchy subepicardial and mid-wall enhancement of the {segment}, in a non-ischaemic distribution." (myocarditis); "Subendocardial enhancement in the {territory} territory: transmural (>75%) in the {segment}." (viability); "Patchy mid-wall enhancement at the anterior and inferior right ventricular insertion points and within the hypertrophied {segment}, approximately {value}% of LV mass." (HCM).
Order: enhancement pattern and location → distribution (ischaemic vs non-ischaemic) → transmural extent by segment (viability only) → viability interpretation (viability only) → subendocardial exclusion (non-ischaemic LGE) → pattern exclusion (HCM) → thrombus.
Abnormal pattern: "Linear mid-wall enhancement of the basal to mid septum, in a non-ischaemic distribution."
Abnormal pattern: "Patchy subepicardial and mid-wall enhancement of the basal to mid inferolateral wall, in a non-ischaemic distribution."
Abnormal pattern: "Patchy mid-wall enhancement at the anterior and inferior right ventricular insertion points and within the hypertrophied basal anteroseptum, approximately {value}% of LV mass."
Abnormal pattern: "Subendocardial enhancement in the {territory} territory: transmural (>75%) in the {segment}, {range}% in the {segment}, and {range}% in the {segment}."
Interpretive phrasing: "in a non-ischaemic distribution"
Interpretive phrasing: "Segments with less than 50% transmural extent are likely to be viable; those with greater than 50% are unlikely to recover function following revascularisation."
Interpretive phrasing: "The pattern of enhancement is not suggestive of cardiac amyloidosis or Anderson–Fabry disease."
Measurement: "approximately {value}% of LV mass"
Measurement: "transmural (>75%) in the {segment}, {range}% in the {segment}, and {range}% in the {segment}"
NORMAL [myocardial enhancement] "No late gadolinium enhancement."
NEGATIVE "No intracardiac thrombus."
NEGATIVE "No subendocardial enhancement to suggest prior infarction."

## Paragraph: Conclusion (CONCLUSION)
Opening: Normal study: "Normal cardiac MRI. No evidence of cardiomyopathy." (two sentences, unnumbered). Abnormal study: numbered list beginning with the primary diagnosis.
Order: primary diagnosis (with key measurement in parentheses) → secondary findings (fibrosis, functional MR, pericardial effusion) → viability statement (viability studies only) → recommendation (always last).
Abnormal pattern: "Dilated left ventricle with severely impaired systolic function (LVEF {value}%) and mildly impaired right ventricular function."
Abnormal pattern: "Septal mid-wall fibrosis in a non-ischaemic pattern, in keeping with dilated cardiomyopathy. With the normal CT coronary angiogram, an ischaemic aetiology is effectively excluded."
Abnormal pattern: "Chronic {territory} territory infarction with severely impaired left ventricular systolic function (LVEF {value}%) and a small apical aneurysm."
Abnormal pattern: "Acute myocarditis: myocardial oedema and non-ischaemic subepicardial enhancement of the {segment}, fulfilling the updated Lake Louise criteria. No evidence of infarction."
Abnormal pattern: "Asymmetric septal hypertrophic cardiomyopathy, maximal wall thickness {measurement} mm, without resting left ventricular outflow tract obstruction."
Abnormal pattern: "Non-viable {segment}. The {segment} ({range}% transmural extent) are unlikely to recover function."
Abnormal pattern: "Viable myocardium in the {segment} and throughout the {territory} and {territory} territories."
Abnormal pattern: "Low-normal left ventricular systolic function (LVEF {value}%) with regional {segment} hypokinesia."
Abnormal pattern: "Patchy mid-wall fibrosis (approximately {value}% of LV mass) with raised ECV."
Abnormal pattern: "Hyperdynamic left ventricular systolic function (LVEF {value}%)."
Recommendation phrasing: "Suggest discussion at the cardiomyopathy MDT."
Recommendation phrasing: "Suggest discussion at the heart team MDT."
Recommendation phrasing: "Suggest repeat cardiac MRI in {duration} to assess resolution of oedema and residual scar."
Recommendation phrasing: "Suggest referral to the inherited cardiac conditions service; first-degree relatives should be offered screening."

## Impression Construction
### Full impressions (verbatim)
Example 1 (normal): "Normal cardiac MRI. No evidence of cardiomyopathy."
Example 2 (DCM): "1. Dilated left ventricle with severely impaired systolic function (LVEF 29%) and mildly impaired right ventricular function.
2. Septal mid-wall fibrosis in a non-ischaemic pattern, in keeping with dilated cardiomyopathy. With the normal CT coronary angiogram, an ischaemic aetiology is effectively excluded.
3. Moderate functional mitral regurgitation.
4. Suggest discussion at the cardiomyopathy MDT."
Example 3 (viability): "1. Chronic LAD territory infarction with severely impaired left ventricular systolic function (LVEF 31%) and a small apical aneurysm.
2. Non-viable apex and apical segments. The mid anterior and mid anteroseptal segments (51–75% transmural extent) are unlikely to recover function.
3. Viable myocardium in the basal anterior segment and throughout the RCA and circumflex territories.
4. Suggest discussion at the heart team MDT."
Example 4 (myocarditis): "1. Acute myocarditis: myocardial oedema and non-ischaemic subepicardial enhancement of the basal to mid inferolateral wall, fulfilling the updated Lake Louise criteria. No evidence of infarction.
2. Low-normal left ventricular systolic function (LVEF 55%) with regional inferolateral hypokinesia.
3. Small pericardial effusion.
4. Suggest repeat cardiac MRI in 6 months to assess resolution of oedema and residual scar."
Example 5 (HCM): "1. Asymmetric septal hypertrophic cardiomyopathy, maximal wall thickness 19 mm, without resting left ventricular outflow tract obstruction.
2. Patchy mid-wall fibrosis (approximately 4% of LV mass) with raised ECV.
3. Hyperdynamic left ventricular systolic function (LVEF 72%).
4. Suggest referral to the inherited cardiac conditions service; first-degree relatives should be offered screening."

### Sentence construction
Each numbered item is one or two short sentences. The primary diagnosis leads with the anatomical structure and its key abnormality, followed by the functional consequence in parentheses (LVEF value). Secondary findings (fibrosis pattern, functional regurgitation, pericardial effusion) are compressed into single declarative sentences. Viability statements name segments explicitly with their transmural extent in parentheses. The recommendation is always the final item, a single imperative beginning "Suggest" + infinitive clause.

### Inclusion logic
Findings that alter management or define the diagnosis are promoted to the impression. Measurements (LVEF, wall thickness) are restated in the impression alongside the diagnosis. Incidental or minor findings (small pericardial effusion, mild RV impairment) are included if they add clinical context but are not the primary driver. The recommendation tailors to the clinical question: MDT for cardiomyopathy/viability, repeat imaging for myocarditis, genetics referral for HCM.

### Normal-study impression
Two unnumbered sentences: "Normal cardiac MRI. No evidence of cardiomyopathy." No recommendation is given.

## Measurement and Grading
Measurements are written inline as a comma-separated run at the end of the ventricular paragraph: "LVEDVi {value} ml/m², LVESVi {value} ml/m², LVEF {value}%, LV mass index {value} g/m²." Volumes use ml/m² (indexed), EF uses %, mass uses g/m². Wall thickness is given in mm with the segment named: "maximal end-diastolic wall thickness 19 mm in the basal anteroseptum". Transmural LGE extent uses bracketed ranges: ">75%", "51–75%", "1–25%". Fibrosis burden is given as a percentage of LV mass: "approximately 4% of LV mass". Regurgitant fraction is in parentheses after the grade: "Moderate functional mitral regurgitation (regurgitant fraction 28%)". Pericardial effusion size: "up to 6 mm adjacent to the lateral wall".

Functional grading language: "preserved" (normal), "low-normal" (mildly reduced), "mildly impaired", "severely impaired", "hyperdynamic". Wall motion grading: "no regional wall motion abnormality", "mild hypokinesia", "severely hypokinetic", "akinetic".

Viability thresholds (explicit): "<50% transmural extent" = "likely to be viable"; ">50% transmural extent" = "unlikely to recover function following revascularisation".

## Reference Values
- Native T1: 950–1050 ms at 1.5 T (stated in every tissue characterisation paragraph)
- T2 mapping: 42–52 ms
- Extracellular volume: <30%
- Transmural LGE viability cutoff: 50% (segments <50% viable, >50% non-viable)
- Transmural LGE tiers: >75% (transmural), 51–75% (subtransmural), 1–25% (minimal)

## Incidental Findings
Incidental findings (small pericardial effusion, small pleural effusions) are reported in the Pericardial and Extracardiac paragraph with a size and a haemodynamic qualifier: "Small pericardial effusion, up to 6 mm adjacent to the lateral wall, without haemodynamic compromise." They are promoted to the impression as a separate numbered item when clinically relevant (Example 4, item 3). Findings described as "no significant extracardiac findings" are below the reporting threshold and receive no further comment.

## Domain Rules
- The LV paragraph always ends with the measurement run; the RV paragraph always ends with its measurement run. Neither paragraph contains the other ventricle's data.
- When both atria are normal, they are reported together: "The atria are not dilated." When one is abnormal, it is named individually: "The left atrium is moderately dilated."
- The LGE section always closes with a thrombus statement. In viability studies the wording shifts: "No apical thrombus on early or late post-contrast imaging."
- When prior coronary imaging is available and normal, it is referenced in the impression to exclude ischaemia: "With the normal CT coronary angiogram, an ischaemic aetiology is effectively excluded."
- Missing quantitative values are flagged at the top of the Findings section before any paragraph: "Values not provided: LV mass index, RVEDVi, RVESVi, RVEF."
- In HCM, the LV paragraph adds an LVOT assessment after the measurements: "No systolic anterior motion of the mitral valve and no flow acceleration in the left ventricular outflow tract at rest."
- Tissue characterisation values are always paired with the local reference range in parentheses on the same line.

## Open Questions
- [NEEDS CLARIFICATION] Is the "Values not provided" line only written when the technologist's measurements are genuinely absent, or is it also used when the radiologist chooses not to report a value? Only one example (Ex 4) shows it.
- [NEEDS CLARIFICATION] In the viability protocol, is the LGE section always subdivided into per-territory transmural percentages, or is a simpler pattern description acceptable when the infarct is small?
- [NEEDS CLARIFICATION] Does the radiologist always include a haemodynamic qualifier ("without haemodynamic compromise") for pericardial effusions, or is it omitted when the effusion is very small? Only one example shows an effusion.
- [NEEDS CLARIFICATION] For the viability protocol, is the "No enhancement of the {segment}" negative (excluding other territories) always written, or only when the infarct is territorial and other territories are at risk?

## Case Deliberation
QUESTION "Does the imaging show evidence of hypertrophic cardiomyopathy or another cardiomyopathy that would alter the screening surveillance pathway?"
DIFFERENTIAL [HCM] TIER triage "Left ventricular wall hypertrophy, asymmetric or concentric, with or without mid-wall or patchy late gadolinium enhancement" VISIBLE yes
DIFFERENTIAL [DCM] TIER triage "Left ventricular dilatation with reduced systolic function and global hypokinesis" VISIBLE yes
DIFFERENTIAL [Infiltrative cardiomyopathy] TIER triage "Diffuse subendocardial late gadolinium enhancement with elevated native T1 mapping" VISIBLE yes
DIFFERENTIAL [ACM] TIER triage "Right ventricular dilatation with regional wall motion abnormality and right ventricular late gadolinium enhancement" VISIBLE yes
DIFFERENTIAL [Sarcomeric HCM] TIER aetiology "Asymmetric septal or apical hypertrophy with mid-wall or patchy late gadolinium enhancement and normal native T1" VISIBLE yes
DIFFERENTIAL [Infiltrative aetiology] TIER aetiology "Concentric hypertrophy with diffuse subendocardial late gadolinium enhancement and elevated native T1" VISIBLE yes
RECOMMEND REFERRAL "Referral to cardiology" WHEN [findings: left ventricular hypertrophy]
RECOMMEND REFERRAL "Urgent referral to cardiology" WHEN [findings: late gadolinium enhancement in the myocardium]
RECOMMEND REFERRAL "Referral to cardiology" WHEN [findings: left ventricular dilatation with reduced systolic function]
RECOMMEND REFERRAL "Referral to cardiology" WHEN [findings: right ventricular dilatation]
