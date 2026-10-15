// The questionnaire card (spec 2026-10-14 §4, §6): the values the radiologist must affirm (Check), the next question
// in the tree's order, the answers so far, and whether the card is ready to apply. Pure: from the preview, the card's
// answers (`edits`, "Not stated" = "Not known") and its ticks (input → the exact value affirmed; never sent).
import { NOT_STATED } from '../state';
import type { Ask, DraftValue, Preview, Proposal } from '../types';
import { assumptionsOf, scopeDoubts, shownValue } from './format';

export interface CheckItem { input: string; label: string; value: string; options: string[]; kind: 'prefilled' | 'assumed' | 'doubt'; basis: string; byExam: boolean; affirmed: boolean }
export interface Chip { input: string; label: string; value: string; options: string[]; basis: string }
export type Blocker = 'excluded' | 'question' | 'check' | 'pick' | 'incomplete' | null;

const GUESSED = new Set(['prefilled', 'assumed']);

/** Decisive (or unweighed) pre-filled and assumed values, and scope doubts, in pack order. A doubt is cleared only by
 *  an answer (Confirm or Change), never by a tick. */
export function checkItems(p: Preview | null | undefined, ticks: Record<string, string> = {}): CheckItem[] {
	if (!p?.draft?.length || p.state === 'does_not_apply') return [];
	const doubts = new Set(p.scope_doubt ?? []);
	const out: CheckItem[] = [];
	for (const d of p.draft) {
		const doubt = doubts.has(d.input);
		if (!doubt && !(GUESSED.has(d.state) && d.value && d.decisive !== false)) continue;
		out.push({
			input: d.input,
			label: d.label,
			value: d.value,
			options: d.options,
			kind: doubt ? 'doubt' : (d.state as 'prefilled' | 'assumed'),
			basis: d.basis ?? '',
			byExam: d.by === 'exam',
			affirmed: !doubt && ticks[d.input] === d.value
		});
	}
	return out;
}

/** The shown values not in Check (read, answered, edited, non-decisive guesses): the "Based on" line. */
export function basedOn(p: Preview | null | undefined, check: CheckItem[]): DraftValue[] {
	const inCheck = new Set(check.map((c) => c.input));
	return (p?.draft ?? []).filter((d) => !inCheck.has(d.input) && d.value && d.state !== 'asked' && d.state !== 'not_applicable');
}

const open = (p: Preview | null | undefined, edits: Record<string, string>): Ask[] =>
	!p || p.state === 'does_not_apply' ? [] : p.asks.filter((a) => edits[a.input] !== NOT_STATED);

/** The first question the engine still needs that was not answered "Not known" (asks come in the tree's order). */
export function nextAsk(p: Preview | null | undefined, edits: Record<string, string> = {}): Ask | null {
	return open(p, edits)[0] ?? null;
}
export function remaining(p: Preview | null | undefined, edits: Record<string, string> = {}): number {
	return open(p, edits).length;
}

/** Every answer the radiologist gave on this card, with the row's options (a chip tap changes it). */
export function answeredChips(p: Preview | null | undefined, edits: Record<string, string> = {}): Chip[] {
	const rows = new Map((p?.draft ?? []).map((d) => [d.input, d]));
	return Object.entries(edits)
		.filter(([k]) => rows.has(k))
		.map(([input, value]) => ({ input, label: rows.get(input)!.label, value, options: rows.get(input)!.options, basis: rows.get(input)!.basis ?? '' }));
}

/** What stops Apply, or null when ready (spec §6.3): one outcome (reached, or a picked candidate with a complete
 *  sentence) and every Check item affirmed. */
