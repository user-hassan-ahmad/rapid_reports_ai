"""Rebuild UICC TNM 9 clinical stage tables from the raw extraction (scratchpad copilot, 2026-10-12).

The v2.0 parse kept one row per stage and dropped continuation rows (Lung T2b N1 M0 had no stage). This re-parses
each site's clinical stage table from the raw text of the master extraction (not in the repo) and writes
`stage_tables` into resources/tnm_9th_clean.json:

    "stage_tables": [{"variant": "" | "Squamous cell carcinoma" | ..., "verified": true,
                      "rows": [{"stage": "Stage IIB", "T": ["T1"], "N": ["N2a"], "M": ["M0"]}, ...]}]

Only sites listed in SITES are rebuilt; each table was hand-checked against the source text and the exhaustive
T x N x M check below before being marked verified. Sites whose stage needs more than T, N and M (grade, PSA, age,
markers, mitotic rate, subsite) are not rebuilt: their cards propose T, N and M only.

  cd backend && python3 scripts/tnm/rebuild_stage_tables.py ~/Downloads/Medical/Papers/tnm_9th_master.json
  cd backend && python3 scripts/tnm/rebuild_stage_tables.py RAW --dry    # print tables and checks, write nothing
"""
from __future__ import annotations

import json
import re
import sys
from itertools import product
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "src" / "rapid_reports_ai" / "resources" / "tnm_9th_clean.json"

# site -> [(variant, anchor regex: the line that heads the clinical table)]. The table runs from the anchor until a
# stop line; page headers between rows are skipped.
SITES: dict[str, list[tuple[str, str]]] = {
    "Oral Cavity and Mucosal Lip": [("", r"^\s*Stage\s*$")],
    "Larynx": [("", r"^\s*Stage\s*$")],
    "Nasal Cavity and Paranasal Sinuses": [("", r"^\s*Stage\s*$")],
    "Malignant Melanoma of Upper Aerodigestive Tract": [("", r"^\s*Stage\s*$")],
    "Salivary Glands": [("", r"^\s*Stage\s*$")],
    "Oesophagus": [("Squamous cell carcinoma", r"^\s*Squamous Cell Carcinoma\s*$"),
                   ("Adenocarcinoma", r"^\s*Adenocarcinoma\s*$")],
    "Stomach": [("", r"^\s*Clinical Stage\*?\s*$")],
    "Small Intestine": [("", r"^\s*Stage\s*$")],
    "Colon and Rectum": [("", r"^\s*Stage\s*$")],
    "Anal Canal and Perianal Skin": [("", r"^\s*Stage\s*$")],
    "Liver": [("", r"^\s*Stage\s*-\s*Liver")],
    "Intrahepatic Bile Ducts": [("", r"^\s*Stage\s*-")],
    "Gallbladder": [("", r"^\s*Stage\s*-\s*Gallbladder")],
    "Perihilar Bile Ducts": [("", r"^\s*Stage\s*-\s*Perihilar")],
    "Distal Extrahepatic Bile Duct": [("", r"^\s*Stage\s*-")],
    "Ampulla of Vater": [("", r"^\s*Stage\s*-\s*Ampulla")],
    "Pancreas": [("", r"^\s*Stage\s*-\s*Pancreas")],
    "Lung": [("", r"^\s*Stage\s*$")],
    "Pleural Mesothelioma": [("", r"^\s*Stage\s*-\s*Pleural")],
    "Thymus Tumours": [("", r"^\s*Stage\s*-\s*Thymic")],
    "Carcinoma of Skin (excluding eyelid, head and neck, perianal, vulva and penis)": [("", r"^\s*Stage\s*$")],
    "Carcinoma of Skin of the Head and Neck Region": [("", r"^\s*Stage\s*$")],
    "Carcinoma of Skin of the Eyelid": [("", r"see page 8\.\s*$")],
    "Merkel Cell Carcinoma of Skin": [("", r"^\s*Clinical Stage\s*$")],
    "Vulva": [("", r"^\s*Stage\s*$")],
    "Vagina": [("", r"^\s*Stage\s*$")],
    "Uterus - Endometrium": [("", r"^\s*Stage\s*$")],
    "Ovarian, Fallopian Tube and Primary Peritoneal Carcinoma": [("", r"^\s*Stage\s*$")],
    "Penis": [("", r"^\s*Stage\s*$")],
    "Kidney": [("", r"^\s*Stage\s*$")],
    "Renal Pelvis and Ureter": [("", r"^\s*Stage\s*$")],
    "Urinary Bladder": [("", r"^\s*Stage\s*$")],
    "Urethra": [("", r"^\s*Stage\s*$")],
    "Adrenal Cortex": [("", r"^\s*Stage\s*$")],
    "Adrenal Medulla and Extra-Adrenal Paraganglia Tumours": [("", r"^\s*Stage\s*$")],
    "Retinoblastoma": [("", r"^\s*Clinical stage\s*$")],
}
# Not rebuilt although a table exists, because the site's own category table is incomplete or disagrees with it:
# Cervix Uteri (no IB3 row, no N2 rows), Uterine Sarcomas (no T1c; leiomyosarcoma and adenosarcoma T differ),
# Melanoma of Uvea (T1d, T3a-d and T4 subcategories missing from the T table). Their cards propose T, N and M only.
STOP = re.compile(r"Pathological|Prognostic|Summary|Source:|^\s*Notes?\b|References|^\s*\*\s*\w|Clinical Stage|"
                  r"Adenocarcinoma\s*$|Stage\s*-\s*\w|Prognostic Factors")
