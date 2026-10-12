from rapid_reports_ai.hybrid_stack.copilot.types import Publication as P
SEEDS = [
 ("Fleischner", "2017", P(title="Guidelines for Management of Incidental Pulmonary Nodules Detected on CT Images: From the Fleischner Society 2017", body="Fleischner Society", year="2017"),
  ["Solid nodule, single", "Solid nodules, multiple", "Subsolid nodule, pure ground-glass", "Subsolid nodule, part-solid", "Subsolid nodules, multiple"]),
 ("Bosniak", "2019", P(title="Bosniak Classification of Cystic Renal Masses, Version 2019", body="Society of Abdominal Radiology", year="2019"),
  ["Class I and II", "Class IIF", "Class III", "Class IV"]),
 ("ESE adrenal incidentaloma", "2023", P(title="European Society of Endocrinology clinical practice guidelines on the management of adrenal incidentalomas", body="European Society of Endocrinology", year="2023"),
  ["Unenhanced CT attenuation 10 HU or less", "Attenuation 11 to 20 HU", "Indeterminate lesions above 20 HU or inhomogeneous"]),
 ("BTA U classification", "2014", P(title="Guidelines for the management of thyroid cancer, third edition", body="British Thyroid Association", year="2014"),
  ["U1 and U2 benign", "U3 indeterminate", "U4 and U5 suspicious or malignant"]),
 ("O-RADS US", "2022", P(title="O-RADS US Risk Stratification and Management System", body="American College of Radiology", year="2022"),
  ["O-RADS 2 almost certainly benign", "O-RADS 3 low risk", "O-RADS 4 intermediate risk", "O-RADS 5 high risk"]),
 ("LI-RADS CT/MRI", "2018", P(title="LI-RADS CT/MRI Diagnostic Algorithm", body="American College of Radiology", year="2018"),
  ["LR-3 intermediate", "LR-4 probably HCC", "LR-5 definitely HCC", "LR-M"]),
 ("Kellgren-Lawrence", "", P(title="Radiological assessment of osteo-arthrosis", body="Kellgren and Lawrence", year="1957"),
  ["Grades 0 to 4"]),
]
