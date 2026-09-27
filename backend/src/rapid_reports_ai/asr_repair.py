"""Real-word mishearing repair: code proposes sound-alike candidates, Jev chooses.

Rev 2 §6.2 pattern A. Jev spots a word that makes no clinical sense as heard (word-sense
noul in the bundle); this module finds candidates for it in the case's vocabulary
(checklist sections, keyterms, a broad radiology list) by comparing 1–3 word windows
around the flagged word with a phonetic key and letter similarity. The chosen candidate
is applied as a plain substitution, so nothing else in the sentence changes.

Plan: docs/superpowers/plans/2026-09-27-jev-word-sense-spotter-fixer.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .deepgram_spelling import UK_SPELLING

_STOP = set("""a an the of in on at to for from by with without and or but is are was were be been being there this
that these those it its as into onto over under than then also which who whose any some no not nor very
measuring measures measured measure seen noted demonstrated identified present shows show""".split())
_UNITS = set("mm cm mls ml millimetre millimetres millimeter millimeters centimetre centimetres centimeter centimeters".split())

# Broad radiology vocabulary across body systems and modalities (anatomy, descriptors,
# pathology). Checklist sections and keyterms are added per case.
RADIOLOGY_TERMS = """
adrenal glands, adrenal, kidneys, kidney, renal, ureter, bladder, prostate, uterus, ovary, ovaries, adnexa,
liver, hepatic, gallbladder, biliary, common bile duct, bile duct, bile, pancreas, pancreatic duct, ampulla, spleen,
portal vein, hepatic veins, inferior vena cava, aorta, abdominal aorta, iliac, mesenteric, mesentery, peritoneum,
retroperitoneum, omentum, appendix, caecum, colon, sigmoid, rectum, duodenum, jejunum, ileum, terminal ileum, stomach,
oesophagus, hiatus hernia, umbilical hernia, inguinal hernia, lymph nodes, lymphadenopathy, ascites, free fluid,
lungs, lobe, lingula, upper lobe, lower lobe, middle lobe, pleura, pleural, pleural effusion, pericardial,
pericardial effusion, mediastinum, mediastinal, hilar, trachea, bronchi, bronchus, bronchiectasis, emphysema,
centrilobular, paraseptal, consolidation, atelectasis, ground-glass, nodule, nodules, mass, lesion, cyst, cystic,
solid, calcified, calcification, spiculated, cavitating, pulmonary arteries, pulmonary artery, segmental,
subsegmental, lobar, embolus, emboli, embolism, thrombus, infarct, right ventricle, left ventricle,
interventricular septum, heart, cardiomegaly, thyroid, thyroid nodule, parotid, submandibular, salivary gland,
brain, parenchyma, cerebral, cerebellar, frontal, parietal, temporal, occipital, sulci, gyri, ventricles,
cisterns, basal cisterns, midline shift, mass effect, effacement, herniation, uncal, tonsillar, extra-axial,
intra-axial, subdural, extradural, subarachnoid, intraparenchymal, haemorrhage, haematoma, oedema, vasogenic,
periventricular, white matter, small vessel, ischaemic, ischaemia, infarction, skull, skull vault, vault, scalp,
sylvian fissure, sinuses, orbits, mastoid, vertebrae, vertebral body, disc, discs, disc bulge, disc protrusion,
disc extrusion, desiccation, paracentral, foraminal, foraminal stenosis, subarticular, lateral recess, canal,
canal stenosis, facet joint, nerve root, traversing, exiting, conus, cauda equina, thecal sac, paraspinal,
sacroiliac, spondylolisthesis, spondylosis, osteophyte, fracture, sclerosis, sclerotic, lytic, marrow, cortex,
cortical, acetabulum, femoral head, joint effusion, meniscus, ligament, tendon, cartilage, hypodense, hyperdense,
isodense, hypoattenuating, hyperattenuating, hypoechoic, hyperechoic, enhancing, enhancement, non-enhancing,
arterially enhancing, washout, steatosis, cirrhosis, splenomegaly, hepatomegaly, hydronephrosis, hydroureter,
calculus, calculi, stone, cholelithiasis, choledocholithiasis, cholecystitis, appendicitis, appendicolith,
diverticulosis, diverticulitis, pneumothorax, pneumoperitoneum, collection, abscess, wall thickening, stranding,
fat stranding, effusion, dilated, dilatation, stenosis, occlusion, patent, aneurysm, dissection
"""


def _terms(text: str) -> list[str]:
    return [t.strip().lower() for t in text.replace("\n", " ").split(",") if t.strip()]


def build_lexicon(checklist: list[str] | tuple[str, ...] = (), extra: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Case vocabulary: checklist sections (as phrases), extra terms (keyterms), the broad
    radiology list and British spellings. Lowercase, de-duplicated, order kept."""
    seen: dict[str, None] = {}
    for t in [*(s.lower() for s in checklist), *(e.lower() for e in extra), *_terms(RADIOLOGY_TERMS),
              *UK_SPELLING.values()]:
        t = re.sub(r"\s+", " ", t.strip())
        if t:
            seen.setdefault(t, None)
    return list(seen)


