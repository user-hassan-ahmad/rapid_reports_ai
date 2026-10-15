// Small text helpers the card components share. Pure, so they are unit-tested apart from the markup.
import { cardRef, NOT_STATED, outcomeOf, rowsOf } from '../state';
import type { ActionCategory, Ask, Card, Citation, OpenResult, Preview, ValueState } from '../types';

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

const isEligibility = (p: Preview, input: string) => p.asks.some((a) => a.input === input && a.role === 'eligibility');

const hasDraft = (p: Preview) => !!p.draft?.length;

/** What a visible sign assumed absent reads as (Assumption.kind "sign"). */
export const ASSUMED_ABSENT = 'assumed absent';

/** The values the card assumes rather than asks (never the lead), as "Label: value" ("Label: assumed absent" for a
 *  visible sign). From the backend's `assumptions` objects; else the draft's assumed rows; else (pre-Task 3) the
 *  missing eligibility inputs. */
export function assumptionsOf(p: Preview | null | undefined): string[] {
	if (!p) return [];
	if (p.assumptions?.length) return p.assumptions.map((a) => `${a.label}: ${a.kind === 'sign' ? ASSUMED_ABSENT : a.value}`);
	if (hasDraft(p)) return rowsOf(p).assumed.map((v) => (v.value ? `${v.label}: ${v.value}` : v.label));
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	return p.missing.filter((m) => isEligibility(p, m)).map((m) => labels.get(m) || m);
}

/** "Depends on <question>": the deciding input's label (from the draft), else the first still-open question that can
 *  change the outcome. Empty when nothing is said to decide it. */
export function decidingQuestion(p: Preview): string {
	if (!p.deciding?.length) return '';
	return p.deciding_input?.label || rowsOf(p).asked.find((v) => v.needed)?.label || openQuestions(p)[0] || '';
}

/** Marks an assumed band whose exact number an open formula branch still needs (e.g. an age assumed "18 or over"). */
export const EXACT_NEEDED = '(exact value needed)';
/** The still-open questions that can change the outcome (spec §7.12 item 3: the head counts only these): the
 *  draft's asked rows with `needed` (eligibility first in check_first), then its assumed rows with `needed` (a band
 *  assumed, the exact number still needed: "{label} (exact value needed)"; the row stays the editable assumed row),
 *  else (pre-Task 3) the missing inputs that are not eligibility checks. */
export function openQuestions(p: Preview): string[] {
	if (hasDraft(p)) {
		const r = rowsOf(p);
		return [...r.asked.filter((v) => v.needed).map((v) => v.label), ...r.assumed.filter((v) => v.needed).map((v) => `${v.label} ${EXACT_NEEDED}`)];
	}
	const labels = new Map(p.asks.map((a) => [a.input, a.label]));
	return p.missing.filter((m) => !isEligibility(p, m)).map((m) => labels.get(m) || m);
}

/** The draft's asked rows that cannot change the outcome on this branch (not needed, not waiting). */
export const notNeededRows = (p: Preview | null | undefined) => rowsOf(p ?? null).asked.filter((v) => !v.needed);
/** Their labels: "N not needed on this branch", so the radiologist sees why they are not asked (§7.12 item 3). */
export const notNeeded = (p: Preview | null | undefined): string[] => notNeededRows(p).map((v) => v.label);

/** The card's one value list (simplified card, Hassan 2026-10-13): every input the draft shows, each editable with
 *  its provenance; assumed first, then pre-filled (exam presets included), then read, then answered or changed,
 *  then still open; waiting rows hidden; N/A last (the card hides them behind a toggle). Without a draft (non-pack
 *  cards, a pre-Task 3 backend) it falls back to valueRows. */
