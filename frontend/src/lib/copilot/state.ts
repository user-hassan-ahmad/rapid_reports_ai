// Copilot card state as pure functions: which findings are ready to match, when to call /match, how cards group
// under their findings, and which cards stay quiet. No I/O here; the rail components own requests.
import { effectiveItems } from '$lib/hybrid-stack/regionState';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { MAX_FINDINGS } from './api';
import type { Card, Preview } from './types';

export interface Finding { id: string; unitId: number; text: string; region: string }
export const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.;,]$/, '');

/** Abnormal, placed findings in dictation order, ids as the matcher expects ("u<id>" / "u<id>.<part>"),
 *  from effectiveItems (hybrid-stack/regionState). */
export function abnormalFindings(units: StackUnit[]): Finding[] {
	return effectiveItems(units)
		.filter((i) => i.abnormal)
		.map((i) => ({ id: i.part === null ? `u${i.unitId}` : `u${i.unitId}.${i.part}`, unitId: i.unitId, text: i.text, region: i.group }));
}

/** A finding is ready to match once its text did not change across a grouping round, or the radiologist has
 *  moved on (a later placed unit exists), or dictation is not running (stopped or paused: plan Q4). */
export function stableFindings(prev: Map<string, string>, now: Finding[], lastUnitId: number, recording: boolean): Finding[] {
	return now.filter((f) => !recording || prev.get(f.id) === f.text || f.unitId < lastUnitId);
}

export interface MatchPlan { call: boolean; findings: Finding[]; reason: 'new_text' | 'context' | 'exam' | 'none' }

/** Call /match when a stable finding's normalised text has not been sent under this context (scan type +
 *  history), or when no call has yet been made for this context and the dictation has placed text (exam cards
 *  bind with no abnormal finding). The body always carries ALL stable findings (≤ 20, dictation order): the server
 *  applies case-level caps and the one-TNM-per-site rule, and caches each unit, so unchanged findings cost nothing.
 *  `sent` holds normalised texts sent under `sentCtx`; a new context ignores it (the caller clears it on call). */
export function planMatch(sent: Set<string>, ctx: string, sentCtx: string | null, stable: Finding[], hasText: boolean): MatchPlan {
	const findings = stable.slice(0, MAX_FINDINGS);
	const none: MatchPlan = { call: false, findings, reason: 'none' };
	if (sentCtx !== ctx) {
		if (!hasText && !findings.length) return none;
		const reason = sentCtx !== null ? 'context' : findings.length ? 'new_text' : 'exam';
		return { call: true, findings, reason };
	}
	return findings.some((f) => !sent.has(norm(f.text))) ? { call: true, findings, reason: 'new_text' } : none;
}

/** Record what a /match call carried, so planMatch skips it next round. */
export function markSent(sent: Set<string>, findings: Finding[]): Set<string> {
	for (const f of findings) sent.add(norm(f.text));
	return sent;
}

/** Card identity that survives unit renumbering: key + "exam" or the normalised finding text. */
export const cardRef = (c: Card) => `${c.key}|${c.finding_id === 'exam' ? 'exam' : norm(c.finding)}`;

export type CardKind = 'exam' | 'finding' | 'tnm' | 'needs_modality' | 'reference' | 'other';
export function kindOf(c: Card, fromOther = false): CardKind {
	if (c.needs_modality) return 'needs_modality';
	if (c.reference) return 'reference';
	if (c.key.startsWith('tnm-')) return 'tnm';
	if (c.finding_id === 'exam') return 'exam';
	if (fromOther) return 'other';
	return 'finding';
}

export interface Group { finding: Finding | null; cards: Card[] } // null: the exam group

/** Exam cards first, then one group per current finding (with cards) in dictation order; cards whose finding text
 *  is no longer dictated are dropped (a deleted finding takes its cards, copilot spec §4.1). A card with no
 *  finding text (non-library) falls back to its finding_id. Duplicate cards (same cardRef) show once. */
export function groupCards(cards: Card[], findings: Finding[]): Group[] {
	const seen = new Set<string>();
	const unique = cards.filter((c) => !seen.has(cardRef(c)) && !!seen.add(cardRef(c)));
	const exam = unique.filter((c) => c.finding_id === 'exam');
	const rest = unique.filter((c) => c.finding_id !== 'exam');
	const used = new Set<Card>();
	const groups: Group[] = exam.length ? [{ finding: null, cards: exam }] : [];
	for (const f of findings) {
		const key = norm(f.text);
		const mine = rest.filter((c) => !used.has(c) && (c.finding ? norm(c.finding) === key : c.finding_id === f.id));
		mine.forEach((c) => used.add(c));
		if (mine.length) groups.push({ finding: f, cards: mine });
	}
	return groups;
}

/** The outcome the card shows, read-only: Task 3's draft_outcome, else today's proposal (never Applied). */
export const outcomeOf = (p: Preview | null) => p?.draft_outcome ?? p?.proposal ?? null;

/** §5.3 quiet one-line card. Interim rule until contract request R3 (plan Q2): an exam card whose preview applies,
 *  reached an outcome, needs nothing, is not degraded, and has no pre-filled value. */
export function quiet(c: Card, p: Preview | null): boolean {
	if (c.finding_id !== 'exam' || !p) return false;
	if (p.state !== 'applies' || p.degraded || p.missing.length || !outcomeOf(p)) return false;
	const prefilled = p.settled.some((s) => s.by === 'exam') || (p.draft ?? []).some((v) => v.state === 'prefilled' || v.by === 'exam');
	return !prefilled;
}

export const modalityLabel = (m: string) =>
	(({ US: 'ultrasound', CT: 'CT', MRI: 'MRI', XR: 'a radiograph' }) as Record<string, string>)[m] ?? m;
