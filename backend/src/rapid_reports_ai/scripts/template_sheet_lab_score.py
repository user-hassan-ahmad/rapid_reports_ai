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
    """Content words, crudely stemmed to five letters (appendix/appendiceal, abnormal/abnormality)."""
    text = re.sub(r"\{[^}]*\}", " ", text or "").lower()
    return {w[:5] for w in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text) if w not in _STOP and len(w) > 1}


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


_STUDY = re.compile(r"\bnot (?:performed|acquired|given|obtained|done)\b|\bprotocol\b|\bprior\b|\bprevious\b|"
                    r"\bcomparison\b|\bacquisition\b|\bphase\b|\bsequences?\b", re.I)


def is_intrinsic(p: Dict) -> bool:
    """A planted unit the LEAN template sheet should carry (spec 2026-10-01 two-phase): NORMAL, routine
    NEGATIVE, FIXED, TERM, LIST_MISSING, and study/context rules. Findings- or history-conditioned rules,
    conditional negatives and IF_PRESENT are Phase 1's. A rule counts as a study rule when its source is
    context, its effect is section/header suppression, or its statement is about what was performed
    (some keys label those findings: "... was not performed")."""
    kind, cond = p["kind"], p.get("condition")
    src = cond.get("source") if isinstance(cond, dict) else None
    statement = cond.get("statement", "") if isinstance(cond, dict) else (cond or "")
    if kind == "IF_PRESENT":
        return False
    if kind == "NEGATIVE":
        return src in (None, "context")
    if kind == "RULE":
        return (p.get("effect") in ("list_missing", "suppress_section", "suppress_headers") or src == "context"
                or bool(_STUDY.search(statement)))
    return True


def _key_units(key: Dict, intrinsic_only: bool = False) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for p in key["planted"]:
        if intrinsic_only and not is_intrinsic(p):
            continue
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
            {"text": r.get("then_text") or r.get("target") or "", "texts": texts, "cond": _cond(r.get("condition")),
             "rid": r["id"]})
    for ip in s.get("if_present", []):
        for n in ip["negatives"]:
            out.setdefault("IF_PRESENT", []).append({"text": n["text"], "finding": ip["finding"]})
    term = s.get("terminology") or {}
    for t in term.get("preferred", []) + term.get("suppressed", []):
        out.setdefault("TERM", []).append({"text": t})
    return out


def _pair_score(kind: str, k: Dict, u: Dict) -> float:
    if kind == "PARAGRAPH":
        a, b = (re.sub(r"[^a-z]", "", x["text"].lower()) for x in (k, u))
        return 1.0 if a and b and (a == b or a in b or b in a) else (sim(k["text"], u["text"]) if
                                                                    sim(k["text"], u["text"]) >= TEXT_MATCH else 0.0)
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


def score(structure: Dict, key: Dict, intrinsic_only: bool = False) -> Dict:
    kus, sus = _key_units(key, intrinsic_only), _sheet_units(structure)
    all_sheet_texts = [u["text"] for us in sus.values() for u in us]
    per_kind: Dict[str, Dict] = {}
    misses, spurious, rule_map = [], [], {}
    for kind in sorted(set(kus) | set(sus)):
        keys, units = kus.get(kind, []), sus.get(kind, [])
        pairs, mk, mu = _match(kind, keys, units)
        if kind.startswith("RULE"):
            rule_map.update({keys[i]["id"]: units[j]["rid"] for i, j in pairs})
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
    paras_key = [p["name"] for p in key.get("paragraphs", [])]
    paras_sheet = [p["name"] for p in structure.get("paragraphs", [])]
    pp, _, _ = _match("PARAGRAPH", [{"text": n} for n in paras_key], [{"text": n} for n in paras_sheet])
    per_kind["PARAGRAPH"] = {"planted": len(paras_key), "emitted": len(paras_sheet), "matched": len(pp),
                             "recall": round(len(pp) / len(paras_key), 2) if paras_key else None,
                             "precision": round(len(pp) / len(paras_sheet), 2) if paras_sheet else None}
    planted = sum(v["planted"] for k, v in per_kind.items() if k not in ("SECTION", "PARAGRAPH"))
    matched = sum(v["matched"] for k, v in per_kind.items() if k not in ("SECTION", "PARAGRAPH"))
    return {"per_kind": per_kind, "units_recall": round(matched / planted, 2) if planted else None,
            "misses": misses, "spurious": spurious, "rule_map": rule_map}


