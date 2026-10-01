"""Plan G6 (lab): convert stored template skill sheets into the lean grammar sheet.

Lab only, no production writes. The production template creator does not keep the example reports, so the
conversion works from the stored sheet (the authority) plus a few real reports made with that template
(voice evidence). One conversion call (TEMPLATE_SHEET_CONVERT_PROMPT, the lean analyser's model and
settings), the grammar parser in template mode, one lint-repair call when the parse has errors, then a
code faithfulness check: old headings accounted for, old quoted negatives / fixed / normal text kept
verbatim, every quoted text of the new sheet grounded in the old sheet or the reports.

The pulled data is production data: it lives in a scratch directory, never in the repo.

Usage (from backend/):
  python -m rapid_reports_ai.scripts.template_sheet_convert pull <data.json> [--top 5]
  python -m rapid_reports_ai.scripts.template_sheet_convert run <data.json> <out_dir> [--only slug1,slug2]
  python -m rapid_reports_ai.scripts.template_sheet_convert check <data.json> <out_dir>
Env: METABASE_URL / METABASE_API_KEY (pull), model keys (run); read from $LAB_ENV_FILE or backend/.env.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv(os.environ.get("LAB_ENV_FILE") or Path(__file__).resolve().parents[3] / ".env")
os.environ.setdefault("DATABASE_URL", "sqlite://")  # the lab never touches an app database (imports build an engine)

from rapid_reports_ai import template_sheet_lab_prompts as P  # noqa: E402

MAX_EVIDENCE, HELD_OUT, MIN_FINDINGS_CHARS = 5, 2, 100

# A model call: (system prompt, user prompt, settings) -> raw text. Injected in tests.
Call = Callable[[str, str, Dict], Awaitable[str]]


# ---------------------------------------------------------------------------------------------- data

def _metabase(sql: str) -> List[Dict]:
    import httpx

    r = httpx.post(
        os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
        headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8"},
        json={"database": 2, "type": "native", "native": {"query": sql}},
        timeout=120,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"])
    cols = [c["name"] for c in d["data"]["cols"]]
    return [dict(zip(cols, row)) for row in d["data"]["rows"]]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


def distinct_reports(rows: List[Dict]) -> List[Dict]:
    """One report per dictation (the newest regeneration), newest first; the radiologist's latest edited
    version is the report text when there is one."""
    seen: Dict[str, Dict] = {}
    for r in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        f = (r.get("findings") or "").strip()
        key = hashlib.md5(f.encode()).hexdigest()
        if f and key not in seen:
            seen[key] = r
    out = list(seen.values())
    for r in out:
        r["final_content"] = r.get("latest_version_content") or r["report_content"]
        r["content_source"] = (f"version {r['latest_version']}" if r.get("latest_version_content")
                               else "report_content")
    return out


def split_evidence(reports: List[Dict]) -> Tuple[List[Dict], List[Dict], bool]:
    """(evidence, held_out, leak). The HELD_OUT newest dictations with real findings are held out for the
    smoke test; up to MAX_EVIDENCE of the rest are voice evidence. With fewer than two left, the evidence is
    every report (held-out ones included) and leak is True."""
    real = [r for r in reports if len((r.get("findings") or "").strip()) >= MIN_FINDINGS_CHARS]
    held = real[:HELD_OUT]
    held_ids = {r["report_id"] for r in held}
    rest = [r for r in reports if r["report_id"] not in held_ids]
    if len(rest) >= 2:
        return rest[:MAX_EVIDENCE], held, False
    return reports[:MAX_EVIDENCE], held, True


def pull(out: Path, top: int = 5) -> Dict:
    """The `top` skill_sheet_guided templates by report count: config, report count, distinct dictations."""
    tops = _metabase(
        f"""select t.id, t.name, count(r.id) n from templates t left join reports r on r.template_id = t.id
            where t.template_config::jsonb->>'generation_mode' = 'skill_sheet_guided'
            group by t.id, t.name order by n desc limit {int(top)}""")
    data: Dict = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "templates": []}
    for t in tops:
        cfg = _metabase(f"select template_config from templates where id = '{t['id']}'")[0]["template_config"]
        cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
        rows = _metabase(
            f"""select r.id report_id, r.created_at, r.report_content,
                       v.report_content latest_version_content, v.version_number latest_version,
                       r.input_data::jsonb->'variables'->>'FINDINGS' findings,
                       r.input_data::jsonb->'variables'->>'CLINICAL_HISTORY' clinical_history
                from reports r
                left join lateral (select rv.report_content, rv.version_number from report_versions rv
                                   where rv.report_id = r.id order by rv.version_number desc limit 1) v on true
                where r.template_id = '{t['id']}' and r.report_content is not null""")
        reports = distinct_reports(rows)
        data["templates"].append({"slug": slug(t["name"]), "name": t["name"], "template_id": t["id"],
                                  "reports_total": t["n"], "distinct": len(reports),
                                  "skill_sheet": cfg.get("skill_sheet") or "", "scan_type": cfg.get("scan_type") or "",
                                  "coverage_sections": cfg.get("coverage_sections") or [],
                                  "reports": reports[:MAX_EVIDENCE + HELD_OUT]})
        print(f"{t['name'][:45]:45} reports {t['n']:3}  distinct {len(reports):3}", file=sys.stderr)
    out.write_text(json.dumps(data, indent=1, default=str))
    return data


# ------------------------------------------------------------------------------------------- parse

def parse(sheet: str) -> Tuple[Dict, List[Dict], List[Dict]]:
    """(structure dict, lint errors, lint warnings) in lean template mode. A sheet that lints clean but is
    not usable gets one synthetic error so the repair call sees it."""
    from rapid_reports_ai.template_sheet_grammar import parse_sheet

    res = parse_sheet(sheet, mode="template")
    errs = [dataclasses.asdict(e) for e in res.errors]
    warns = [dataclasses.asdict(w) for w in res.warnings]
    if not errs and not res.structure.usable:
        errs.append({"line": 0, "text": "", "reason": "structure not usable",
                     "detail": "the Report Structure block needs a findings-role and an impression-role SECTION"})
    return res.structure.model_dump(), errs, warns


# ------------------------------------------------------------------------------------------- calls

async def model_call(system: str, user: str, settings: Dict) -> str:
    """The lean analyser's model (SKILL_SHEET_ANALYZER) with the given settings."""
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    result = await _run_agent_with_model(
        model_name=MODEL_CONFIG["SKILL_SHEET_ANALYZER"], output_type=str, system_prompt=system,
        user_prompt=user, api_key="", use_thinking=True, model_settings=settings)
    return result.output if hasattr(result, "output") else str(result)