export function allValueRows(r: OpenResult): ValueRow[] {
	const p = r.preview;
	if (!p?.draft?.length) return valueRows(r);
	const rank: Record<string, number> = { assumed: 0, prefilled: 1, read: 2, answered: 3, edited: 3, asked: 5, not_applicable: 6 };
	const assumption = new Map((p.assumptions ?? []).map((a) => [a.input, a]));
	return p.draft
		.filter((v) => !v.waiting)
		.map((v, i) => ({ v, i }))
		.sort((a, b) => (rank[a.v.state] ?? 4) - (rank[b.v.state] ?? 4) || a.i - b.i)
		.map(({ v }) => ({
			input: v.input,
			label: v.label || humanise(v.input),
			value: v.value,
			quote: v.quote,
			byExam: v.by === 'exam',
			state: v.state,
			why: v.why,
			options: v.options,
			...(v.basis ? { basis: v.basis } : {}),
			...(v.decisive !== undefined ? { decisive: v.decisive } : assumption.has(v.input) ? { decisive: assumption.get(v.input)!.decisive } : {}),
			...(v.state === 'assumed' && assumption.get(v.input)?.kind === 'sign' ? { sign: true } : {})
		}));
}

/** The recommendation, minus what the action already says: the full text when it does not start with the action,
 *  the rest when it does (e.g. "CT at 3 months" + "CT at 3 months, then 1 year…" → "then 1 year…"), nothing when
 *  the rest is only a word or two ("No further imaging" + "No further imaging required."). */
export function recommendationBeyond(action: string, recommendation: string): string {
	const rec = recommendation.trim();
	if (!rec) return '';
	const a = action.trim().toLowerCase().replace(/[.;:,]+$/, '');
	if (!a || !rec.toLowerCase().startsWith(a)) return rec;
	const rest = rec.slice(a.length).replace(/^[\s,;:.—-]+/, '').trim();
	return rest.replace(/[.;:,]+$/, '').split(/\s+/).filter(Boolean).length >= 3 ? rest : '';
}

/** Pre-filled values that would make the guideline not apply (preview.scope_doubt), with their label and value from
 *  the draft. Never an exclusion until the radiologist confirms or changes them. */
export function scopeDoubts(p: Preview | null | undefined): { input: string; label: string; value: string; options: string[] }[] {
	if (!p?.scope_doubt?.length) return [];
	const rows = new Map((p.draft ?? []).map((v) => [v.input, v]));
	return p.scope_doubt.map((id) => ({ input: id, label: rows.get(id)?.label || humanise(id), value: rows.get(id)?.value ?? '', options: rows.get(id)?.options ?? [] }));
}

/** The backend's WHY_EXAM (library/pack_preview.py): an exam preset, shown as the "set by the exam" chip instead. */
export const WHY_EXAM = 'set by the exam';
const humanise = (id: string) => (id.charAt(0).toUpperCase() + id.slice(1)).replace(/_/g, ' ');
/** A value as the card shows it: a stored option id ("diameter_clear_growth") as words, anything else as it is. */
export const shownValue = (v: string) => (/^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(v) ? humanise(v) : v);
/** "Not stated" is the wire value that clears an input; the radiologist answering reads "Not known" (spec 2026-10-14 §4.3). */
export const NOT_KNOWN = 'Not known';
export const optionLabel = (o: string) => (o === NOT_STATED ? NOT_KNOWN : shownValue(o));
export interface ValueRow { input: string; label: string; value: string; quote: string; byExam: boolean; state: ValueState; why: string[]; options?: string[]; decisive?: boolean | null; /** assumed: a visible sign assumed absent */ sign?: boolean; /** where a derived value came from (§7.12 item 4) */ basis?: string }
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
			why: v.why,
			options: v.options,
			...(v.basis ? { basis: v.basis } : {})
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

export const setByExam = (p: Preview | null | undefined) => !!p?.settled.some((s) => s.by === 'exam');

/** The column ref a SiblingColumns retry names: the card ref plus the pack key, so A6 retries one column. */
export const columnRef = (card: Card, key: string) => `${cardRef(card)}#${key}`;

// ── Card redesign (B-design, Hassan after checkpoint 3): judgement first ──