_OMITTED_NEG = {"rule_omitted", "paragraph_suppressed", "removed", "section_omitted"}
_OMITTED_NORMAL = {"rule_omitted", "suppressed_by_rule", "do_not_assert", "section_omitted"}


def brief_accuracy(decisions: Dict, expected: Dict, rule_map: Dict[str, str], structure: Dict) -> Dict:
    """One dictation's brief decisions against the key's expected_per_dictation entry.

    - rules: each expected met / not-met planted rule, through rule_map to the generated rule; a planted
      rule with no generated counterpart is `unmapped` (a sheet miss, not a brief error).
    - omissions: each expected omitted text, matched by text to a generated negative or normal; correct
      when that unit was omitted or not asserted (for a negative, any OMIT / DO NOT ASSERT line for one
      of its parts counts). Generated omissions with no expected counterpart are listed as extra.
    - missing: LIST_MISSING items flagged as missing vs the expected missing items.
    """
    met_by_rid = {r["id"]: r.get("met") for r in decisions.get("rules", [])}
    rules: Dict = {"correct": 0, "wrong": [], "unmapped": []}
    for pid, want in [(p, True) for p in expected.get("rules_met", [])] + \
                     [(p, False) for p in expected.get("rules_not_met", [])]:
        rid = rule_map.get(pid)
        if rid is None or rid not in met_by_rid:
            rules["unmapped"].append(pid)
        elif bool(met_by_rid[rid]) == want:
            rules["correct"] += 1
        else:
            rules["wrong"].append({"planted": pid, "expected_met": want, "rule": rid})

    text_by_id = {n["id"]: n["text"] for n in structure.get("negatives", []) + structure.get("normals", [])}
    units = []
    for n in decisions.get("negatives", []):
        omitted = n["action"] in _OMITTED_NEG or any(
            ln.lstrip("- ").startswith(("OMIT", "DO NOT ASSERT")) for ln in n.get("lines", []))
        units.append({"text": n.get("text") or text_by_id.get(n["id"], ""), "omitted": omitted})
    for n in decisions.get("normals", []):
        units.append({"text": text_by_id.get(n["id"], ""), "omitted": n["action"] in _OMITTED_NORMAL})
    omissions: Dict = {"correct": 0, "not_omitted": [], "not_found": [], "extra": []}
    claimed = set()
    for text in expected.get("negatives_omitted", []):
        best = max(((sim(text, u["text"]), j) for j, u in enumerate(units)), default=(0.0, None))
        if best[0] < TEXT_MATCH:
            omissions["not_found"].append(text)
            continue
        claimed.add(best[1])
        if units[best[1]]["omitted"]:
            omissions["correct"] += 1
        else:
            omissions["not_omitted"].append(text)
    omissions["extra"] = [u["text"] for j, u in enumerate(units) if u["omitted"] and j not in claimed]

    flagged = [i for m in decisions.get("missing", []) for i in m.get("missing", [])]
    want = expected.get("missing_items", [])
    hit = [w for w in want if any(sim(w, f) >= TEXT_MATCH for f in flagged)]
    missing = {"expected": len(want), "found": len(hit),
               "extra": [f for f in flagged if not any(sim(w, f) >= TEXT_MATCH for w in want)]}
    return {"rules": rules, "omissions": omissions, "missing": missing}
