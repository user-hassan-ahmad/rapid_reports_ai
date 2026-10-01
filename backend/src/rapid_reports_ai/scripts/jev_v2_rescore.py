"""Jev wording v2 (L-49), production re-score: old vs new questions on the same prod inputs. Lab only.

No regeneration of reports and no prod writes. Input is a JSON list pulled read-only from prod
(Metabase /api/dataset) into the scratchpad: each row has input_data (dictation), report_content,
candidates (stored brief decisions / quality telemetry when present) and the skill sheet.

Per case, on the same inputs:
  omission   old: positive items, "The report states this dictated finding" < 0.5
             new: every item, Q_CONVEYS < 0.40; new flags are run through insert_findings (Qwen
             writes, Jev dup guard) to show what would be inserted
  restated   flagged report negatives (contradiction >= 0.6): old vs new removal confirmation
  if-present old noul presence vs new score / 3, banded by route_finding (label keep)
  branches   old Q_PRESENT vs new present_question, through the policy-1 action rule
  recs       old "unmet" >= 0.5 vs new 1 - met >= 0.5
  (the Q7 relation arm was removed with Q7 itself; its run_67723 results stay in the scratchpad)

    python -m rapid_reports_ai.scripts.jev_v2_rescore <rows.json> <out_dir>
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/hassan/Code/rapid_reports_ai/backend/.env")

from rapid_reports_ai import quick_report_brief as qb  # noqa: E402
from rapid_reports_ai import quick_report_quality as qq  # noqa: E402

# Old wordings, as on main before L-49.
OLD_Q_OMIT = "The report states this dictated finding, in any wording: "
OLD_Q_RESTATED = "The dictated findings report this finding: "
OLD_Q_FINDING = "The dictated findings report this imaging finding, in any wording or size: "
OLD_Q_PRESENT = "A dictated finding shows that this diagnosis or branch is present in this case. Branch: "
OLD_Q_REC_UNMET = ("The condition for this recommendation is not met by the dictated findings, or it belongs to a "
                   "diagnosis the findings rule out. Recommendation: ")
OLD_OMIT_FLAG = 0.5
_BACKGROUND = __import__("re").compile(r"^\s*(no|nil)\b|\b(unremarkable|normal|intact|clear)\b", __import__("re").I)

SEM = asyncio.Semaphore(6)


async def jev(state: str, qs: dict) -> dict:
    if not qs:
        return {}
    async with SEM:
        for attempt in range(3):
            try:
                return await asyncio.wait_for(qb._jev(state, qs), 30)
            except Exception as e:
                err = e
                await asyncio.sleep(1 + attempt)
    raise err


def band(p: float) -> str:
    return "dropped" if p < qb.PRESENT_LOW else ("present" if p >= qb.PRESENT_HIGH else "offered")


def diff_action(present: bool, t: str) -> str:
    return "present" if present else ("removed" if ("visible on this technique: yes" in t and "imaging-silent" not in t) else "open")


async def one(row: dict) -> dict:
    v = row["input_data"].get("variables", {})
    findings, scan = v.get("FINDINGS", ""), v.get("SCAN_TYPE", "") or row["input_data"].get("extracted_scan_type", "")
    report, sheet = row["report_content"] or "", row["sheet"] or ""
    out = {"id": row["id"], "created_at": row["created_at"], "scan": scan, "findings": findings, "changes": [], "errors": []}
    dstate = f"SCAN TYPE: {scan}\nDICTATED FINDINGS:\n{findings}"

    # ── omission (report state) and restated (dictation state) ──
    old_items = [t for t in qb.split_findings(findings) if not _BACKGROUND.search(t)]
    new_items = qq.dictated_items(findings)
    fnd, imp = qq.report_sections(report)
    cls = list(dict.fromkeys(qq.clauses(fnd) + qq.clauses(imp)))
    restated = {i: qq.restate(t) for i, t in enumerate(cls)}
    try:
        o_old, o_new, contra = await asyncio.gather(
            jev(f"REPORT:\n{report}", {f"i{i}": {"type": "noul", "instructions": OLD_Q_OMIT + t} for i, t in enumerate(old_items)}),
            jev(f"REPORT:\n{report}", {f"i{i}": {"type": "noul", "instructions": qq.Q_CONVEYS + t} for i, t in enumerate(new_items)}),
            jev(dstate, {**{f"c{i}": {"type": "noul", "instructions": qq.Q_CONTRA + t} for i, t in enumerate(cls)},
                         **{f"ro{i}": {"type": "noul", "instructions": OLD_Q_RESTATED + r} for i, r in restated.items() if r},
                         **{f"rn{i}": qq.q_restated(r) for i, r in restated.items() if r}}))
        old_flag = {t: float(o_old[f"i{i}"]["noul"]) for i, t in enumerate(old_items)}
        new_flag = {t: float(o_new[f"i{i}"]["noul"]) for i, t in enumerate(new_items)}
        out["omission"] = {"old": old_flag, "new": new_flag}
        new_omitted = []
        for t in new_items:
            was = t in old_flag and old_flag[t] < OLD_OMIT_FLAG
            now = new_flag[t] < qq.OMIT_FLAG
            if now:
                new_omitted.append(t)
            if was != now:
                out["changes"].append({"q": "omission", "item": t, "old": ("flag" if was else ("not asked" if t not in old_flag else "ok")),
                                       "new": "flag" if now else "ok",
                                       "scores": {"old": old_flag.get(t), "new": round(new_flag[t], 3)}})
        for t, s in old_flag.items():   # items only the old splitter produced (none expected)
            if t not in new_flag and s < OLD_OMIT_FLAG:
                out["changes"].append({"q": "omission", "item": t, "old": "flag", "new": "not asked", "scores": {"old": s}})
        if new_omitted and any(c["q"] == "omission" and c["new"] == "flag" for c in out["changes"]):
            ins = await qq.insert_findings(report, findings, new_omitted)
            out["would_insert"] = {"items": new_omitted, "applied": ins.applied, "skipped": ins.skipped,
                                   "dup_check": ins.dup_check, "error": ins.error,
                                   "added": [s for s in qq._sentences(qq.report_sections(ins.report)[0])
                                             if s not in qq._sentences(fnd)]}
        for i, t in enumerate(cls):
            r = restated[i]
            if not r or float(contra[f"c{i}"]["noul"]) < qq.CONTRA_FLAG:
                continue
            ro, rn = float(contra[f"ro{i}"]["noul"]), float(contra[f"rn{i}"]["noul"])
            if (ro >= qq.RESTATED_FLAG) != (rn >= qq.RESTATED_FLAG):
                out["changes"].append({"q": "restated", "item": t, "old": "remove" if ro >= 0.5 else "keep",
                                       "new": "remove" if rn >= 0.5 else "keep",
                                       "scores": {"contra": float(contra[f"c{i}"]["noul"]), "old": ro, "new": rn}})
    except Exception as e:
        out["errors"].append(f"check: {type(e).__name__}: {e}")

    # ── brief questions (dictation state) ──
    secs = qb.parse_sheet(sheet)
    matrix, imp_s = qb._section(secs, "Companion Matrix"), qb._section(secs, "Impression Exemplars")
    diffs, recs = qb.differential_lines(secs), qb._recommendations(imp_s)
    fb = qb._bullet(matrix, "If present")
    cands = qb.parse_if_present(fb.lines) if fb else []
    keys = qb.distinct_keys(cands)
    try:
        old_qs = {**{f"d{k}": {"type": "noul", "instructions": OLD_Q_PRESENT + t} for k, t in enumerate(diffs)},
                  **{f"r{k}": {"type": "noul", "instructions": OLD_Q_REC_UNMET + t} for k, t in enumerate(recs)},
                  **{f"f{i}": {"type": "noul", "instructions": OLD_Q_FINDING + k} for i, k in enumerate(keys)}}
        new_qs = {**{f"d{k}": qb.present_question(t) for k, t in enumerate(diffs)},
                  **{f"r{k}": {"type": "noul", "instructions": qb.Q_REC_MET + t} for k, t in enumerate(recs)},
                  **{f"f{i}": qb.q_finding(k) for i, k in enumerate(keys)}}
        a_old, a_new = await asyncio.gather(jev(dstate, old_qs), jev(dstate, new_qs))
        for k, t in enumerate(diffs):
            o, n = float(a_old[f"d{k}"]["noul"]), float(a_new[f"d{k}"]["noul"])
            ao, an = diff_action(o >= 0.5, t), diff_action(n >= 0.5, t)
            if ao != an:
                out["changes"].append({"q": "branch", "item": t, "old": ao, "new": an, "scores": {"old": o, "new": n}})
        for k, t in enumerate(recs):
            o, n = float(a_old[f"r{k}"]["noul"]), float(a_new[f"r{k}"]["noul"])
            ro, rn = o >= 0.5, (1 - n) >= 0.5
            if ro != rn:
                out["changes"].append({"q": "recommendation", "item": t, "old": "removed" if ro else "kept",
                                       "new": "removed" if rn else "kept", "scores": {"old_unmet": o, "new_met": n}})
        for i, key in enumerate(keys):
            o, n = float(a_old[f"f{i}"]["noul"]), qb.finding_presence(a_new[f"f{i}"])
            if band(o) != band(n):
                out["changes"].append({"q": "if_present", "item": key, "old": band(o), "new": band(n),
                                       "scores": {"old": o, "new": round(n, 3)},
                                       "negatives": [(c.text, c.tag) for c in cands if c.key == key]})
        out["counts"] = {"diffs": len(diffs), "recs": len(recs), "keys": len(keys)}
    except Exception as e:
        out["errors"].append(f"brief: {type(e).__name__}: {e}")

    return out


async def main(rows_path: str, out_dir: str):
    rows = json.loads(Path(rows_path).read_text())
    if len(sys.argv) > 3 and sys.argv[3] != "--selector":   # rerun only these ids, merged into an existing results.json
        only = set(Path(sys.argv[3]).read_text().split())
        prev = json.loads((Path(out_dir) / "results.json").read_text())
        redo = {r["id"]: r for r in await asyncio.gather(*(one(r) for r in rows if r["id"] in only))}
        res = [redo.get(r["id"], r) for r in prev]
        return _write(res, Path(out_dir))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = await asyncio.gather(*(one(r) for r in rows))
    _write(res, out)


def _write(res: list, out: Path):
    (out / "results.json").write_text(json.dumps(res, indent=1))
    by_q = Counter((c["q"], c["old"], c["new"]) for r in res for c in r["changes"])
    lines = [f"# Jev wording v2 re-score — {len(res)} prod quick reports", "",
             f"errors: {sum(bool(r['errors']) for r in res)} cases", "",
             "| question | old -> new | n |", "|---|---|---|"]
    lines += [f"| {q} | {o} -> {n} | {k} |" for (q, o, n), k in sorted(by_q.items())]
    tot = Counter()
    for r in res:
        tot["omission items"] += len((r.get("omission") or {}).get("new", {}))
        for k, v in (r.get("counts") or {}).items():
            tot[k] += v
    lines += ["", "asked: " + ", ".join(f"{k} {v}" for k, v in tot.items())]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    md = []
    for r in res:
        if not r["changes"] and not r["errors"]:
            continue
        md += [f"## {r['id'][:8]} {r['created_at'][:16]} — {r['scan']}", "", "```", r["findings"].strip(), "```", ""]
        md += [f"- **{c['q']}** {c['old']} -> {c['new']}: {c['item']}  `{json.dumps(c.get('scores'))}`"
               + (f"  negatives={c['negatives']}" if c.get("negatives") else "") for c in r["changes"]]
        if r.get("would_insert"):
            md.append(f"- would insert: `{json.dumps(r['would_insert'])}`")
        md += [f"- ERROR {e}" for e in r["errors"]] + [""]
    (out / "changed.md").write_text("\n".join(md))
    print((out / "summary.md").read_text())


# ── second re-score: the omission selector (group F) ─────────────────────────

async def one_selector(row: dict) -> dict:
    """Production today (regex selection, old wording < 0.5) vs the shipped check (qq.check: selector +
    conveys < 0.40), then the shipped inserter on the new flags, keeping each inserted sentence with the
    sentence it follows. Recommendations are re-asked to confirm the Q6 changes hold."""
    v = row["input_data"].get("variables", {})
    findings, scan = v.get("FINDINGS", ""), v.get("SCAN_TYPE", "") or row["input_data"].get("extracted_scan_type", "")
    report = row["report_content"] or ""
    out = {"id": row["id"], "created_at": row["created_at"], "scan": scan, "findings": findings, "errors": []}
    if not report.strip():
        out["errors"].append("empty report")
        return out
    old_items = qq.positive_items(findings)
    try:
        o_old = await jev(f"REPORT:\n{report}", {f"i{i}": {"type": "noul", "instructions": OLD_Q_OMIT + t}
                                                for i, t in enumerate(old_items)})
        res = await qq.check(report, findings, scan, [])   # live path; its own 6 s timeouts
        out["old_flags"] = [t for i, t in enumerate(old_items) if float(o_old[f"i{i}"]["noul"]) < OLD_OMIT_FLAG]
        out["old_scores"] = {t: float(o_old[f"i{i}"]["noul"]) for i, t in enumerate(old_items)}
        out["new_flags"] = [f.text for f in res.flags if f.kind == "omission"]
        out["selector"], out["n_items"], out["n_selected"], out["check_error"] = res.selector, res.n_items, res.n_selected, res.error
        if out["new_flags"]:
            ins = await qq.insert_findings(report, findings, out["new_flags"])
            before = set(qq._sentences(report))
            new_s = [x for x in qq._sentences(ins.report) if x not in before]
            ctx = []
            for x in new_s:
                i = ins.report.find(x)
                ctx.append({"sentence": x, "before": ins.report[max(0, i - 160):i].strip()})
            out["insert"] = {"applied": ins.applied, "skipped": ins.skipped, "dup_check": ins.dup_check,
                             "error": ins.error, "added": ctx}
    except Exception as e:
        out["errors"].append(f"omission: {type(e).__name__}: {e}")
    secs = qb.parse_sheet(row["sheet"] or "")
    recs = qb._recommendations(qb._section(secs, "Impression Exemplars"))
    if recs:
        try:
            dstate = f"SCAN TYPE: {scan}\nDICTATED FINDINGS:\n{findings}"
            a_old, a_new = await asyncio.gather(
                jev(dstate, {f"r{k}": {"type": "noul", "instructions": OLD_Q_REC_UNMET + t} for k, t in enumerate(recs)}),
                jev(dstate, {f"r{k}": {"type": "noul", "instructions": qb.Q_REC_MET + t} for k, t in enumerate(recs)}))
            out["recs"] = [{"text": t, "old": "removed" if float(a_old[f"r{k}"]["noul"]) >= 0.5 else "kept",
                            "new": "removed" if 1 - float(a_new[f"r{k}"]["noul"]) >= 0.5 else "kept"}
                           for k, t in enumerate(recs)]
        except Exception as e:
            out["errors"].append(f"recs: {type(e).__name__}: {e}")
    return out


async def main_selector(rows_path: str, out_dir: str):
    rows = json.loads(Path(rows_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    case_sem, done = asyncio.Semaphore(4), [0]   # cases in flight; jev() keeps its own SEM (never nested)

    async def bounded(r):
        async with case_sem:
            try:
                res = await asyncio.wait_for(one_selector(r), 60)
            except Exception as e:
                res = {"id": r["id"], "created_at": r["created_at"], "errors": [f"case: {type(e).__name__}: {e}"]}
        done[0] += 1
        if done[0] % 25 == 0:
            print(f"progress {done[0]}/{len(rows)}", flush=True)
        return res
    res = await asyncio.gather(*(bounded(r) for r in rows))
    (out / "results.json").write_text(json.dumps(res, indent=1))
    print(f"{len(res)} cases; errors {sum(bool(r['errors']) for r in res)}; "
          f"old flags {sum(len(r.get('old_flags', [])) for r in res)}; new flags {sum(len(r.get('new_flags', [])) for r in res)}; "
          f"inserted {sum(len((r.get('insert') or {}).get('added', [])) for r in res)}")


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[3] == "--selector":
        asyncio.run(main_selector(sys.argv[1], sys.argv[2]))
    else:
        asyncio.run(main(sys.argv[1], sys.argv[2]))
