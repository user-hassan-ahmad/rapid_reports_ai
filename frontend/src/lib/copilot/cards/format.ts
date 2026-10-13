// Small text helpers the card components share. Pure, so they are unit-tested apart from the markup.
import { cardRef, outcomeOf, rowsOf } from '../state';
import type { Ask, Card, Citation, OpenResult, Preview, ValueState } from '../types';

/** One short citation line, as the backend's describe.cite_text: title (edition), p. N, section, table. */
export function citeText(c: Citation | null | undefined): string {
	if (!c) return '';
	let head = c.title || c.source || '';
	if (c.edition) head += ` (${c.edition})`;
	return [head, c.page ? `p. ${c.page}` : '', c.section ?? '', c.table ?? ''].filter(Boolean).join(', ');
}

/** A pack key's issuer slug as a column title before /open answers: "bts-pulmonary-nodule" → "BTS". */
export function issuerSlug(key: string): string {
	const s = key.split('-')[0] ?? key;
	return s.length <= 4 ? s.toUpperCase() : s[0].toUpperCase() + s.slice(1);
}

/** Column titles for a card with siblings, primary first: the opened entry's name, else the backend's
 *  sibling_names, else the issuer slug. */
export function columnTitles(card: Card, opened: Record<string, OpenResult | null | undefined> = {}): { key: string; title: string }[] {
	const keys = [card.key, ...card.siblings].slice(0, 3);
	return keys.map((key, i) => ({
		key,
		title: opened[key]?.entry?.name || (i === 0 ? card.name : card.sibling_names?.[i - 1]) || issuerSlug(key)
	}));
}

/** The labels of the missing inputs, in `missing` order; an input with no ask shows its id. */
export function missingLabels(p: Preview): string[] {
	const byInput = new Map<string, Ask>(p.asks.map((a) => [a.input, a]));
	return p.missing.map((m) => byInput.get(m)?.label || m);
}

const isEligibility = (p: Preview, input: string) => p.asks.some((a) => a.input === input && a.role === 'eligibility');

const hasDraft = (p: Preview) => !!p.draft?.length;

/** Eligibility checks the card assumed rather than asked (B0: never lead with them), as "Label: value". From the
 *  draft's assumed rows (Task 3); else `assumptions` ids with their ask labels; else (pre-Task 3) the missing
 *  eligibility inputs. */
export function assumptionsOf(p: Preview | null | undefined): string[] {
	if (!p) return [];
	if (hasDraft(p)) return rowsOf(p).assumed.map((v) => (v.value ? `${v.label}: ${v.value}` : v.label));
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	if (p.assumptions?.length) return p.assumptions.map((id) => labels.get(id) || id);
	return p.missing.filter((m) => isEligibility(p, m)).map((m) => labels.get(m) || m);
}

/** The still-open questions shown last, quietly: the draft's asked rows (eligibility first in check_first, then
 *  needed), else (pre-Task 3) the missing inputs that are not eligibility checks. */
export function openQuestions(p: Preview): string[] {
	if (hasDraft(p)) return rowsOf(p).asked.map((v) => v.label);
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	return p.missing.filter((m) => !isEligibility(p, m)).map((m) => labels.get(m) || m);
}

/** The backend's WHY_EXAM (library/pack_preview.py): an exam preset, shown as the "set by the exam" chip instead. */
export const WHY_EXAM = 'set by the exam';
const humanise = (id: string) => (id.charAt(0).toUpperCase() + id.slice(1)).replace(/_/g, ' ');
export interface ValueRow { input: string; label: string; value: string; quote: string; byExam: boolean; state: ValueState; why: string[] }
/** The values the card shows first. From the draft (Task 3): read, pre-filled, answered, edited and N/A rows with
 *  their state and why[]; else (pre-Task 3) preview.settled as read values, labelled from the entry's inputs, else
 *  the ask, else the id. */
export function valueRows(r: OpenResult): ValueRow[] {
	const p = r.preview;
	if (!p) return [];
	if (hasDraft(p))
		return rowsOf(p).values.map((v) => ({
			input: v.input,
			label: v.label || humanise(v.input),
			value: v.value,
			quote: v.quote,
			byExam: v.by === 'exam',
			state: v.state,
			why: v.why
		}));
	const labels = new Map<string, string>();
	for (const b of r.entry?.content.branches ?? []) for (const i of b.inputs ?? []) if (i.question) labels.set(i.id, i.question);
	for (const a of p.asks) if (!labels.has(a.input) && a.label) labels.set(a.input, a.label);
	return p.settled.map((s) => ({
		input: s.input,
		label: labels.get(s.input) ?? humanise(s.input),
		value: s.value,
		quote: s.quote,
		byExam: s.by === 'exam',
		state: s.by === 'exam' ? 'prefilled' : 'read',
		why: s.by === 'exam' ? [WHY_EXAM] : []
	}));
}

export type Badge = { text: string; variant: 'v' | 'a' };
/** The collapsed head's state badge, once a preview exists. */
export function stateBadge(p: Preview | null | undefined): Badge | null {
	if (!p) return null;
	if (p.state === 'applies') return { text: 'applies', variant: 'v' };
	if (p.state === 'check_first') return null; // rendered as if eligible; the assumed checks are a chip (B0)
	if (p.state === 'does_not_apply') return { text: 'does not apply', variant: 'v' };
	return { text: 'which lesion?', variant: 'a' };
}

/** The collapsed hint: the reached outcome's classification, read-only. */
export function outcomeHint(p: Preview | null | undefined): string | null {
	const o = outcomeOf(p ?? null);
	return o?.classification ? `on these values · ${o.classification}` : null;
}

export const setByExam = (p: Preview | null | undefined) => !!p?.settled.some((s) => s.by === 'exam');

/** The column ref a SiblingColumns retry names: the card ref plus the pack key, so A6 retries one column. */
export const columnRef = (card: Card, key: string) => `${cardRef(card)}#${key}`;
