"""Phase G lab: grammar-form skill sheets from real example reports (spec 2026-10-01 template sheet grammar).

Lab only — production analyser untouched. Pulls templated reports from prod via Metabase (read-only SQL),
runs the amended analyser (template_sheet_lab_prompts), parses the sheet with the grammar parser, makes
one lint-repair call when the parse has errors, and writes every sheet, parse result and timing to an
output directory. The pulled data is production data: it lives in a scratch file, never in the repo.

Usage (from backend/):
  uv run python -m rapid_reports_ai.scripts.template_sheet_lab pull <data.json>
  uv run python -m rapid_reports_ai.scripts.template_sheet_lab run <data.json> <out_dir> [--only name1,name2]
  uv run python -m rapid_reports_ai.scripts.template_sheet_lab reparse <out_dir>
Env: METABASE_URL / METABASE_API_KEY (pull), model keys (run); read from $LAB_ENV_FILE or backend/.env.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv(os.environ.get("LAB_ENV_FILE") or Path(__file__).resolve().parents[3] / ".env")
os.environ["DATABASE_URL"] = "sqlite://"  # the lab never touches an app database (imports build an engine)

from rapid_reports_ai import template_sheet_lab_prompts as P  # noqa: E402

TEMPLATES = [
    "CT TAVI (Non-Valve Findings)",
    "CT Coronary Angiogram",
    "CT Abdomen and Pelvis (Acute & Staging)",
    "CT Trauma Polytrauma",
    "CT Aorta Angiogram Reporting - Rumman",
    "CMR Non-Stress (Dr. Sabeeh Syed)",
    "Cardiac MR 2",
    "CT Abdomen and Pelvis (Portal Venous)",
]
MAX_EXAMPLES, HELD_OUT, MIN_EXAMPLES = 5, 2, 3


# ---------------------------------------------------------------------------------------------- data

def _metabase(sql: str) -> List[Dict]:
    import httpx

    r = httpx.post(
        os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
        headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8"},
        json={"database": 2, "type": "native", "native": {"query": sql}},
        timeout=90,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"])
    cols = [c["name"] for c in d["data"]["cols"]]
    return [dict(zip(cols, row)) for row in d["data"]["rows"]]


def split_reports(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Distinct dictations only (a regenerated report shares its findings), oldest first. The newest
    distinct reports are held out (up to HELD_OUT, never leaving fewer than MIN_EXAMPLES examples);
    up to MAX_EXAMPLES of the ones before them are the examples."""
    seen: Dict[str, Dict] = {}
    for r in sorted(rows, key=lambda r: r["created_at"]):
        key = hashlib.md5((r.get("findings") or "").strip().encode()).hexdigest()
        seen[key] = r  # latest regeneration of a dictation wins
    distinct = sorted(seen.values(), key=lambda r: r["created_at"])
    held = max(0, min(HELD_OUT, len(distinct) - MIN_EXAMPLES))
    examples = distinct[: len(distinct) - held][-MAX_EXAMPLES:]
    return examples, distinct[len(distinct) - held:]


def pull(out: Path) -> Dict:
    names = ",".join("'" + n.replace("'", "''") + "'" for n in TEMPLATES)
    rows = _metabase(
        f"""select t.id template_id, t.name, r.id report_id, r.created_at, r.report_content,
                   v.report_content latest_version_content, v.version_number latest_version,
                   r.input_data::jsonb->'variables'->>'FINDINGS' findings,
                   r.input_data::jsonb->'variables'->>'CLINICAL_HISTORY' clinical_history
            from reports r join templates t on t.id = r.template_id
            left join lateral (select rv.report_content, rv.version_number from report_versions rv
                               where rv.report_id = r.id order by rv.version_number desc limit 1) v on true
            where t.name in ({names}) and r.report_content is not null"""
    )
    # Edited versions are closer to the radiologist's own voice than the generated report.
    for r in rows:
        r["content"] = r["latest_version_content"] or r["report_content"]
        r["content_source"] = f"version {r['latest_version']}" if r["latest_version_content"] else "report_content"
    data = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "templates": []}
    for name in TEMPLATES:
        mine = [r for r in rows if r["name"] == name]
        if not mine:
            print(f"!! no reports for {name}")
            continue
        # a duplicated template name: the template with the most reports
        counts: Dict[str, int] = {}
        for r in mine:
            counts[r["template_id"]] = counts.get(r["template_id"], 0) + 1
        tid = max(counts, key=counts.get)
        mine = [r for r in mine if r["template_id"] == tid]
        examples, held = split_reports(mine)
        data["templates"].append({
            "name": name, "template_id": tid, "reports_total": len(mine),
            "examples": [{"report_id": r["report_id"], "content": r["content"], "content_source": r["content_source"]}
                         for r in examples],
            "held_out": [{"report_id": r["report_id"], "findings": r["findings"],
                          "clinical_history": r["clinical_history"], "report_content": r["report_content"],
                          "final_content": r["content"], "content_source": r["content_source"]}
                         for r in held],
        })
        versions = sum(r["content_source"] != "report_content" for r in examples)
        print(f"{name[:45]:45} total {len(mine):3}  examples {len(examples)} ({versions} from a version)"
              f"  held-out {len(held)}")
    out.write_text(json.dumps(data, indent=1))
    return data


