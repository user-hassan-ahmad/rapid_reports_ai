# Plan — Jev word-sense spotter + fixer (lab, 2026-09-27)

**Why:** real-word mishearings ("renal glands" for adrenal, "supplemental emboli", "nipple effusion", "common bowel duct", "a high lesion") pass every polish: an eval of 3 prompts × 3 runs fixed at most 23/33, never those three, and pushing the prompt reworded clean lines. A Jev probe, one noul per word ("makes clinical sense as heard"), put the misheard word (or its neighbour) lowest in all six misheard sentences (0.06–0.59) and every word of two clean controls ≥ 0.73. Rev 2 §6.2 pattern A: code proposes, Jev chooses, "as heard" always an option. Step 11 of the work order, brought forward for the lab.

Lab only (decision-first front door, `RR_TRIAGE_DEBUG=1`); production unchanged.

## Design

1. **Spot (same call):** the bundle adds `word_sense_<i>` nouls for up to 12 content words of the latest utterance. Flag below `word_sense_flag` (provisional 0.6).
2. **Candidates (code):** for each flagged word, windows of 1–3 words around it are compared with a lexicon (checklist sections + keyterms + a broad radiology list) by a phonetic-key and letter similarity; top candidates above a cut become whole-sentence variants.
3. **Choose (chained Jev call, only when there are candidates):** a Choice over {as_heard, variant_1…}. Accept a variant at confidence ≥ `word_fix_accept` (provisional 0.8); otherwise the word stays and is flagged.
4. **Apply (code):** `/bundle` returns `asr_fixes` [{heard, replacement, confidence}] and `asr_flags` [{word, score}]; fast-append text is fixed before it is written; the lean polish's insert gets the same substitution when the heard phrase is still present verbatim. Flags are underlined in the scratchpad.
5. **Log data only:** counts, scores, chosen index, confidence; never words.

## Tasks (TDD, one commit each)

1. Registry: word-sense question, choice wording, `word_sense_flag` / `word_fix_accept`, QSET `2026-09-27.2`.
2. `asr_repair.py`: content-word selection, lexicon, phonetic candidates (tests: the lab's misheard lines).
3. Bundle + `/bundle`: word-sense answers, chained choice, fixes/flags in the response and the log.
4. Offline eval on the labelled lab finals (live Jev): misheard caught / fixed / flagged, clean flagged / wrongly changed, latency; thresholds checked before the frontend.
5. Scratchpad: apply fixes to fast-append and lean text, underline flags, record counts; panel shows them.
6. Docs.