def evidence_docs(reports: List[Dict]) -> List[Dict[str, str]]:
    return [{"label": f"Report {i}", "content": r.get("final_content") or r.get("report_content") or ""}
            for i, r in enumerate(reports, 1)]


async def convert(old_sheet: str, scan_type: str, reports: List[Dict], coverage: Optional[List[str]] = None,
                  call: Call = model_call) -> Dict:
    """Conversion -> parse -> one repair on lint errors -> parse. Returns the record: sheets (first and
    final), accounting, lint errors/warnings of each pass, usable, timings, raw answers."""
    rec: Dict = {"lat": {}}
    t = time.time()
    raw = await call(P.TEMPLATE_SHEET_CONVERT_PROMPT, P.convert_user_prompt(old_sheet, scan_type,
                                                                           evidence_docs(reports), coverage),
                     P.ANALYSER_SETTINGS)
    rec["lat"]["convert_s"] = round(time.time() - t, 1)
    rec["raw"] = raw
    parsed = P.split_conversion(raw)
    sheet = parsed["skill_sheet"]
    rec.update(first_sheet=sheet, accounting=parsed["accounting"], dropped=parsed["dropped"],
               json_error=parsed["json_error"])
    structure, errors, warnings = parse(sheet)
    rec.update(first_errors=errors, first_warnings=warnings)
    if errors:
        t = time.time()
        repaired = await call(P.REPAIR_SYSTEM_PROMPT, P.repair_user_prompt(sheet, errors), P.REPAIR_SETTINGS)
        rec["lat"]["repair_s"] = round(time.time() - t, 1)
        sheet = P.strip_fences(repaired)
        structure, errors, warnings = parse(sheet)
        rec.update(repair_errors=errors)
    sources = [old_sheet] + [d["content"] for d in evidence_docs(reports)]
    snapped, rec["snaps"] = snap_to_source(sheet, sources)
    if rec["snaps"]:
        sheet = snapped
        structure, errors, warnings = parse(sheet)
    rec.update(sheet=sheet, structure=structure, errors=errors, warnings=warnings, usable=not errors)
    return rec