# -------------------------------------------------------------------------------------------- parser

def parse(sheet: str) -> Tuple[Dict, List[Dict]]:
    """The grammar parser (G1). Returns the structure as a dict and the lint errors; a sheet that lints
    clean but is not usable (no findings- or impression-role section) gets one synthetic error so the
    repair call sees it."""
    import dataclasses

    from rapid_reports_ai.template_sheet_grammar import parse_sheet

    res = parse_sheet(sheet)
    errs = [dataclasses.asdict(e) for e in res.errors]
    if not errs and not res.structure.usable:
        errs.append({"line": 0, "text": "", "reason": "structure not usable",
                     "detail": "the Report Structure block needs a findings-role and an impression-role SECTION"})
    return res.structure.model_dump(), errs


# ------------------------------------------------------------------------------------------- calls

# The model runner prints its settings to stdout. redirect_stdout swaps sys.stdout process-wide, so
# concurrent calls must not each redirect (they restore each other's buffers): run() redirects once
# around the whole gather and progress goes to stderr.

async def analyse(examples: List[Dict], scan_type: str) -> Tuple[Dict, float, str]:
    """The production analyser's call (model, settings, JSON contract) with the lab system prompt."""
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _run_agent_with_model
    from rapid_reports_ai.template_manager import TemplateManager

    t = time.time()
    result = await _run_agent_with_model(
        model_name=MODEL_CONFIG["SKILL_SHEET_ANALYZER"], output_type=str,
        system_prompt=P.ANALYSER_SYSTEM_PROMPT, user_prompt=P.analyser_user_prompt(examples, scan_type),
        api_key="", use_thinking=True, model_settings=P.ANALYSER_SETTINGS)
    raw = result.output if hasattr(result, "output") else str(result)
    try:
        parsed = TemplateManager._parse_skill_sheet_json(raw, ["skill_sheet", "summary", "questions"])
    except Exception as e:  # noqa: BLE001 - keep the raw answer for the post-mortem
        raise AnalyseError(f"{type(e).__name__}: {e}", raw, time.time() - t) from e
    return parsed, time.time() - t, raw


class AnalyseError(Exception):
    def __init__(self, msg: str, raw: str, seconds: float):
        super().__init__(msg)
        self.raw, self.seconds = raw, seconds


async def repair(sheet: str, errors: List[Dict]) -> Tuple[str, float]:
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _run_agent_with_model

    t = time.time()
    result = await _run_agent_with_model(
        model_name=MODEL_CONFIG["SKILL_SHEET_ANALYZER"], output_type=str,
        system_prompt=P.REPAIR_SYSTEM_PROMPT, user_prompt=P.repair_user_prompt(sheet, errors),
        api_key="", use_thinking=True, model_settings=P.REPAIR_SETTINGS)
    return P.strip_fences(result.output if hasattr(result, "output") else str(result)), time.time() - t


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


def load_synthetic(root: Path) -> Dict:
    """Synthetic consultant-grade sets (tests/fixtures/sheet_lab/<set>/examples/NN.md + answer_key.json),
    in the same shape as the pulled prod data. A set without an answer key yet is skipped."""
    templates = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        key_path = d / "answer_key.json"
        examples = sorted((d / "examples").glob("*.md"))
        if not key_path.exists() or not examples:
            print(f"!! {d.name}: no answer key or examples yet, skipped", file=sys.stderr)
            continue
        key = json.loads(key_path.read_text())
        templates.append({"name": key.get("scan_type") or d.name, "slug": d.name, "answer_key": key,
                          "examples": [{"report_id": f.name, "content": f.read_text()} for f in examples]})
    return {"templates": templates}


