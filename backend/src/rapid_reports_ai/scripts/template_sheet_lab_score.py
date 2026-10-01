"""Score a parsed grammar sheet against a synthetic set's answer key (tests/fixtures/sheet_lab/<set>/
answer_key.json): per-kind recall and precision, with the misses and the spurious units listed.

Matching is lexical and lenient on purpose: the analyser quotes the examples, the key quotes the same
examples, so normalised content-word overlap separates a captured unit from a missed one.
- NEGATIVE / NORMAL / FIXED: quoted text overlap (slots removed). A planted unit found only under another
  kind (a negative written as part of a NORMAL sentence) counts as a miss for its kind and is reported as
  `cross_kind`.
- RULE: same effect, and the condition's subject overlaps or the rule's quoted text overlaps.
- LIST_MISSING: per item.
- IF_PRESENT: the negative's text overlaps (the finding is reported, not required).
- TERM: same term, case-insensitive.
- Sections: by name or header.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_STOP = frozenset("""
a an the this that these those it its is are was were be been being has have had of in on at to for from by
with without within into and or nor but not no any all some each every either both other such same as than then
reported reports report stated states state described present absent seen identified noted there which who
""".split())
TEXT_MATCH, COND_MATCH = 0.5, 0.34


def toks(text: Optional[str]) -> set:
    text = re.sub(r"\{[^}]*\}", " ", text or "").lower()
    return {w for w in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text) if w not in _STOP and len(w) > 1}


def sim(a: Optional[str], b: Optional[str]) -> float:
    """Overlap of content words: the larger of Jaccard and containment of the smaller set (min 2 words)."""
    x, y = toks(a), toks(b)
    if not x or not y:
        return 0.0
    inter = len(x & y)
    jac = inter / len(x | y)
    cont = inter / min(len(x), len(y)) if inter >= 2 else 0.0  # one shared word never proves containment
    return max(jac, cont)


def _cond(c) -> str:
    if isinstance(c, dict):
        return c.get("statement") or ""
    return re.sub(r"^\s*(findings|history|context)\s*:\s*", "", c or "")


def _grammar_finding(p: Dict) -> str:
    m = re.search(r"IF_PRESENT\s*\[([^\]]+)\]", p.get("grammar") or "")
    return m.group(1) if m else (p.get("target") or "")


def _key_units(key: Dict) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for p in key["planted"]:
        kind = p["kind"]
        if kind == "RULE" and p.get("effect") == "list_missing":
            for item in p.get("items") or []:
                out.setdefault("LIST_MISSING item", []).append({"id": p["id"], "text": item})
            continue
        if kind == "RULE":
            kind = f"RULE {p.get('effect')}"
        texts = [p.get(k) for k in ("text", "then_text", "target", "anchor") if p.get(k)]
        out.setdefault(kind, []).append({
            "id": p["id"], "text": p.get("text") or p.get("then_text") or p.get("target") or "",
            "texts": texts, "cond": _cond(p.get("condition")), "finding": _grammar_finding(p),
            "grammar": p.get("grammar", ""),
        })
    return out


def _sheet_units(s: Dict) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for n in s.get("negatives", []):
        out.setdefault("NEGATIVE", []).append({"text": n["text"]})
    for n in s.get("normals", []):
        out.setdefault("NORMAL", []).append({"text": n["text"]})
    for f in s.get("fixed_blocks", []):
        out.setdefault("FIXED", []).append({"text": f["text"]})
    for r in s.get("rules", []):
        if r["effect"] == "list_missing":
            for item in r.get("items") or []:
                out.setdefault("LIST_MISSING item", []).append({"text": item})
            continue
        texts = [r.get(k) for k in ("then_text", "target", "anchor") if r.get(k)]
        out.setdefault(f"RULE {r['effect']}", []).append(
            {"text": r.get("then_text") or r.get("target") or "", "texts": texts, "cond": _cond(r.get("condition"))})
    for ip in s.get("if_present", []):
        for n in ip["negatives"]:
            out.setdefault("IF_PRESENT", []).append({"text": n["text"], "finding": ip["finding"]})
    term = s.get("terminology") or {}
    for t in term.get("preferred", []) + term.get("suppressed", []):
        out.setdefault("TERM", []).append({"text": t})
    return out


def _pair_score(kind: str, k: Dict, u: Dict) -> float:
    if kind == "TERM":
        return 1.0 if k["text"].strip().lower() == u["text"].strip().lower() else 0.0
    if kind.startswith("RULE"):
        cond = sim(k["cond"], u["cond"])
        text = max([sim(a, b) for a in k["texts"] for b in u["texts"]] or [0.0])
        has_text = bool(k["texts"] and u["texts"])
        if has_text:
            return (cond + text) / 2 if (cond >= COND_MATCH or text >= TEXT_MATCH) else 0.0
        return cond if cond >= COND_MATCH else 0.0
    s = sim(k["text"], u["text"])
    return s if s >= TEXT_MATCH else 0.0


def _match(kind: str, keys: List[Dict], units: List[Dict]) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """Greedy best-first one-to-one matching; returns (pairs, unmatched key idx, unmatched unit idx)."""
    cands = sorted(((_pair_score(kind, k, u), i, j) for i, k in enumerate(keys) for j, u in enumerate(units)),
                   reverse=True)
    used_k, used_u, pairs = set(), set(), []
    for sc, i, j in cands:
        if sc <= 0:
            break
        if i in used_k or j in used_u:
            continue
        used_k.add(i), used_u.add(j), pairs.append((i, j))
    return pairs, [i for i in range(len(keys)) if i not in used_k], [j for j in range(len(units)) if j not in used_u]


def score(structure: Dict, key: Dict) -> Dict:
    kus, sus = _key_units(key), _sheet_units(structure)
    all_sheet_texts = [u["text"] for us in sus.values() for u in us]
    per_kind: Dict[str, Dict] = {}
    misses, spurious = [], []
    for kind in sorted(set(kus) | set(sus)):
        keys, units = kus.get(kind, []), sus.get(kind, [])
        pairs, mk, mu = _match(kind, keys, units)
        per_kind[kind] = {"planted": len(keys), "emitted": len(units), "matched": len(pairs),
                          "recall": round(len(pairs) / len(keys), 2) if keys else None,
                          "precision": round(len(pairs) / len(units), 2) if units else None}
        for i in mk:
            k = keys[i]
            cross = kind in ("NEGATIVE", "NORMAL", "FIXED", "IF_PRESENT") and any(
                sim(k["text"], t) >= 0.8 for t in all_sheet_texts)
            misses.append({"id": k["id"], "kind": kind, "cross_kind": cross, "grammar": k.get("grammar") or k["text"]})
        for j in mu:
            spurious.append({"kind": kind, "text": units[j]["text"],
                             **({"cond": units[j]["cond"]} if "cond" in units[j] else {})})
    secs_key = [(s["name"], s.get("header")) for s in key.get("sections", [])]
    secs_sheet = [(s["name"], s.get("header")) for s in structure.get("sections", [])]
    norm = lambda x: re.sub(r"[^a-z]", "", (x or "").lower())  # noqa: E731
    found = [n for n, h in secs_key if any(norm(n) == norm(m) or (h and norm(h) == norm(g)) for m, g in secs_sheet)]
    per_kind["SECTION"] = {"planted": len(secs_key), "emitted": len(secs_sheet), "matched": len(found),
                           "recall": round(len(found) / len(secs_key), 2) if secs_key else None,
                           "precision": round(len(found) / len(secs_sheet), 2) if secs_sheet else None}
    planted = sum(v["planted"] for k, v in per_kind.items() if k != "SECTION")
    matched = sum(v["matched"] for k, v in per_kind.items() if k != "SECTION")
    return {"per_kind": per_kind, "units_recall": round(matched / planted, 2) if planted else None,
            "misses": misses, "spurious": spurious}
