// Small text helpers the card components share. Pure, so they are unit-tested apart from the markup.
import { cardRef, outcomeOf } from '../state';
import type { Ask, Card, Citation, OpenResult, Preview } from '../types';

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

/** Eligibility checks the card assumes rather than asks (B0, Hassan 2026-10-13: never lead with them). Task 3's
 *  `preview.assumptions` when sent; until then the missing eligibility inputs' labels. */
export function assumptionsOf(p: Preview | null | undefined): string[] {
	if (!p) return [];
	if (p.assumptions) return p.assumptions;
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	return p.missing.filter((m) => isEligibility(p, m)).map((m) => labels.get(m) || m);
}

/** The still-open questions that are not eligibility checks, in `missing` order (shown last, quietly). */
export function openQuestions(p: Preview): string[] {
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	return p.missing.filter((m) => !isEligibility(p, m)).map((m) => labels.get(m) || m);
}

const humanise = (id: string) => (id.charAt(0).toUpperCase() + id.slice(1)).replace(/_/g, ' ');
export interface ValueRow { input: string; label: string; value: string; quote: string; byExam: boolean }
/** The values read from the dictation (preview.settled), labelled from the entry's inputs, else the ask, else the id. */
export function valueRows(r: OpenResult): ValueRow[] {
	const p = r.preview;
	if (!p) return [];
	const labels = new Map<string, string>();
	for (const b of r.entry?.content.branches ?? []) for (const i of b.inputs ?? []) if (i.question) labels.set(i.id, i.question);
	for (const a of p.asks) if (!labels.has(a.input) && a.label) labels.set(a.input, a.label);
	return p.settled.map((s) => ({ input: s.input, label: labels.get(s.input) ?? humanise(s.input), value: s.value, quote: s.quote, byExam: s.by === 'exam' }));
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