def _score(rec: Dict, t: Dict) -> None:
    if t.get("answer_key") and rec.get("structure"):
        from rapid_reports_ai.scripts.template_sheet_lab_score import score

        rec["score"] = score(rec["structure"], t["answer_key"])


async def run_one(t: Dict, out: Path) -> Dict:
    rec: Dict = {"name": t["name"], "examples": len(t["examples"])}
    s = t.get("slug") or slug(t["name"])
    try:
        parsed, rec["analyse_s"], raw = await analyse(t["examples"], t["name"])
    except Exception as e:  # noqa: BLE001 - a lab run records failures and moves on
        rec["error"] = f"{type(e).__name__}: {e}"[:500]
        if isinstance(e, AnalyseError):
            rec["analyse_s"] = e.seconds
            (out / f"{s}.raw.txt").write_text(e.raw)
        (out / f"{s}.json").write_text(json.dumps(rec, indent=1))
        print(f"!! {t['name']}: {rec['error'][:120]}", file=sys.stderr, flush=True)
        return rec
    sheet = parsed["skill_sheet"]
    (out / f"{s}.sheet.md").write_text(sheet)
    structure, errors = parse(sheet)
    rec.update(first_pass_errors=errors, first_pass_ok=not errors, summary=parsed["summary"],
               questions=parsed["questions"])
    if errors:
        fixed, rec["repair_s"] = await repair(sheet, errors)
        (out / f"{s}.repaired.md").write_text(fixed)
        structure, errors = parse(fixed)
        rec.update(repair_errors=errors, repair_ok=not errors)
    rec["structure"] = structure
    rec["final_ok"] = not errors
    rec["grounding"] = grounding(structure, t["examples"])
    _score(rec, t)
    (out / f"{s}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(f"{t['name'][:45]:45} analyse {rec['analyse_s']:5.1f}s  first {len(rec['first_pass_errors']):2} err"
          + (f"  repair {rec['repair_s']:5.1f}s -> {len(errors)} err" if "repair_s" in rec else ""),
          file=sys.stderr, flush=True)
    return rec