_TOKEN = re.compile(r"[A-Za-z][A-Za-z'-]*")


def content_words(utterance: str, cap: int = 12) -> list[tuple[str, int, int]]:
    """Words worth asking about: letters only, ≥ 3 characters, not function words or units."""
    out = []
    for m in _TOKEN.finditer(utterance or ""):
        w = m.group(0)
        if len(w) < 3 or w.lower() in _STOP or w.lower() in _UNITS:
            continue
        out.append((w, m.start(), m.end()))
        if len(out) >= cap:
            break
    return out


def phonetic_key(word: str) -> str:
    """A rough English sound key: spellings that sound alike map close together."""
    s = re.sub(r"[^a-z]", "", word.lower())
    for a, b in (("ph", "f"), ("ck", "k"), ("qu", "kw"), ("x", "ks"), ("dg", "j"), ("gh", "g"), ("wh", "w"),
                 ("sch", "sk"), ("th", "t"), ("ae", "e"), ("oe", "e")):
        s = s.replace(a, b)
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = s.replace("c", "k").replace("z", "s").replace("v", "f").replace("b", "p").replace("d", "t").replace("g", "k")
    if not s:
        return ""
    head, rest = s[0], re.sub(r"[aeiouy]", "", s[1:])
    return re.sub(r"(.)\1+", r"\1", head + rest)


def similarity(a: str, b: str) -> float:
    a, b = a.lower(), b.lower()
    ka, kb = phonetic_key(a), phonetic_key(b)
    return 0.5 * SequenceMatcher(None, ka, kb).ratio() + 0.5 * SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class Candidate:
    start: int  # character span in the utterance of the heard text
    end: int
    heard: str
    replacement: str
    score: float


def _stem(w: str) -> str:
    return re.sub(r"e$", "", re.sub(r"(es|s)$", "", w.lower()))


def candidates(utterance: str, flagged: str, lexicon: list[str], k: int = 5, cut: float = 0.62) -> list[Candidate]:
    """Sound-alike replacements for the flagged word, considering 1–3 word windows around it,
    best first. A replacement that is only an inflection of the heard words is not offered."""
    toks = [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(utterance or "")]
    idx = [i for i, t in enumerate(toks) if t[0] == flagged]
    if not idx:
        return []
    i = idx[0]
    windows = {(a, b) for a in range(max(0, i - 2), i + 1) for b in range(i, min(len(toks), i + 3)) if b - a <= 2}
    best: dict[str, Candidate] = {}
    for a, b in windows:
        if toks[a][0].lower() in _STOP or toks[b][0].lower() in _STOP:
            continue  # a window never starts or ends on a function word ('the renal' → 'adrenal')
        start, end = toks[a][1], toks[b][2]
        heard = utterance[start:end]
        n = b - a + 1
        terms = lexicon
        # Deepgram merges a negation into the next word ('no pleural' → 'nipple'): when the
        # heard word starts with an n-sound, the negated form is offered too, so a fix can
        # never silently turn a normal finding into a positive one.
        if phonetic_key(heard).startswith("n"):
            terms = lexicon + [f"no {t}" for t in lexicon if not t.startswith("n")]
        for term in terms:
            tn = term.count(" ") + 1
            if abs(tn - n) > 1 or term == heard.lower():
                continue
            if " ".join(_stem(w) for w in term.split()) == " ".join(_stem(w) for w in heard.lower().split()):
                continue
            # the flagged word itself must change; unchanged neighbours are trimmed off
            sc = similarity(heard, term)
            if sc < cut:
                continue
            h_words, t_words = heard.split(), term.split()
            while len(h_words) > 1 and len(t_words) > 1 and h_words[0].lower() == t_words[0]:
                h_words, t_words = h_words[1:], t_words[1:]
            while len(h_words) > 1 and len(t_words) > 1 and h_words[-1].lower() == t_words[-1]:
                h_words, t_words = h_words[:-1], t_words[:-1]
            h, t = " ".join(h_words), " ".join(t_words)
            if h.lower() == t or {_stem(w) for w in t.split()} <= {_stem(w) for w in h_words}:
                continue  # unchanged, or only deletes a heard word: not a fix
            if len(t_words) < len(h_words):
                continue  # a fix replaces words; it never drops one ('common bowel' → 'bile')
            hs = utterance.find(h, start)
            c = Candidate(hs, hs + len(h), h, t, sc)
            words_after = apply_fix(utterance, c).lower().split()
            if any(x == y for x, y in zip(words_after, words_after[1:])):
                continue  # 'bowel' → 'bile duct' next to 'duct' would read 'bile duct duct'
            key = f"{h.lower()}→{t}"
            if key not in best or best[key].score < sc:
                best[key] = c
    return sorted(best.values(), key=lambda c: -c.score)[:k]


