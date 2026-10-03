"""Shared plumbing for the review-engine gate labs (spec 2026-10-02 §11).

Production text is written only under $RR_LAB_OUT (a scratchpad), never inside the repo."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[4]
REPO = BACKEND.parent


def load_env() -> None:
    load_dotenv(BACKEND / ".env")


def lab_out(gate: str) -> Path:
    root = os.environ.get("RR_LAB_OUT")
    if not root:
        raise SystemExit("set RR_LAB_OUT to a scratchpad directory; production text never goes in the repo")
    p = (Path(root) / gate).resolve()
    if p == REPO or REPO in p.parents:
        raise SystemExit(f"RR_LAB_OUT must be outside the repo: {p}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_file(gate: str, stem: str, ext: str = "json") -> Path:
    return lab_out(gate) / f"{stem}_{os.getpid()}.{ext}"


def pipeline_scratch() -> Path:
    p = os.environ.get("RR_PIPELINE_SCRATCH")
    if not p:
        raise SystemExit("set RR_PIPELINE_SCRATCH to the pipeline session's scratchpad")
    return Path(p)


def read_json(p: Path | str) -> Any:
    return json.loads(Path(p).read_text())


def write_json(p: Path | str, obj: Any) -> Path:
    Path(p).write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return Path(p)


def read_jsonl(p: Path | str) -> List[dict]:
    return [json.loads(line) for line in Path(p).read_text().splitlines() if line.strip()]


def metabase(sql: str, timeout: float = 120) -> List[Dict[str, Any]]:
    """Read-only SQL against production through Metabase (database 2)."""
    load_env()
    r = httpx.post(os.environ["METABASE_URL"].rstrip("/") + "/api/dataset",
                   headers={"x-api-key": os.environ["METABASE_API_KEY"], "User-Agent": "curl/8",
                            "Content-Type": "application/json"},
                   json={"database": 2, "type": "native", "native": {"query": sql}}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"])
    cols = [c["name"] for c in d["data"]["cols"]]
    return [dict(zip(cols, row)) for row in d["data"]["rows"]]


def decode_json_list(v: Any) -> List[Any]:
    """Qwen string-encodes list fields (L-50): accept a list, a JSON-encoded list, or one plain string."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            out = json.loads(s)
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
    return [s]


SENT_END = re.compile(r"(?<=[.;])\s+(?=[A-Z])|\n+")
_HEADING = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$", re.M)


def sentences(text: str) -> List[Tuple[int, int]]:
    out, s = [], 0
    for m in SENT_END.finditer(text):
        out.append((s, m.start()))
        s = m.end()
    out.append((s, len(text)))
    return [(a, b) for a, b in out if text[a:b].strip() and not _HEADING.fullmatch(text[a:b].strip())]


def best_sentence(text: str, query: str) -> Tuple[int, int]:
    q = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    best, score = (0, 0), -1.0
    for a, b in sentences(text):
        w = set(re.findall(r"[a-z0-9]+", text[a:b].lower()))
        sc = len(q & w) / (len(w) ** 0.5 + 1)
        if sc > score:
            best, score = (a, b), sc
    return best


def section_of(report: str, pos: int) -> str:
    hs = [m.group(1) for m in _HEADING.finditer(report) if m.start() <= pos]
    return hs[-1].title() if hs else "Report"


def prod_cases() -> Dict[str, dict]:
    """id8 → {id, scan, dictation, history, report} for the 150 quick reports the pipeline session pulled."""
    rows = read_json(pipeline_scratch() / "jev_v2_rescore" / "prod_quick_150.json")
    out = {}
    for r in rows:
        v = (r.get("input_data") or {}).get("variables") or {}
        out[r["id"][:8]] = {"id": r["id"], "scan": v.get("SCAN_TYPE") or "", "dictation": v.get("FINDINGS") or "",
                            "history": v.get("CLINICAL_HISTORY") or "", "report": r.get("report_content") or ""}
    return out
