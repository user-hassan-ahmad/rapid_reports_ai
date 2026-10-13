// Copilot card state as pure functions: which findings are ready to match, when to call /match, how cards group
// under their findings, and which cards stay quiet. No I/O here; the rail components own requests.
import { effectiveItems } from '$lib/hybrid-stack/regionState';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { MAX_FINDINGS } from './api';
import type { Card, DraftValue, Preview } from './types';

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
 *  is no longer dictated are dropped (a deleted finding takes its cards, copilot spec §4.1). Groups are keyed by
 *  finding id: a card goes to the finding with its own id when the text still matches, else to the first finding
 *  with its text (renumbered units), so two findings with identical text stay separate groups. A card with no
 *  finding text (non-library) goes by finding_id only. Within a group, duplicate cards (same cardRef) show once. */
export function groupCards(cards: Card[], findings: Finding[]): Group[] {
	const exam: Card[] = [];
	const byId = new Map<string, Card[]>();
	const seen = new Set<string>();
	const put = (id: string, list: Card[], c: Card) => {
		const ref = `${id}|${cardRef(c)}`;
		if (seen.has(ref)) return;
		seen.add(ref);
		list.push(c);
	};
	for (const c of cards) {
		if (c.finding_id === 'exam') {
			put('exam', exam, c);
			continue;
		}
		const text = norm(c.finding);
		const home = c.finding
			? (findings.find((f) => f.id === c.finding_id && norm(f.text) === text) ?? findings.find((f) => norm(f.text) === text))
			: findings.find((f) => f.id === c.finding_id);
		if (!home) continue;
		if (!byId.has(home.id)) byId.set(home.id, []);
		put(home.id, byId.get(home.id)!, c);
	}
	const groups: Group[] = exam.length ? [{ finding: null, cards: exam }] : [];
	for (const f of findings) {
		const mine = byId.get(f.id);
		if (mine?.length) groups.push({ finding: f, cards: mine });
	}
	return groups;
}

/** The outcome the card shows, read-only: Task 3's draft_outcome, else today's proposal (never Applied). */
export const outcomeOf = (p: Preview | null) => p?.draft_outcome ?? p?.proposal ?? null;

/** §5.3 quiet one-line card: an exam card whose preview applies, needs nothing, is not degraded, has no pre-filled
 *  value other than the exam's own presets (a value set by the exam keeps the line quiet and shows "set by the
 *  exam"), and whose outcome is normal. When the backend sends Proposal.normal (R3) it decides "normal"; otherwise
 *  the interim rule (plan Q2) takes any reached outcome. */
export function quiet(c: Card, p: Preview | null): boolean {
	if (c.finding_id !== 'exam' || !p) return false;
	const outcome = outcomeOf(p);
	if (p.state !== 'applies' || p.degraded || p.missing.length || !outcome) return false;
	if (outcome.normal !== undefined && !outcome.normal) return false;
	return !(p.draft ?? []).some((v) => v.state === 'prefilled' && v.by !== 'exam');
}

export interface DraftRows { values: DraftValue[]; assumed: DraftValue[]; asked: DraftValue[] }
const SHOWN_AS_VALUE = new Set(['read', 'prefilled', 'answered', 'edited', 'not_applicable']);
/** The draft card's rows by section (Slice B1, §7.5), waiting rows hidden (behind a prerequisite still unknown):
 *  values (read, pre-filled, answered, edited, N/A) in pack order; assumed eligibility inputs (under the warning
 *  chip); asked ("Still open"): eligibility first while the card is check_first, then the inputs that can still
 *  change the outcome (`needed`), each group in pack order. */
export function rowsOf(p: Preview | null): DraftRows {
	const shown = (p?.draft ?? []).filter((v) => !v.waiting);
	const rank = (v: DraftValue) => (p?.state === 'check_first' && v.role === 'eligibility' ? 0 : 2) + (v.needed ? 0 : 1);
	return {
		// a state this UI does not know yet shows as a plain value rather than vanishing
		values: shown.filter((v) => SHOWN_AS_VALUE.has(v.state) || !['assumed', 'asked'].includes(v.state)),
		assumed: shown.filter((v) => v.state === 'assumed'),
		asked: shown
			.map((v, i) => ({ v, i }))
			.filter(({ v }) => v.state === 'asked')
			.sort((a, b) => rank(a.v) - rank(b.v) || a.i - b.i)
			.map(({ v }) => v)
	};
}

export const modalityLabel = (m: string) =>
	(({ US: 'ultrasound', CT: 'CT', MRI: 'MRI', XR: 'a radiograph' }) as Record<string, string>)[m] ?? m;