def apply_fix(utterance: str, c: Candidate) -> str:
    rep = c.replacement
    if c.heard[:1].isupper():
        rep = rep[:1].upper() + rep[1:]
    return utterance[: c.start] + rep + utterance[c.end:]


# --- the chained choice ------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairResult:
    text: str
    fixes: list[dict]  # {heard, replacement, confidence}
    flags: list[dict]  # {word, score}: flagged and not fixed
    asked: int  # flagged words that had candidates (one Jev question each)
    latency_ms: int | None
    error: str | None


def _find_word(sentence: str, word: str) -> str | None:
    """The flagged word as it appears in the (cleaned) sentence, matching case-insensitively."""
    for m in _TOKEN.finditer(sentence):
        if m.group(0).lower() == word.lower():
            return m.group(0)
    return None


async def repair(
    sentence: str,
    word_sense: tuple[tuple[str, float], ...],
    *,
    state: dict,
    lexicon: list[str],
    api_key: str,
    transport=None,
    max_words: int = 2,
) -> RepairResult:
    """Flag words below the word-sense band; for those with sound-alike candidates, one Jev
    choice per word over whole sentences ("as heard" always included); apply a candidate
    only at or above the fix band. Everything else stays as heard and is flagged."""
    import time

    import httpx

    from .jev_client import JEV_MODEL, jev_post
    from .jev_questions import WORD_SENSE_BANDS, word_fix_question

    flagged = sorted((ws for ws in word_sense if ws[1] < WORD_SENSE_BANDS["word_sense_flag"]), key=lambda x: x[1])
    flagged = flagged[:max_words]
    if not flagged:
        return RepairResult(sentence, [], [], 0, None, None)
    questions, options_by_q = {}, {}
    for j, (w, _score) in enumerate(flagged):
        found = _find_word(sentence, w)
        cands = candidates(sentence, found, lexicon) if found else []
        options: dict[str, str] = {"as_heard": sentence}
        by_option: dict[str, Candidate] = {}
        for c in cands:
            v = apply_fix(sentence, c)
            if v in options.values():
                continue  # same sentence as an option already offered
            key = f"candidate_{len(by_option)}"
            options[key] = v
            by_option[key] = c
        if by_option:
            questions[f"fix_{j}"] = word_fix_question(options)
            options_by_q[f"fix_{j}"] = by_option
    flags = [{"word": w, "score": s} for w, s in flagged]
    if not questions:
        return RepairResult(sentence, [], flags, 0, None, None)
    body = {"model": JEV_MODEL, "state": {**state, "latest_utterance": sentence}, "questions": questions}
    t0 = time.perf_counter()
    try:
        resp = await jev_post(body, api_key, 3.0, transport)
        resp.raise_for_status()
        answers = resp.json().get("answers") or {}
    except (httpx.HTTPError, ValueError) as e:
        return RepairResult(sentence, [], flags, len(questions), int((time.perf_counter() - t0) * 1000), type(e).__name__)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    chosen: list[tuple[Candidate, float]] = []
    fixed_words = set()
    for q, opts in options_by_q.items():
        a = answers.get(q) or {}
        choice, conf = a.get("choice"), a.get("confidence") or 0.0
        if choice in opts and conf >= WORD_SENSE_BANDS["word_fix_accept"]:
            chosen.append((opts[choice], conf))
            fixed_words.add(flagged[int(q.split("_")[1])][0])
    text, last_start = sentence, len(sentence) + 1
    applied = []
    for c, conf in sorted(chosen, key=lambda x: -x[0].start):
        if c.end > last_start:
            continue  # overlaps a fix already applied to its right
        text = apply_fix(text, c)
        last_start = c.start
        applied.append({"heard": c.heard, "replacement": c.replacement, "confidence": conf})
    return RepairResult(text, applied, [f for f in flags if f["word"] not in fixed_words], len(questions), latency_ms, None)