export type VerdictCategory = ActionCategory | 'neutral' | 'open';
export interface Verdict {
	category: VerdictCategory;
	/** The pill's text: the action, else the headline, else the open state. */
	pill: string;
	/** No outcome yet, but a likeliest one (planned `most_likely`): coloured, drawn dashed. */
	tentative?: boolean;
	/** The card does not apply (state does_not_apply): only this dims and mutes. An outcome whose category is
	 *  not_applicable (e.g. "manage as solid") or info is a real verdict and stays fully legible. */
	excluded?: boolean;
	/** The outcome's full recommendation: always shown beside the short action (an action can drop later steps). */
	recommendation: string;
	headline: string;
	action: string;
	classification: string;
	caveats: string[];
	citations: Citation[];
	/** A scope doubt leads the card (controller ruling 2026-10-14): the drafted outcome, kept as a secondary line. */
	ifApplies?: string;
}
export interface VerdictOverride { headline?: string | null; action?: string | null; category?: ActionCategory | null }

const words = (s: string, n: number) => {
	const w = s.trim().split(/\s+/);
	return w.length > n ? `${w.slice(0, n).join(' ')}…` : w.join(' ');
};
const unstop = (s: string) => s.trim().replace(/[.;:,]+$/, '');
/** Fallback headline until the backend sends one: the classification's first clause (before ":"), ≤ 8 words. */
export const headlineOf = (classification: string) => words(unstop(classification.split(':')[0] ?? ''), 8);
/** Fallback action: the recommendation's first sentence. */
export const actionOf = (recommendation: string) => unstop(recommendation.split(/(?<=[.;])\s/)[0] ?? '');

/** What the card leads with. The backend's planned per-outcome `headline` / `action` / `category` win (and props
 *  override both); until then category is not_applicable for does_not_apply, none for a normal outcome, else
 *  neutral, and the headline and action come from the classification and recommendation. With no outcome yet the
 *  pill counts what is still open. */
export function verdictOf(p: Preview | null | undefined, o: VerdictOverride = {}): Verdict | null {
	if (!p) return null;
	if (p.state === 'does_not_apply') {
		const x = p.exclusion;
		// an exclusion worded by its own outcome (§7.12 item 1, e.g. "Outside the table: interval growth") says so
		const worded = !!p.exclusion_reason?.outcome && !!x;
		return {
			category: 'not_applicable',
			pill: 'Does not apply',
			excluded: true,
			// the specific reason first ("Maximum diameter 38 mm"), never the generic list of exclusion criteria
			headline:
				o.headline ||
				(worded ? x!.headline || headlineOf(x!.classification) : '') ||
				(p.exclusion_reason ? `${p.exclusion_reason.label} ${p.exclusion_reason.value}` : '') ||
				x?.headline ||
				(x ? headlineOf(x.classification) : 'Does not apply'),
			action: worded ? x!.recommendation : '',
			recommendation: x?.recommendation ?? '',
			classification: x?.classification ?? '',
			caveats: x?.caveats ?? [],
			citations: x?.citations ?? []
		};
	}
	const out = outcomeOf(p);
	const doubt = scopeDoubts(p)[0];
	if (doubt) {
		// a pre-filled value that would exclude: the card leads with the doubt, never the drafted outcome (ruling)
		const d = out ? { headline: o.headline || out.headline || headlineOf(out.classification), action: o.action || out.action || actionOf(out.recommendation) } : p.most_likely;
		const then = d?.headline ? `If it applies: ${[d.headline, d.action].filter(Boolean).join(' — ')}` : '';
		return {
			category: 'not_applicable',
			pill: 'May not apply',
			tentative: true,
			headline: `Check: ${[doubt.label, shownValue(doubt.value)].filter(Boolean).join(' — ')}`,
			action: '',
			recommendation: '',
			classification: '',
			caveats: [],
			citations: out?.citations ?? [],
			...(then ? { ifApplies: then } : {})
		};
	}
	if (!out && p.most_likely?.headline) {
		const m = p.most_likely;
		return { category: m.category || 'neutral', pill: `Likely: ${m.headline}`, headline: m.headline, action: m.action || '', recommendation: '', classification: '', caveats: [], citations: [], tentative: true };
	}
	if (!out) {
		const n = openQuestions(p).length;
		const pill = n ? `${n} ${n === 1 ? 'question' : 'questions'} open` : p.possible.length > 1 ? `${p.possible.length} outcomes possible` : 'No outcome yet';
		return { category: 'open', pill, headline: '', action: '', recommendation: '', classification: '', caveats: [], citations: [] };
	}
	// "" from the backend (a pack without display fields) falls back like an absent field
	const headline = o.headline || out.headline || headlineOf(out.classification);
	const action = o.action || out.action || actionOf(out.recommendation);
	return {
		category: o.category || out.category || (out.normal ? 'none' : 'neutral'),
		pill: action || headline,
		headline,
		action,
		recommendation: out.recommendation,
		classification: out.classification,
		caveats: out.caveats,
		citations: out.citations
	};
}

