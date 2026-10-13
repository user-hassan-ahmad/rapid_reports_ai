"""Cleanup v2.1 of resources/tnm_9th_clean.json (scratchpad copilot, 2026-10-12).

Every change is listed here and was hand-checked against the scan of v2.0. Text is only removed or moved where the
source text itself is present; the only added text is the universal UICC wording for TX / NX / N0 / M0 where a site's
table lost those rows, and two category labels the source names inline (T1mi, N1mi, N1c, Endometrium T3/T4).

  cd backend && python3 scripts/tnm/clean_tnm_9th.py            # rewrites the file from v2.0 (git), prints the diff
  cd backend && python3 scripts/tnm/clean_tnm_9th.py --check    # exit 1 if the file is not clean
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "src" / "rapid_reports_ai" / "resources" / "tnm_9th_clean.json"

TX = "Primary tumour cannot be assessed"
NX = "Regional lymph nodes cannot be assessed"
N0 = "No regional lymph node metastasis"
M0 = "No distant metastasis"

# Words broken across a line in the source PDF: "dimen- sion" → "dimension". Compounds keep their hyphen.
DEHYPHEN = {
    "car- tilage": "cartilage", "character- istics": "characteristics", "com- mon": "common",
    "contralat- eral": "contralateral", "descend- ing": "descending", "dimen- sion": "dimension",
    "dis- ease": "disease", "extra- adrenal": "extra-adrenal", "extra- osseous": "extra-osseous",
    "gallblad- der": "gallbladder", "high- grade": "high-grade", "histologi- cally": "histologically",
    "hydro- nephrosis": "hydronephrosis", "imaging- detected": "imaging-detected", "ipsi- lateral": "ipsilateral",
    "lim- ited": "limited", "lym- phatic": "lymphatic", "mam- mary": "mammary", "mediasti- nal": "mediastinal",
    "menin- geal": "meningeal", "mesen- tery": "mesentery", "metas- tasis": "metastasis", "mus- cles": "muscles",
    "muscu- laris": "muscularis", "non- peritonealised": "non-peritonealised", "paraesoph- ageal": "paraesophageal",
    "perito- neal": "peritoneal", "preverte- bral": "prevertebral", "rec- tum": "rectum",
    "retroperito- neum": "retroperitoneum", "sterno- thyroid": "sternothyroid", "supe- rior": "superior",
    "vis- ceral": "visceral", "with- out": "without", "orFallopian": "or Fallopian",
}

# Footnote letters fused onto the last word: (site, axis, key) -> (old, new).
FOOTNOTES = [
    ("Lung", "T", "Tis", "situa", "situ"),
    ("Lung", "T", "T1a", "dimensionb", "dimension"),
    ("Lung", "T", "T1b", "dimensionb", "dimension"),
    ("Lung", "T", "T1c", "dimensionb", "dimension"),
    ("Lung", "T", "T3", "veind", "vein"),
    ("Lung", "M", "M1a", "effusione", "effusion"),
    ("Lung", "M", "M1b", "systemf", "system"),
    ("Breast Tumours", "T", "T4d", "carcinomad", "carcinoma"),
    ("Appendix", "T", "T1", "submucosab", "submucosa"),
    ("Appendix", "T", "T2", "propriab", "propria"),
    ("Appendix", "T", "T4", "structuresc", "structures"),
    ("Colon and Rectum", "T", "Tis", "propriaa", "propria"),
    ("Melanoma of Conjunctiva", "T", "T1a", "quadrantb", "quadrant"),
    ("Adrenal Medulla and Extra-Adrenal Paraganglia Tumours", "T", "T3", "organsa", "organs"),
]

# Whole-value replacements: neighbouring categories, FIGO stage labels or page headers bled into the text.
REPLACE = {
    ("Lung", "T", "T1"): "Tumour 3 cm or less in greatest dimension, surrounded by lung or visceral pleura, or tumour "
                         "in a lobar or more peripheral bronchus",
    ("Breast Tumours", "T", "T1"): "Tumour 2 cm or less in greatest dimension",
    ("Gestational Trophoblastic Neoplasms", "T", "T2b"): "Tumour extends to other genital structures: vagina, ovary, "
                                                         "broad ligament or Fallopian tube by metastasis or direct extension",
    ("Ovarian, Fallopian Tube and Primary Peritoneal Carcinoma", "T", "T1c"):
        "Tumour limited to one or both ovaries or Fallopian tubes with any of the following:",
    ("Ovarian, Fallopian Tube and Primary Peritoneal Carcinoma", "T", "T3"):
        "Tumour involves one or both ovaries or Fallopian tubes or primary peritoneal carcinoma with cytologically or "
        "histologically confirmed spread to the peritoneum outside the pelvis and/or metastasis to the retroperitoneal "
        "lymph nodes",
    ("Ovarian, Fallopian Tube and Primary Peritoneal Carcinoma", "T", "T3c"):
        "Peritoneal metastasis beyond pelvic brim more than 2 cm in greatest dimension and/or retroperitoneal lymph node "
        "metastasis (includes extension of tumour to capsule of liver and spleen without parenchymal involvement of "
        "either organ)",
    ("Retinoblastoma", "M", "M1b"): "Metastasis to the CNS including brain",
    ("Uterine Sarcomas", "T", "T2b"): "Tumour involves other pelvic tissues",
    ("Uterine Sarcomas", "T", "T3b"): "More than one site",
    ("Uterine Sarcomas", "T", "T4"): "Tumour invades bladder or rectum",
    ("Vagina", "T", "T1"): "Tumour confined to vagina",
    ("Vagina", "T", "T4"): "Tumour invades mucosa of bladder or rectum or extends beyond the true pelvis",
    ("Cervix Uteri", "T", "T1a"): "Invasive carcinoma diagnosed only by microscopy. Stromal invasion with a maximal "
                                  "depth of 5.0 mm",
    ("Cervix Uteri", "T", "T4"): "Tumour invades mucosa of the bladder or rectum or extends beyond true pelvis",
    ("Uterus - Endometrium", "T", "T1"): "Tumour confined to the corpus uteri",
    ("Uterus - Endometrium", "T", "T2"): "Tumour invades cervical stroma but does not extend beyond the uterus",
    ("Uterus - Endometrium", "T", "T3b"): "Vaginal or parametrial involvement (direct extension or metastasis)",
    ("Vulva", "T", "T4"): "Tumour fixed to pelvic bone",
    ("Vulva", "N", "N0"): "No regional lymph node metastasis. N0(i+): isolated tumour cells in regional lymph node(s) "
                          "≤0.2 mm, or single cells or clusters of cells ≤200 cells in a single lymph node cross-section",
    ("Vulva", "N", "N1"): "Tumour involvement of non-fixed, non-ulcerated regional lymph nodes",
    ("Vulva", "N", "N1b"): "Tumour involvement (>5 mm) of regional lymph nodes",
    ("Vulva", "N", "N2"): "Tumour involvement of fixed or ulcerated regional lymph nodes",
    ("Sarcoma of Orbit", "T", "T4"): "Tumour invades globe or periorbital structure, such as eyelids, temporal fossa, "
                                     "nasal cavity and paranasal sinuses, and/or central nervous system",
    ("Melanoma of Uvea", "T", "T0"): "No evidence of primary tumour",
    ("Retinoblastoma", "T", "T3d"): "Hyphema and/or massive vitreous haemorrhage",
}

# Categories the source names inline (moved out of the text above) or universal X/0 rows a table lost:
# (site, axis, key, text, insert_after or None for first).
INSERT = [
    ("Lung", "T", "T1mi", "Minimally invasive adenocarcinoma", "T1"),
    ("Breast Tumours", "T", "T1mi", "Microinvasion 0.1 cm or less in greatest dimension", "T1"),
    ("Uterus - Endometrium", "T", "T3", "Local and/or regional spread as specified in T3a and T3b", "T2"),
    ("Uterus - Endometrium", "T", "T4", "Tumour invades bladder/bowel mucosa", "T3b"),
    ("Vulva", "N", "N1mi", "Tumour involvement (>0.2 mm but ≤2.0 mm in diameter) of regional lymph nodes", "N1"),
    ("Retinoblastoma", "T", "T3e", "Aseptic orbital cellulitis", "T3d"),
    ("Vulva", "N", "N1c", "Tumour involvement of regional lymph nodes with extranodal extension (ENE)", "N1b"),
    ("Gestational Trophoblastic Neoplasms", "M", "M0", M0, None),
    ("Gestational Trophoblastic Neoplasms", "M", "M1a", "Metastasis to lung(s)", "M0"),
    ("Gestational Trophoblastic Neoplasms", "M", "M1b", "Other distant metastasis", "M1a"),
    ("Uterine Sarcomas", "T", "TX", TX, None),
    ("Nasal Cavity and Paranasal Sinuses", "N", "NX", NX, None),
    ("Nasal Cavity and Paranasal Sinuses", "N", "N0", N0, "NX"),
    ("Unknown Primary - Cervical Nodes", "N", "NX", NX, None),
    ("Unknown Primary - Cervical Nodes", "N", "N0", N0, "NX"),
]

NOTES = [
    "v2.1 (2026-10-12): stripped fused footnote letters and asterisk footnote markers",
    "v2.1: re-joined words broken across lines in the source PDF",
    "v2.1: removed FIGO stage labels, 'N/A' cells and page headers that bled into category text",
    "v2.1: moved inline categories out of neighbouring text (Lung/Breast T1mi, Vulva N1mi/N1c, Endometrium T3/T4, "
    "GTN M1a/M1b, Retinoblastoma T3e); dropped Retinoblastoma pTNM block from M1b",
    "v2.1: added universal TX/NX/N0/M0 rows where a table lost them (Uterine Sarcomas TX, Nasal Cavity NX/N0, "
    "Unknown Primary NX/N0, GTN M0)",
    "v2.1: the record labelled 'Bone & Soft Tissues' was GIST (its rules name GIST): moved to the GIST key; its stage "
    "grouping needs the mitotic rate and site, which the table lost, so it is dropped",
]


def _insert(cats: dict, key: str, text: str, after: str | None) -> dict:
    if key in cats:
        return cats
    items = list(cats.items())
    idx = 0 if after is None else next((i + 1 for i, (k, _) in enumerate(items) if k == after), len(items))
    items.insert(idx, (key, text))
    return dict(items)


def clean_text(s: str) -> str:
    for a, b in DEHYPHEN.items():
        s = s.replace(a, b)
    s = re.sub(r"\*+", "", s)
    s = re.sub(r"(^|\s)N/A\s+", r"\1", s)
    return " ".join(s.split())


def clean(data: dict) -> dict:
    t = data["tumours"]
    if "Bone & Soft Tissues" in t:
        gist = t["Gastrointestinal Stromal Tumour (GIST)"]
        bst = t.pop("Bone & Soft Tissues")
        gist["tnm"] = bst["tnm"]
        gist["stage_grouping"] = []
    for site, rec in t.items():
        for ax, cats in rec["tnm"].items():
            if isinstance(cats, dict):
                rec["tnm"][ax] = {k: clean_text(v) if isinstance(v, str) else v for k, v in cats.items()}
        rec["rules"] = clean_text(rec.get("rules") or "")
    for site, ax, key, old, new in FOOTNOTES:
        v = t[site]["tnm"][ax][key]
        assert old in v, (site, ax, key, old)
        t[site]["tnm"][ax][key] = v.replace(old, new)
    for (site, ax, key), new in REPLACE.items():
        assert key in t[site]["tnm"][ax], (site, ax, key)
        t[site]["tnm"][ax][key] = new
    for site, ax, key, text, after in INSERT:
        t[site]["tnm"][ax] = _insert(t[site]["tnm"][ax], key, text, after)
    data["cleanup_version"] = "2.1"
    data["cleanup_notes"] = [n for n in data.get("cleanup_notes", []) if not n.startswith("v2.1")] + NOTES
    data["tumour_count"] = len(t)
    return data


def problems(data: dict) -> list[str]:
    """What the scan flagged, re-checked on the cleaned data: fused footnotes on the listed words, bleed markers."""
    out = []
    for site, rec in data["tumours"].items():
        for ax, cats in rec["tnm"].items():
            if not isinstance(cats, dict):
                continue
            for k, v in cats.items():
                if re.search(r"\*|\(Continued\)|FIGO|\bN/A\b|\b\w+- \w", v):
                    out.append(f"{site} {ax} {k}: {v[:80]}")
                if re.search(r"\bc[TNM]\d", v):
                    out.append(f"{site} {ax} {k} (embedded category): {v[:80]}")
    return out


def main() -> int:
    data = json.loads(PATH.read_text())
    if "--check" in sys.argv:
        p = problems(data)
        print("\n".join(p) or "clean")
        return 1 if p else 0
    if data.get("cleanup_version") != "2.0":   # always rebuild from the v2.0 file in git, so the run is repeatable
        import subprocess
        rel = PATH.relative_to(PATH.parents[3])
        src = subprocess.run(["git", "log", "--format=%H", "--", str(rel)], capture_output=True, text=True,
                             cwd=PATH.parents[3]).stdout.split()
        data = next(d for h in src if (d := json.loads(subprocess.run(["git", "show", f"{h}:./{rel}"], capture_output=True,
                    text=True, cwd=PATH.parents[3]).stdout)).get("cleanup_version") == "2.0")
    before = json.loads(json.dumps(data))
    data = clean(data)
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    changed = 0
    for site, rec in data["tumours"].items():
        old = (before["tumours"].get(site) or {}).get("tnm", {})
        for ax, cats in rec["tnm"].items():
            if not isinstance(cats, dict):
                continue
            for k, v in cats.items():
                ov = (old.get(ax) or {}).get(k) if isinstance(old.get(ax), dict) else None
                if ov != v:
                    changed += 1
                    print(f"[{site} | {ax} | {k}]\n  - {ov}\n  + {v}")
    print(f"\n{changed} category texts changed; remaining problems: {len(problems(data))}")
    for p in problems(data):
        print("  !", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