MAX_GAP = 8   # non-row lines (page headers, blanks) tolerated inside one table


def _split(line: str) -> list[str]:
    return [x for x in re.split(r"\s{2,}", line.strip()) if x]


RUNNING_HEADERS = {"Lung, Pleural, Thymic", "Head & Neck", "Digestive System", "Gynaecological", "Urological"}


def _row(line: str):
    f = _split(line)
    if f and f[-1] in RUNNING_HEADERS:   # a page's running header printed on the same line as a row
        f = f[:-1]
    if [x.strip() for x in f] == ["T", "N", "M"]:   # a column header row
        return None
    label = None
    if f and (f[0].startswith("Stage") or f[0].startswith("Occult")):
        label, f = f[0], f[1:]
    if len(f) == 3 and re.match(r"^(Any\s*T|c?T)", f[0]) and re.match(r"^(Any\s*N|c?N)", f[1]) \
            and re.match(r"^(Any\s*M|c?M)", f[2]):
        return label, f
    return None


def _expand(cell: str, axis: str, order: list[str]) -> list[str]:
    """'T1, T2' / 'T3,4' / 'N2a,b' / 'T1/2' / 'TX-T3' / 'T1b-d' / 'Any N' -> category list (c/p prefixes, stars off).
    A parent inside a range is dropped unless all its children are in it (T1-T4a keeps T4a, not T4)."""
    cell = cell.replace("*", "").strip()
    if cell.lower().startswith("any"):
        return ["Any"]
    out: list[str] = []
    prev = ""
    for part in re.split(r"\s*[,/]\s*", cell):
        p = re.sub(r"^[cp](?=[TNM])", "", part.strip())
        if not p:
            continue
        if re.fullmatch(r"[a-e]", p) and prev:                     # 'N2a,b' -> N2b
            p = re.sub(r"[a-e]$", "", prev) + p
        elif re.fullmatch(r"\d", p) and prev:                     # 'T3,4' / 'N1,2'
            p = axis + p
        m = re.fullmatch(rf"({axis}\w*?)-({axis}?\w+)", p)
        if m:
            a, b = m.group(1), m.group(2)
            if not b.startswith(axis):                            # 'T1b-d'
                b = re.sub(r"[a-e]$", "", a) + b
            if a in order and b in order:
                span = order[order.index(a): order.index(b) + 1]
                keep = [c for c in span if not any(o.startswith(c) and o != c and o not in span for o in order)]
                out += keep
                prev = b
                continue
        out.append(p)
        prev = p
    return out


def parse(raw: str, anchor: str, order: dict[str, list[str]]) -> list[dict]:
    lines = raw.split("\n")
    start = next((i for i, l in enumerate(lines) if re.search(anchor, l)), None)
    if start is None:
        raise ValueError(f"anchor {anchor!r} not found")
    rows, stage, gap = [], None, 0
    for l in lines[start + 1:]:
        r = _row(l)
        if r is None:
            if rows and (STOP.search(l) or gap >= MAX_GAP):
                break
            gap += 1 if rows else 0
            continue
        gap = 0
        label, (t, n, m) = r
        if label:
            stage = label.replace("*", "").strip()
        if stage is None:   # a continuation row before any stage label: the table's top is missing
            raise ValueError(f"continuation row before a stage label: {l.strip()!r}")
        rows.append({"stage": stage, "T": _expand(t, "T", order["T"]), "N": _expand(n, "N", order["N"]),
                     "M": _expand(m, "M", order["M"])})
    return rows