const STOP = new Set(['of', 'the', 'and', 'for', 'in', 'on', 'de', 'la', 'et']);
/** "European Society of Endocrinology" → "ESE"; an abbreviation in brackets wins; one word stays as it is. */
export function issuerShort(issuer: string): string {
	const bracket = issuer.match(/\(([A-Z][A-Za-z0-9-]{1,9})\)/);
	if (bracket) return bracket[1];
	const w = issuer.split(/[\s,]+/).filter((x) => x && !STOP.has(x.toLowerCase()) && /^[A-Za-z]/.test(x));
	return w.length > 1 ? w.map((x) => x[0].toUpperCase()).join('') : (w[0] ?? '');
}
/** One short source line: issuer + year + locator, e.g. "ESE 2023 · Fig 5, p. 18". */
export function citeShort(c: Citation): string {
	const who = c.issuer ? issuerShort(c.issuer) : (c.title ?? c.source ?? '').split(/\s+/).slice(0, 3).join(' ');
	const year = (c.edition ?? '').match(/\d{4}/)?.[0] ?? '';
	const where = (c.table || c.section || '').replace(/\bFigure\b/g, 'Fig').replace(/\bTable\b/g, 'Table');
	const loc = [where.length > 24 ? `${where.slice(0, 23)}…` : where, c.page ? `p. ${c.page}` : ''].filter(Boolean).join(', ');
	return [[who, year].filter(Boolean).join(' '), loc].filter(Boolean).join(' · ');
}
/** Citations deduplicated (identical full lines show once), as one short line plus the full list. */
export function sourcesOf(cs: Citation[]): { short: string; more: number; full: string[] } {
	const seen = new Map<string, Citation>();
	for (const c of cs) {
		const t = citeText(c);
		if (t && !seen.has(t)) seen.set(t, c);
	}
	const list = [...seen.values()];
	return { short: list.length ? citeShort(list[0]) : '', more: Math.max(0, list.length - 1), full: [...seen.keys()] };
}

/** The category's text token: >= 4.5:1 on its wash in both themes (the -line tokens are for strips and icons). */
export const categoryText = (c: VerdictCategory) =>
	({
		none: 'var(--rv-green-text)',
		surveillance: 'var(--rv-blue-text)',
		workup: 'var(--rv-amber-text)',
		refer: 'var(--rv-red-text)',
		info: 'var(--rv-text)', // no management stated: neutral, but a real verdict, fully legible
		not_applicable: 'var(--rv-text)', // the outcome's own category (e.g. manage as solid); muted only when excluded
		neutral: 'var(--rv-text)',
		open: 'var(--rv-muted)'
	})[c];

/** The category's colour token (the card's left strip, the pill's border and wash, icons). */
export const categoryColor = (c: VerdictCategory) =>
	({
		none: 'var(--rv-green-line)',
		surveillance: 'var(--rv-blue-line)',
		workup: 'var(--rv-amber-line)',
		refer: 'var(--rv-red-line)',
		info: 'var(--rv-border-strong)',
		not_applicable: 'var(--rv-border-strong)',
		neutral: 'var(--rv-border-strong)', // not categorised yet (no backend category): no colour claim
		open: 'var(--rv-muted)'
	})[c];