# ------------------------------------------------------------------------------------- faithfulness

def _norm(text: str) -> str:
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t.lower()).strip(" .")


QUOTE = re.compile(r'"([^"\n]{3,})"|“([^”\n]{3,})”')


def quotes(text: str) -> List[str]:
    """Quoted strings, line by line. A match that starts or ends with a space is the gap between two quotes
    (a line with an unpaired quote mark) and is skipped."""
    out = []
    for ln in text.splitlines():
        out += [q for q in (a or b for a, b in QUOTE.findall(ln)) if q.strip() == q]
    return out


def is_grounded(text: str, corpus: str) -> bool:
    """The quoted text occurs in the corpus (normalised), each {slot} standing for up to 80 characters or
    for a slot in the corpus. Text that is little more than slots carries no wording and counts as grounded
    only if found verbatim."""
    n = _norm(text)
    if n in corpus:
        return True
    parts = [re.escape(_norm(p)) for p in re.split(r"\{[^}]*\}", text) if _norm(p)]
    if not parts or len(re.findall(r"[a-z]{2,}", " ".join(parts))) < 2:
        return False
    return re.search(r".{0,80}?".join(parts), corpus) is not None


def sentences(text: str) -> List[str]:
    """Sentences of a quote (split after . ! ? even without a following space); "..." gaps and
    fragments without two words are left out."""
    parts = re.split(r"(?<=[.!?])\s*(?=[A-Z{])", text.replace("...", " "))
    return [p.strip() for p in parts if len(re.findall(r"[A-Za-z]{2,}", p)) >= 2]


UNIT_LINE = re.compile(r"^\s*(?:-\s+)?(NORMAL|NEGATIVE|FIXED|RULE)\b")
SNAP_RATIO = 0.92


