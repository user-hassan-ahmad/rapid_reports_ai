"""British spelling for Deepgram transcripts, via Deepgram's own find-and-replace.

Deepgram's English models always return American spelling, with language=en-GB too
(docs: "Models and Languages > English Dialect Spelling"). Its `replace=find:replacement`
query parameter works on the streaming websocket (checked live 2026-09-26) and is the
supported way to change that. Whole words only, so 'hemi-' words (hemidiaphragm) are
untouched by construction.

Replace inserts the replacement as written, so a sentence-initial 'Hematoma' comes back
'haematoma'; restore_sentence_case puts the capital back after . ? ! within a final.
Enabled by DEEPGRAM_UK_SPELLING=1 (main.websocket_transcribe); off by default.
"""
from __future__ import annotations

import re

# US → UK, lowercase find terms (Deepgram requires it). Radiology vocabulary first.
UK_SPELLING: dict[str, str] = {
    # haem-
    "hematoma": "haematoma", "hematomas": "haematomas",
    "hemorrhage": "haemorrhage", "hemorrhages": "haemorrhages", "hemorrhagic": "haemorrhagic",
    "hemoperitoneum": "haemoperitoneum", "hemothorax": "haemothorax",
    "hemopericardium": "haemopericardium", "hemarthrosis": "haemarthrosis",
    "hemangioma": "haemangioma", "hemangiomas": "haemangiomas",
    "hemosiderin": "haemosiderin", "hematuria": "haematuria", "hemoptysis": "haemoptysis",
    "hemodynamically": "haemodynamically", "hemoglobin": "haemoglobin",
    # oe- / ae-
    "edema": "oedema", "edematous": "oedematous",
    "esophagus": "oesophagus", "esophageal": "oesophageal", "estrogen": "oestrogen",
    "ischemia": "ischaemia", "ischemic": "ischaemic",
    "anemia": "anaemia", "leukemia": "leukaemia", "diarrhea": "diarrhoea",
    "feces": "faeces", "fecal": "faecal", "cesarean": "caesarean",
    "anesthesia": "anaesthesia", "pediatric": "paediatric", "orthopedic": "orthopaedic",
    "gynecological": "gynaecological", "gynecology": "gynaecology",
    # -re / -our
    "caliber": "calibre", "center": "centre", "centers": "centres",
    "millimeter": "millimetre", "millimeters": "millimetres",
    "centimeter": "centimetre", "centimeters": "centimetres",
    "tumor": "tumour", "tumors": "tumours", "color": "colour",
    "behavior": "behaviour", "favor": "favour", "favored": "favoured",
    "gray": "grey",
    # -ise
    "organized": "organised", "localized": "localised", "generalized": "generalised",
    "visualized": "visualised", "visualize": "visualise", "characterized": "characterised",
    "characterize": "characterise", "recognized": "recognised", "catheterized": "catheterised",
    # -ll-
    "labeled": "labelled", "labeling": "labelling",
}


def uk_spelling_params() -> str:
    """The query-string fragment for the Deepgram websocket URL."""
    return "&".join(f"replace={us}:{uk}" for us, uk in UK_SPELLING.items())


_AFTER_STOP = re.compile(
    r"([.?!]\s+)(" + "|".join(re.escape(uk) for uk in sorted(set(UK_SPELLING.values()), key=len, reverse=True)) + r")\b"
)


def restore_sentence_case(text: str) -> str:
    """Capitalise a replaced word that starts a sentence inside the final."""
    return _AFTER_STOP.sub(lambda m: m.group(1) + m.group(2)[0].upper() + m.group(2)[1:], text or "")