async def run(data_path: Path, out: Path, only: Optional[List[str]]) -> None:
    data = load_synthetic(data_path) if data_path.is_dir() else json.loads(data_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    templates = [t for t in data["templates"] if not only or any(o.lower() in t["name"].lower() for o in only)]
    with contextlib.redirect_stdout(io.StringIO()):
        recs = await asyncio.gather(*(run_one(t, out) for t in templates))
    n = len(recs)
    summary = {
        "templates": n,
        "first_pass_ok": sum(bool(r.get("first_pass_ok")) for r in recs),
        "final_ok": sum(bool(r.get("final_ok")) for r in recs),
        "errors": [r["name"] for r in recs if "error" in r],
        "lint_classes": _classes(recs),
        "timings": {r["name"]: {k: round(r[k], 1) for k in ("analyse_s", "repair_s") if k in r} for r in recs},
        "grounded": {r["name"]: r["grounding"]["grounded"] for r in recs if "grounding" in r},
    }
    if any("score" in r for r in recs):
        summary["score"] = _score_summary(recs)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def _score_summary(recs: List[Dict]) -> Dict:
    """Per-set unit recall, and per-kind recall/precision pooled over the sets."""
    pooled: Dict[str, List[int]] = {}
    for r in recs:
        for kind, v in r.get("score", {}).get("per_kind", {}).items():
            p = pooled.setdefault(kind, [0, 0, 0])
            p[0], p[1], p[2] = p[0] + v["planted"], p[1] + v["emitted"], p[2] + v["matched"]
    return {
        "units_recall": {r["name"]: r["score"]["units_recall"] for r in recs if "score" in r},
        "per_kind": {k: {"planted": a, "emitted": b, "matched": m,
                         "recall": round(m / a, 2) if a else None, "precision": round(m / b, 2) if b else None}
                     for k, (a, b, m) in sorted(pooled.items())},
    }


def rescore(root: Path, out: Path) -> None:
    """Score saved sheets of a synthetic run against the answer keys (e.g. after a key is revised)."""
    data = {t["slug"]: t for t in load_synthetic(root)["templates"]}
    recs = []
    for f in sorted(out.glob("*.json")):
        if f.stem in data:
            rec = json.loads(f.read_text())
            _score(rec, data[f.stem])
            f.write_text(json.dumps(rec, indent=1, default=str))
            recs.append(rec)
    print(json.dumps(_score_summary(recs), indent=1))


def _classes(recs: List[Dict]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {"first_pass": {}, "after_repair": {}}
    for r in recs:
        for key, errs in (("first_pass", r.get("first_pass_errors", [])), ("after_repair", r.get("repair_errors", []))):
            for e in errs:
                cls = re.sub(r"\s+\S*\d\S*|[\"'].*$", "", str(e.get("reason", e)))[:60]
                out[key][cls] = out[key].get(cls, 0) + 1
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip(" .")


def quoted_units(structure: Dict) -> List[Tuple[str, str]]:
    """(kind, quoted text) for every unit text the sheet claims is the radiologist's wording."""
    out: List[Tuple[str, str]] = []
    out += [("negative", n["text"]) for n in structure.get("negatives", [])]
    out += [("normal", n["text"]) for n in structure.get("normals", [])]
    out += [("fixed", f["text"]) for f in structure.get("fixed_blocks", [])]
    for r in structure.get("rules", []):
        out += [(f"rule:{r['effect']}", r[k]) for k in ("then_text",) if r.get(k)]
    out += [("if_present", n["text"]) for ip in structure.get("if_present", []) for n in ip["negatives"]]
    return out


def is_grounded(text: str, corpus: str) -> bool:
    """The quoted text occurs in the examples, each {slot} standing for up to 80 characters. Text that is
    little more than slots ("{finding}.") is not grounded: it carries no wording of the radiologist's."""
    literal = re.sub(r"\{[^}]*\}", "", text)
    if len(re.findall(r"[a-z]{2,}", literal.lower())) < 2:
        return False
    parts = [re.escape(_norm(p)) for p in re.split(r"\{[^}]*\}", text)]
    pattern = r".{0,80}?".join(p for p in parts)
    return bool(pattern.strip()) and re.search(pattern, corpus) is not None


def grounding(structure: Dict, examples: List[Dict]) -> Dict:
    corpus = _norm("\n".join(e["content"] for e in examples))
    by_kind: Dict[str, List[int]] = {}
    misses = []
    for kind, text in quoted_units(structure):
        g = is_grounded(text, corpus)
        k = kind.split(":")[0]
        by_kind.setdefault(k, [0, 0])
        by_kind[k][0] += g
        by_kind[k][1] += 1
        if not g:
            misses.append(f"{kind}: {text}")
    total = [sum(v[0] for v in by_kind.values()), sum(v[1] for v in by_kind.values())]
    return {"grounded": total, "by_kind": by_kind, "ungrounded": misses}


def ground(data_path: Path, out: Path) -> None:
    """Grounding of saved sheets against their example reports (quoted unit text found in the examples)."""
    data = {slug(t["name"]): t for t in json.loads(data_path.read_text())["templates"]}
    for f in sorted(out.glob("*.json")):
        if f.stem not in data:
            continue
        rec = json.loads(f.read_text())
        if "structure" not in rec:
            continue
        g = grounding(rec["structure"], data[f.stem]["examples"])
        print(f"{f.stem[:40]:40} grounded {g['grounded'][0]:3}/{g['grounded'][1]:3}  "
              + "  ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(g["by_kind"].items())))


def reparse(out: Path) -> None:
    """Re-lint saved sheets with the current parser (e.g. after the G1 parser lands)."""
    for f in sorted(out.glob("*.sheet.md")):
        rep = f.with_name(f.name.replace(".sheet.md", ".repaired.md"))
        _, e1 = parse(f.read_text())
        line = f"{f.name[:-9]:40} first {len(e1):2} err"
        if rep.exists():
            _, e2 = parse(rep.read_text())
            line += f"  repaired {len(e2):2} err"
        print(line)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("data")
    r = sub.add_parser("run"); r.add_argument("data"); r.add_argument("out"); r.add_argument("--only", default="")
    rp = sub.add_parser("reparse"); rp.add_argument("out")
    g = sub.add_parser("ground"); g.add_argument("data"); g.add_argument("out")
    sc = sub.add_parser("score"); sc.add_argument("fixtures"); sc.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "score":
        return rescore(Path(a.fixtures), Path(a.out))
    if a.cmd == "pull":
        pull(Path(a.data))
    elif a.cmd == "run":
        asyncio.run(run(Path(a.data), Path(a.out), [o for o in a.only.split(",") if o] or None))
    elif a.cmd == "ground":
        ground(Path(a.data), Path(a.out))
    else:
        reparse(Path(a.out))


if __name__ == "__main__":
    sys.exit(main())