def snap_to_source(sheet: str, sources: List[str]) -> Tuple[str, List[Dict]]:
    """Copy-error repair, by code: a quoted text on a NORMAL / NEGATIVE / FIXED / RULE line that is not in
    the sources but is a near-copy (character similarity >= SNAP_RATIO, a typo or dropped letter) of one
    source quote or sentence is replaced by that source text. Returns (sheet, snaps)."""
    import difflib

    corpus = _norm("\n".join(sources))
    cands: List[str] = []
    for src in sources:
        for q in quotes(src) + sentences(src):
            if q not in cands:
                cands.append(q)
    snaps: List[Dict] = []
    lines = sheet.splitlines()
    for i, ln in enumerate(lines):
        if not UNIT_LINE.match(ln):
            continue
        for q in quotes(ln):
            if "{" in q or is_grounded(q, corpus):
                continue
            best, score = None, 0.0
            for c in cands:
                if abs(len(c) - len(q)) > max(4, len(q) // 10):
                    continue
                r = difflib.SequenceMatcher(None, _norm(q), _norm(c)).ratio()
                if r > score:
                    best, score = c, r
            if best and score >= SNAP_RATIO and '"' not in best:
                lines[i] = lines[i].replace(f'"{q}"', f'"{best}"')
                snaps.append({"line": i + 1, "from": q, "to": best, "ratio": round(score, 3)})
    if not snaps:
        return sheet, snaps
    return "\n".join(lines) + ("\n" if sheet.endswith("\n") else ""), snaps


def old_headings(sheet: str) -> List[str]:
    """Every "## " / "### " heading of the old sheet (fixed-block and paragraph entries included)."""
    out = []
    for ln in sheet.splitlines():
        m = re.match(r"^#{2,3}\s+(.+?)\s*$", ln)
        if m:
            out.append(m.group(1).strip("[] "))
    return out


def old_units(sheet: str) -> Dict[str, List[str]]:
    """Quoted text of the old sheet by kind, judged by the heading or bullet it sits under: negative,
    fixed, normal, other."""
    kinds: Dict[str, List[str]] = {"negative": [], "fixed": [], "normal": [], "other": []}
    block = label = ""
    for ln in sheet.splitlines():
        h = re.match(r"^(#{2,3})\s+(.+)$", ln)
        if h:
            if len(h.group(1)) == 2:
                block = h.group(2).lower()
            label = h.group(2).lower() if len(h.group(1)) == 3 else ""
            continue
        top = re.match(r"^[-*]\s+(.*)$", ln)  # a top-level bullet sets the label its sub-bullets inherit
        if top:
            label = top.group(1).lower()
        where = f"{block} | {label}"
        if "fixed" in block:
            kind = "fixed"
        elif "negative" in where:
            kind = "negative"
        elif re.search(r"\bnormal pattern", where):
            kind = "normal"
        else:
            kind = "other"
        for q in quotes(ln):
            if q not in kinds[kind]:
                kinds[kind].append(q)
    return kinds


def faithfulness(old_sheet: str, new_sheet: str, reports: List[Dict], structure: Dict,
                 accounting: Optional[List[Dict]] = None, dropped: Optional[List[Dict]] = None,
                 coverage: Optional[List[str]] = None) -> Dict:
    """Code half of the faithfulness check (the hand read is the other half)."""
    new_n = _norm(new_sheet)
    acc_text = _norm(json.dumps(accounting or []) + json.dumps(dropped or []))
    para_names = [_norm(p["name"]) for p in structure.get("paragraphs", [])]
    # 1. headings: in the new sheet text or the accounting
    headings = []
    for h in old_headings(old_sheet):
        hn = _norm(re.sub(r"[*_`]", "", h))
        found = hn in new_n or any(hn in p or p in hn for p in para_names if p) or hn in acc_text
        headings.append({"heading": h, "accounted": found})
    # 2. old quoted text kept verbatim (anywhere in the new sheet), by kind
    # A multi-sentence old quote is kept when each of its sentences is kept (the grammar splits sentences).
    kept: Dict[str, Dict] = {}
    for kind, qs in old_units(old_sheet).items():
        missing = []
        for q in qs:
            if _norm(q) in new_n or is_grounded(q, new_n):
                continue
            lost = [s for s in sentences(q) if _norm(s) not in new_n and not is_grounded(s, new_n)]
            if lost:
                missing.append(" | ".join(lost))
        kept[kind] = {"total": len(qs), "missing": missing,
                      "missing_but_dropped": [q for q in missing if _norm(q.split(" | ")[0])[:40] in acc_text]}
    # 3. additions: quoted text of the new sheet with no source in the old sheet or the reports
    corpus = _norm(old_sheet + "\n" + "\n".join((r.get("final_content") or r.get("report_content") or "")
                                                for r in reports) + "\n" + " | ".join(coverage or []))
    unit_quotes = [n["text"] for n in structure.get("negatives", [])] + \
                  [n["text"] for n in structure.get("normals", [])] + \
                  [f["text"] for f in structure.get("fixed_blocks", [])]
    for r in structure.get("rules", []):
        unit_quotes += [r[k] for k in ("target", "then_text") if r.get(k)]
    all_new = []
    for q in unit_quotes + quotes(new_sheet):
        if q not in all_new:
            all_new.append(q)
    additions = [q for q in all_new if not is_grounded(q, corpus)]
    # 4. COVERS per paragraph
    covers = {p["name"]: p.get("covers", []) for p in structure.get("paragraphs", []) if p.get("covers")}
    return {"headings": headings, "headings_missing": [h["heading"] for h in headings if not h["accounted"]],
            "kept": kept, "new_quotes": len(all_new), "additions": additions, "covers": covers,
            "units": {"negatives": len(structure.get("negatives", [])), "normals": len(structure.get("normals", [])),
                      "fixed": len(structure.get("fixed_blocks", [])), "rules": len(structure.get("rules", [])),
                      "paragraphs": len(structure.get("paragraphs", [])), "sections": len(structure.get("sections", []))}}


def render_review(t: Dict, rec: Dict, fx: Dict) -> str:
    """The review file: lint result, faithfulness summary, accounting, then the old and new sheets."""
    L = [f"# {t['name']} — sheet conversion review", "",
         f"- template {t['template_id']} · reports {t.get('reports_total')} · scan type `{t['scan_type']}`",
         f"- evidence reports: {len(rec.get('evidence_ids', []))}" + (" (includes the smoke dictations: too few "
                                                                       "reports to hold out)" if rec.get("leak") else ""),
         f"- usable: **{rec['usable']}** · first pass {len(rec['first_errors'])} lint errors"
         + (f" → repair → {len(rec.get('repair_errors', []))}" if "repair_errors" in rec else "")
         + f" · warnings {len(rec['warnings'])} · latency {rec['lat']}", ""]
    if rec.get("snaps"):
        L += ["## Copy errors repaired by code (snap to source)"] + [
            f"- L{x['line']}: `{x['from']}` → `{x['to']}` ({x['ratio']})" for x in rec["snaps"]] + [""]
    if rec["errors"]:
        L += ["## Lint errors (final)"] + [f"- L{e['line']}: {e['reason']} — `{e['text'][:120]}`" for e in rec["errors"]] + [""]
    if rec["first_errors"]:
        L += ["## Lint errors (first pass)"] + [f"- L{e['line']}: {e['reason']} — `{e['text'][:120]}`"
                                                for e in rec["first_errors"]] + [""]
    if rec["warnings"]:
        L += ["## Lint warnings"] + [f"- L{w['line']}: {w['reason']} — `{w['text'][:120]}`" for w in rec["warnings"]] + [""]
    u = fx["units"]
    L += ["## Faithfulness (code)", "",
          f"- sections {u['sections']}, paragraphs {u['paragraphs']}, NORMAL {u['normals']}, NEGATIVE {u['negatives']},"
          f" FIXED {u['fixed']}, RULE {u['rules']}",
          f"- old headings not accounted for: {fx['headings_missing'] or 'none'}"]
    for kind, k in fx["kept"].items():
        L.append(f"- old {kind} quotes: {k['total']}, missing from new sheet {len(k['missing'])}"
                 + (f" (listed as dropped: {len(k['missing_but_dropped'])})" if k["missing_but_dropped"] else ""))
        L += [f"    - `{q}`" for q in k["missing"]]
    L.append(f"- new quoted texts {fx['new_quotes']}, without a source in the old sheet or reports: {len(fx['additions'])}")
    L += [f"    - `{q}`" for q in fx["additions"]]
    L += ["", "### COVERS", ""] + [f"- **{p}**: {', '.join(c)}" for p, c in fx["covers"].items()]
    L += ["", f"- stored coverage_sections: {', '.join(t.get('coverage_sections') or [])}", ""]
    L += ["## Model accounting (PART 2)", ""]
    for a in rec.get("accounting") or []:
        L.append(f"- {a.get('old')} → {a.get('new')}")
    L += ["", "### Dropped", ""] + [f"- `{d.get('old')}` — {d.get('reason')}" for d in rec.get("dropped") or []]
    if rec.get("json_error"):
        L.append(f"- (accounting JSON error: {rec['json_error']})")
    L += ["", "## Verdict (hand read)", "", "_to be written_", "",
          "## Old sheet", "", "````markdown", t["skill_sheet"].rstrip(), "````", "",
          "## New sheet", "", "````markdown", rec["sheet"].rstrip(), "````", ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------- driver

async def run_one(t: Dict, out: Path) -> Dict:
    evidence, held, leak = split_evidence(t["reports"])
    s = t["slug"]
    try:
        rec = await convert(t["skill_sheet"], t["scan_type"] or t["name"], evidence, t.get("coverage_sections"))
    except Exception as e:  # noqa: BLE001 - a lab run records failures and moves on
        rec = {"slug": s, "error": f"{type(e).__name__}: {e}"[:500]}
        (out / f"{s}.json").write_text(json.dumps(rec, indent=1))
        print(f"!! {s}: {rec['error'][:160]}", file=sys.stderr, flush=True)
        return rec
    rec.update(slug=s, name=t["name"], evidence_ids=[r["report_id"] for r in evidence],
               held_out_ids=[r["report_id"] for r in held], leak=leak)
    (out / f"{s}.raw.txt").write_text(rec.pop("raw"))
    (out / f"{s}.first.md").write_text(rec["first_sheet"])
    (out / f"{s}.new_sheet.md").write_text(rec["sheet"])
    fx = faithfulness(t["skill_sheet"], rec["sheet"], evidence, rec["structure"], rec.get("accounting"),
                      rec.get("dropped"), t.get("coverage_sections"))
    rec["faithfulness"] = fx
    (out / f"{s}.json").write_text(json.dumps(rec, indent=1, default=str))
    (out / f"{s}_review.md").write_text(render_review(t, rec, fx))
    print(f"{s:40} convert {rec['lat']['convert_s']:5.1f}s  first {len(rec['first_errors']):2} err"
          + (f"  repair {rec['lat']['repair_s']:5.1f}s -> {len(rec['errors'])} err" if "repair_s" in rec["lat"] else "")
          + f"  additions {len(fx['additions'])}", file=sys.stderr, flush=True)
    return rec


async def run(data_path: Path, out: Path, only: Optional[List[str]]) -> None:
    data = json.loads(data_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    ts = [t for t in data["templates"] if not only or t["slug"] in only]
    log = io.StringIO()
    with contextlib.redirect_stdout(log):  # the model runner prints its settings to stdout
        recs = await asyncio.gather(*(run_one(t, out) for t in ts))
    (out / "runner.log").write_text(log.getvalue())
    (out / "summary.json").write_text(json.dumps(
        [{k: r.get(k) for k in ("slug", "usable", "lat", "error")} | {
            "first_errors": len(r.get("first_errors", [])), "errors": len(r.get("errors", [])),
            "warnings": len(r.get("warnings", [])),
            "additions": len(r.get("faithfulness", {}).get("additions", []))} for r in recs], indent=1))


def check(data_path: Path, out: Path) -> None:
    """Re-run parse + faithfulness on saved new sheets (e.g. after a hand edit), rewriting the reviews."""
    data = json.loads(data_path.read_text())
    for t in data["templates"]:
        f = out / f"{t['slug']}.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text())
        evidence, _, _ = split_evidence(t["reports"])
        sheet = (out / f"{t['slug']}.new_sheet.md").read_text()
        sheet, snaps = snap_to_source(sheet, [t["skill_sheet"]] + [d["content"] for d in evidence_docs(evidence)])
        if snaps:
            (out / f"{t['slug']}.new_sheet.md").write_text(sheet)
            rec["snaps"] = rec.get("snaps", []) + snaps
        rec["sheet"] = sheet
        rec["structure"], rec["errors"], rec["warnings"] = parse(rec["sheet"])
        rec["usable"] = not rec["errors"]
        fx = faithfulness(t["skill_sheet"], rec["sheet"], evidence, rec["structure"], rec.get("accounting"),
                          rec.get("dropped"), t.get("coverage_sections"))
        rec["faithfulness"] = fx
        f.write_text(json.dumps(rec, indent=1, default=str))
        (out / f"{t['slug']}_review.md").write_text(render_review(t, rec, fx))
        print(f"{t['slug']:40} usable {rec['usable']}  errors {len(rec['errors'])}  additions {len(fx['additions'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("data")
    p.add_argument("--top", type=int, default=5)
    r = sub.add_parser("run")
    r.add_argument("data")
    r.add_argument("out")
    r.add_argument("--only", default="")
    c = sub.add_parser("check")
    c.add_argument("data")
    c.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "pull":
        pull(Path(a.data), a.top)
    elif a.cmd == "run":
        asyncio.run(run(Path(a.data), Path(a.out), [s for s in a.only.split(",") if s] or None))
    else:
        check(Path(a.data), Path(a.out))


if __name__ == "__main__":
    main()