def matches(cat: str, cells: list[str]) -> int:
    """2: exact cell; 1: the cell is its parent (T2b under 'T2') or 'Any'; 0: no match. An X category matches only a
    cell that lists it (Lung 'Occult carcinoma TX N0 M0') or 'Any'."""
    if cat in cells:
        return 2
    if "Any" in cells:
        return 1
    if cat.endswith("X"):
        return 0
    return 1 if any(cat.startswith(c) for c in cells) else 0


def _direct(rows: list[dict], t: str, n: str, m: str) -> str | None:
    hits = []
    for g in rows:
        s = [matches(c, g[a]) for c, a in ((t, "T"), (n, "N"), (m, "M"))]
        if all(s):
            hits.append((sum(s), g["stage"]))
    if not hits:
        return None
    best = max(h for h, _ in hits)
    stages = {st for h, st in hits if h == best}
    # A summary stage listed beside its substages (Stage II with IIA-IIC): the substage wins.
    stages = {st for st in stages if not any(o != st and o.startswith(st) for o in stages)}
    return stages.pop() if len(stages) == 1 else None


def _leaves(cat: str, cats: list[str]) -> list[str]:
    """The most specific subcategories of `cat` (M1 -> M1a, M1b, M1c1, M1c2), or [] when it has none."""
    kids = [k for k in cats if k != cat and k.startswith(cat) and not k.endswith("X")]
    return [k for k in kids if not any(o != k and o.startswith(k) for o in kids)]


def lookup(rows: list[dict], t: str, n: str, m: str, cats: dict[str, list[str]] | None = None) -> str | None:
    """A parent category no row lists exactly (Lung M1 over M1a-M1c2) is resolved through its subcategories: one
    stage when they all agree, else None. A row that lists the parent itself (Colon 'Stage IV ... M1') wins.
    Keep identical to hybrid_stack/copilot/tnm.py."""
    cats = cats or {}
    q = {"T": t, "N": n, "M": m}
    split = {a: _leaves(c, cats.get(a, [])) for a, c in q.items()}
    split = {a: kids for a, kids in split.items() if kids and not any(q[a] in g[a] for g in rows)}
    if not split:
        return _direct(rows, t, n, m)
    got = {_direct(rows, *combo) for combo in product(*(split.get(a) or [q[a]] for a in "TNM"))}
    return got.pop() if len(got) == 1 and None not in got else None


def checks(site: str, rows: list[dict], cats: dict[str, list[str]]) -> list[str]:
    out = []
    for g in rows:
        for a in "TNM":
            for c in g[a]:
                if c != "Any" and not any(k == c or k.startswith(c) for k in cats[a]):
                    out.append(f"unknown {a} token {c!r} in {g['stage']}")
    # T0 / Tis / Ta with nodes or distant spread are not staged in the source tables: not counted as gaps.
    leaves = {a: [c for c in cats[a] if not c.endswith("X") and c not in ("T0", "Tis", "Ta")
                  and not any(o != c and o.startswith(c) for o in cats[a])] for a in "TNM"}
    none = [f"{t} {n} {m}" for t, n, m in product(leaves["T"], leaves["N"], leaves["M"]) if lookup(rows, t, n, m, cats) is None]
    if none:
        out.append(f"{len(none)} leaf combos with no stage, e.g. {none[:6]}")
    return out


def main() -> int:
    raw_path, dry = Path(sys.argv[1]).expanduser(), "--dry" in sys.argv
    raw = json.loads(raw_path.read_text())["tumours"]
    data = json.loads(PATH.read_text())
    for site, variants in SITES.items():
        rec = data["tumours"][site]
        order = {a: list((rec["tnm"].get(a) or {}).keys()) for a in "TNM"}
        tables = []
        for variant, anchor in variants:
            try:
                rows = parse(raw[site]["raw_text"], anchor, order)
            except ValueError as e:
                print(f"\n## {site} — {variant}: {e}")
                continue
            tables.append({"variant": variant, "verified": True, "rows": rows})
            print(f"\n## {site}{' — ' + variant if variant else ''} ({len(rows)} rows)")
            for g in rows:
                print(f"   {g['stage']:14} T {', '.join(g['T']):24} N {', '.join(g['N']):18} M {', '.join(g['M'])}")
            for c in checks(site, rows, order):
                print(f"   ! {c}")
        rec["stage_tables"] = tables
    if not dry:
        data["cleanup_version"] = "2.2"
        note = ("v2.2 (2026-10-12): clinical stage tables rebuilt from the raw extraction with continuation rows "
                "(stage_tables, hand-checked); stage_grouping kept for compatibility")
        data["cleanup_notes"] = [n for n in data["cleanup_notes"] if not n.startswith("v2.2")] + [note]
        PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
