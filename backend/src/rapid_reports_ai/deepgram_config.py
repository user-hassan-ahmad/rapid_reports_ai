"""Deepgram live-transcription URL (nova-3-medical), in one tested place.

Docs audit 2026-09-27 (developers.deepgram.com): nova-3-medical supports en-GB and is the
current medical model (Flux targets voice agents, no medical variant). `numerals` turns
"segment seven" into "segment 7"; `smart_format` already enables punctuation, so
`punctuate` is not sent (commands verified live without it); `mip_opt_out=true` keeps
requests out of Deepgram's Model Improvement Program (approved by the product owner).
Keyterms: at most 500 tokens in total; Deepgram advises 20–50 focused terms.
"""
from __future__ import annotations

from urllib.parse import quote

from .deepgram_spelling import uk_spelling_params

# The generic core list (was inline in main.websocket_transcribe). Per-case keyterms
# (canvas /keyterms) are merged with a trimmed version of it.
CORE_KEYTERMS: tuple[str, ...] = (
    'spiculated',
    'appendicolith',
    'periappendiceal',
    'Bosniak',
    'hydronephrosis',
    'haemorrhage',
    'oedema',
    'atelectasis',
    'consolidation',
    'ground-glass opacity',
    'pneumothorax',
    'pleural effusion',
    'lymphadenopathy',
    'cardiomegaly',
    'hepatomegaly',
    'splenomegaly',
    'pericardial effusion',
    'aortic aneurysm',
    'dissection',
    'pulmonary embolism',
    'deep vein thrombosis',
    'mesenteric ischaemia',
    'cholecystitis',
    'choledocholithiasis',
    'pancreatitis',
    'appendicitis',
    'diverticulitis',
    'intussusception',
    'volvulus',
    'ileus',
    'pneumoperitoneum',
    'ascites',
    'retroperitoneal',
    'mediastinal',
    'hilar',
    'subphrenic',
    'interstitial',
    'parenchymal',
    'cortical',
    'corticomedullary',
    'nephrolithiasis',
    'ureterolithiasis',
    'hydroureter',
    'sacroiliitis',
    'spondylolisthesis',
    'spondylosis',
    'foraminal stenosis',
    'canal stenosis',
    'listhesis',
    'discitis',
    'vertebral body',
)


def keyterm_tokens(terms) -> int:
    """A conservative token estimate: one per word plus one per hyphen or slash."""
    return sum(len(t.split()) + t.count("-") + t.count("/") for t in terms)


def deepgram_listen_url(
    *,
    sample_rate: int | None,
    dictation: bool,
    keyterms=None,
    uk_spelling: bool = False,
) -> str:
    params = [
        ("model", "nova-3-medical"),
        ("language", "en-GB"),
        ("smart_format", "true"),
        ("measurements", "true"),
        ("numerals", "true"),
        ("dictation", "true" if dictation else "false"),
        ("interim_results", "true"),
        ("endpointing", "200"),
        ("utterance_end_ms", "1000"),
        ("mip_opt_out", "true"),
    ]
    if sample_rate is not None:
        params += [("encoding", "linear16"), ("sample_rate", str(sample_rate)), ("channels", "1")]
    params += [("keyterm", t) for t in (CORE_KEYTERMS if keyterms is None else keyterms)]
    url = "wss://api.deepgram.com/v1/listen?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in params)
    if uk_spelling:
        url += "&" + uk_spelling_params()
    return url
