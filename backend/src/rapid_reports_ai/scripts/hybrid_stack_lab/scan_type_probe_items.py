import json
dev = json.load(open("src/rapid_reports_ai/scripts/hybrid_stack_lab/cases.json"))["cases"]
ho = json.load(open("src/rapid_reports_ai/scripts/hybrid_stack_lab/heldout_cases.json"))["cases"]
items = [(c["scan_type"], c["clinical_history"], c["family"]) for c in dev] + \
        [(c["scan_type"], c["clinical_history"], "none" if c.get("uncovered") else c["family"]) for c in ho] + [
    ("MRI left ankle", "Inversion injury.", "none"), ("MRI right wrist", "Fall, scaphoid tenderness.", "none"),
    ("MRI elbow", "Lateral elbow pain.", "none"), ("MRI breast bilateral", "BRCA carrier screening.", "none"),
    ("MR enterography", "Crohn's disease.", "abdomen_pelvis"), ("CT orbits", "Proptosis.", "none"),
    ("MRI internal auditory meati", "Unilateral hearing loss.", "none"), ("CT temporal bones", "Cholesteatoma.", "none"),
    ("CT sinuses", "Chronic rhinosinusitis.", "none"), ("CT coronary angiogram", "Atypical chest pain.", "none"),
    ("CT abdomen", "Epigastric pain.", "abdomen_pelvis"), ("MRI head", "Headache.", "head"),
    ("CT thorax with contrast", "Haemoptysis.", "chest"), ("MRI L-spine", "Back pain.", "lumbar_spine"),
    ("CT head and neck angiogram", "Stroke.", "none"), ("MRI pelvis for endometriosis", "Pelvic pain.", "pelvis_mr")]