export function readiness(p: Preview | null | undefined, edits: Record<string, string> = {}, ticks: Record<string, string> = {}, pick: string | null = null): Blocker {
	if (!p) return 'question';
	if (p.state === 'does_not_apply') return 'excluded';
	const checked = checkItems(p, ticks).every((c) => c.affirmed);
	if (p.draft_outcome) return checked ? null : 'check';
	if (nextAsk(p, edits)) return 'question';
	const chosen = (p.candidates ?? []).find((c) => c.outcome === pick);
	if (!chosen) return 'pick';
	if (!chosen.proposal) return 'incomplete';
	return checked ? null : 'check';
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The status line under the head (spec §4.1); '' when ready, excluded or waiting on an incomplete pick. */
export function statusLine(p: Preview | null | undefined, edits: Record<string, string> = {}, ticks: Record<string, string> = {}, pick: string | null = null): string {
	const b = readiness(p, edits, ticks, pick);
	if (!p) return '';
	if (b === 'question') return `${p.bounded ? '' : 'up to '}${plural(remaining(p, edits), 'question', 'questions')} to a recommendation`;
	if (b === 'check') return `Check ${plural(checkItems(p, ticks).filter((c) => !c.affirmed).length, 'value', 'values')} to apply`;
	if (b === 'pick' && (p.candidates ?? []).length > 0) return 'Pick the outcome that fits';
	return '';
}

const tidy = (s: string) => s.trim().replace(/[\s.]+$/, '');
/** The line Apply writes (spec §7.2): "<classification>: <recommendation> (<source>)." */
export function sentenceOf(pr: Proposal, source: string): string {
	const i = pr.classification.indexOf(' · ');
	const head = tidy(i >= 0 ? pr.classification.slice(i + 3) : pr.classification);
	const rec = tidy(pr.recommendation || pr.action || '');
	const body = head && rec ? `${head}: ${rec}` : head || rec;
	return `${body.charAt(0).toUpperCase()}${body.slice(1)} (${source}).`;
}

/** A guideline that may not apply collapses to one row: it does not apply, or a pre-filled value would make it not. */
export const collapsible = (p: Preview | null | undefined): boolean => !!p && (p.state === 'does_not_apply' || (p.scope_doubt?.length ?? 0) > 0);

export interface CollapsedReason {
	kind: 'doubt' | 'excluded';
	input: string;
	label: string;
	value: string;
	options: string[];
	/** The fact in plain words (a boolean Yes reads as the statement; No as "label: No"). */
	fact: string;
	/** Where the value came from: from your dictation / from the exam / the basis / inferred. */
	source: string;
	quote: string;
	/** The second answer: a boolean's other value, an enum's one other option, or a choice from the options. */
	other: { kind: 'boolean' | 'option'; value: string; label: string } | { kind: 'choose' } | null;
	more: number;
}

const isBoolean = (options: string[]) => options.includes('Yes') && options.includes('No');
const factOf = (label: string, value: string, options: string[]) => (!value ? label : isBoolean(options) && value === 'Yes' ? label : `${label}: ${shownValue(value)}`);

/** The collapsed row's content (spec: Hassan 2026-10-15): the first scope doubt, or the exclusion's specific reason,
 *  as a fact with its source, and the second answer named by what it does. */
export function collapsedReason(p: Preview, excludedHeadline: string): CollapsedReason | null {
	const rows = new Map((p.draft ?? []).map((d) => [d.input, d]));
	const sourceOf = (input: string) => {
		const r = rows.get(input);
		return r?.by === 'exam' ? 'from the exam' : r?.basis ? r.basis : r?.quote ? 'from your dictation' : 'inferred';
	};
	if (p.state === 'does_not_apply') {
		const x = p.exclusion_reason;
		const r = x ? rows.get(x.input) : undefined;
		const options = r?.options ?? [];
		return {
			kind: 'excluded',
			input: x?.input ?? '',
			label: x?.label ?? '',
			value: x?.value ?? '',
			options,
			fact: x ? factOf(x.label, x.value ?? '', options) : excludedHeadline,
			source: x ? sourceOf(x.input) : '',
			quote: r?.quote ?? '',
			other: null,
			more: 0
		};
	}
	const ds = scopeDoubts(p);
	const d = ds[0];
	if (!d) return null;
	const others = d.options.filter((o) => o !== NOT_STATED && o !== d.value);
	const other: CollapsedReason['other'] = isBoolean(d.options)
		? d.value === 'Yes' || d.value === 'No' ? { kind: 'boolean', value: d.value === 'Yes' ? 'No' : 'Yes', label: '' } : { kind: 'choose' }
		: others.length === 1 ? { kind: 'option', value: others[0], label: shownValue(others[0]) } : { kind: 'choose' };
	return { kind: 'doubt', input: d.input, label: d.label, value: d.value, options: d.options, fact: factOf(d.label, d.value, d.options), source: sourceOf(d.input), quote: rows.get(d.input)?.quote ?? '', other, more: ds.length - 1 };
}

/** The head's assumed values: the decisive assumed values not yet ticked (what Check still shows), as "Label: value".
 *  A pre-draft preview keeps the older derivation. */
export function assumedUnticked(p: Preview | null | undefined, ticks: Record<string, string> = {}): string[] {
	if (!p) return [];
	if (!p.draft?.length) return assumptionsOf(p);
	return checkItems(p, ticks)
		.filter((c) => c.kind === 'assumed' && !c.affirmed)
		.map((c) => `${c.label}: ${shownValue(c.value)}`);
}
