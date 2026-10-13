// Pure card logic of the Rules step (mirrors backend template_rules_cards): the evidence line, the ledger change an
// answer records, and the changes sent on Continue or Skip. Nothing seen in fewer than every example is pre-ticked;
// only tapped cards are the radiologist's ("creation" / "first_use_review"); kept items left alone are "default".
import type { CardWording, ChangeSource, DecisionCard, DecisionChange, Evidence } from './types';

export interface Answer {
	choiceId: string;
	edited?: CardWording;
}

/** "reports 1, 2, 4: 'ECV 28%'" or "report 3: not stated" (never percentages); the study setup is named as such. */
export function evidenceLine(e: Evidence): string {
	if (e.source === 'setup') return e.quote ? `From the study setup: '${e.quote}'` : 'From the study setup';
	const nums = [...new Set(e.reports)].sort((a, b) => a - b);
	const head = (nums.length === 1 ? 'report ' : 'reports ') + nums.join(', ');
	return `${head}: ${e.quote ? `'${e.quote}'` : 'not stated'}`;
}

/** Cards with each collapsed group expanded into its own cards. */
export function flatCards(cards: DecisionCard[]): DecisionCard[] {
	return cards.flatMap((c) => (c.kind === 'group' ? (c.cards ?? []) : [c]));
}

/** The wording an "Edit wording" form starts from. A usual-state card (contrast with no clear majority) has no
 * single wording: it starts from the chosen state, else the first one, and keeps that state's condition. */
export function editWording(card: DecisionCard, selectedId: string | null): CardWording {
	if (card.ledger_kind === 'habit' && card.habit) return { ...card.habit };
	if (card.wording) return { ...card.wording };
	const withWording = card.choices.filter((x) => x.choice && x.choice.use === true);
	const pick = withWording.find((x) => x.id === selectedId) ?? withWording[0];
	if (!pick?.choice) return {};
	const c = pick.choice as { default?: string; when_met?: string; condition?: string };
	return { default: c.default ?? '', when_met: c.when_met ?? '', condition: c.condition ?? '' };
}

const ACRONYM_START = /^[a-z]+[A-Z]/; // a lowercase-led word that holds a capital ("eGFR"; "pH" is not)

/** A full sentence (mirrors backend template_decisions.is_sentence): it starts with a capital, a {slot}, a digit or a
 * lowercase-led acronym, and ends with "." or ":" (so never on a bare slot). Only the edges are checked. */
export function isSentence(text: string): boolean {
	const t = (text ?? '').trim();
	if (!t || !'.:'.includes(t[t.length - 1])) return false;
	const c = t[0];
	return (c !== c.toLowerCase() && c === c.toUpperCase()) || c === '{' || /\d/.test(c) || ACRONYM_START.test(t);
}

const QUOTES = /["“”]/;

/** Why written wording can't be stored (the server's rules), or null when it can. A concept's wordings must each be
 * a full sentence; a normal sentence has nothing to fill in; no wording has double quotes. Empty fields are not
 * judged here (changeFor asks for some wording). */
export function wordingProblem(card: DecisionCard, edited: CardWording | undefined): string | null {
	const e = edited ?? {};
	if (card.ledger_kind === 'habit') {
		const all = [e.condition ?? '', e.question ?? '', e.yes ?? '', e.no ?? ''].map((t) => t.trim());
		if (all.some((t) => QUOTES.test(t))) return 'Leave out double quotes.';
		if (all.some((t) => /[{}[\]|]/.test(t))) return 'Leave out values to fill in.';
		const q = (e.question ?? '').trim();
		if (q && !q.endsWith('?')) return 'End the question with "?".';
		return null;
	}
	const texts = card.ledger_kind === 'concept' ? [e.default ?? '', e.when_met ?? ''] : [e.text ?? ''];
	const written = texts.map((t) => t.trim()).filter(Boolean);
	if (written.some((t) => QUOTES.test(t))) return 'Leave out double quotes.';
	if (card.ledger_kind === 'concept') {
		if (written.some((t) => !isSentence(t))) return 'Write it as a full sentence.';
	} else if (written.some((t) => /[{}]/.test(t))) return 'Leave out values to fill in.';
	return null;
}

/** The change an answer records; null when it needs wording the radiologist has not written, or the written
 * wording breaks the server's rules (wordingProblem). */
export function changeFor(card: DecisionCard, a: Answer, source: ChangeSource): DecisionChange | null {
	if (!card.ledger_kind) return null;
	const c = card.choices.find((x) => x.id === a.choiceId);
	if (!c) return null;
	if (c.choice) return { kind: card.ledger_kind, key: card.key, choice: c.choice, source };
	if (!a.edited || wordingProblem(card, a.edited)) return null;
	if (card.ledger_kind === 'habit') {
		// an edited habit is asked every time, under its (re)worded condition, in the card's paragraph
		const [condition, question, yes, no] = [a.edited.condition, a.edited.question, a.edited.yes, a.edited.no].map((t) => (t ?? '').trim());
		if (!condition || !question || !yes || !no) return null;
		const paragraph = card.key.split(' :: ')[0];
		return { kind: 'habit', key: `${paragraph} :: ${condition}`, choice: { mode: 'ask', question, yes, no }, source };
	}
	if (card.ledger_kind === 'concept') {
		const d = (a.edited.default ?? '').trim();
		const w = (a.edited.when_met ?? '').trim();
		if (!d && !w) return null;
		// the condition stays the card's (or the chosen state's): which wording is usual was decided (D1)
		const condition = a.edited.condition ?? card.wording?.condition ?? '';
		return { kind: 'concept', key: card.key, choice: { use: true, default: d, when_met: w, condition, dictated: false }, source };
	}
	const text = (a.edited.text ?? '').trim();
	return text ? { kind: card.ledger_kind, key: card.key, choice: { text }, source } : null;
}

/** The habit card's edit hint (trigger lab 2026-10-13): a condition names where the finding is. Case-agnostic. */
export const HABIT_WHERE_HINT = "Name where: e.g. 'in the <structure>'";

/** A value name code can store: a few plain words, no quotes, bars, brackets or braces. */
export function validValueName(name: string): boolean {
	const n = name.trim();
	return n.length > 0 && n.split(/\s+/).length <= 8 && !/["|[\]{}]/.test(n);
}

/** Continue: every answered card (as `source`), the kept items left alone ("default"), and added values. Cards
 * inside a group count one by one. */
export function changesOnContinue(
	open: DecisionCard[],
	kept: DecisionCard[],
	answers: Record<string, Answer>,
	added: string[],
	source: ChangeSource
): DecisionChange[] {
	const out: DecisionChange[] = [];
	const keptIds = new Set(kept.map((c) => c.id));
	const seen = new Set<string>();
	for (const card of [...flatCards(open), ...kept]) {
		if (seen.has(card.id)) continue;
		seen.add(card.id);
		const a = answers[card.id];
		const ch = a
			? changeFor(card, a, source)
			: keptIds.has(card.id) && card.selected
				? changeFor(card, { choiceId: card.selected }, 'default')
				: null;
		if (ch) out.push(ch);
	}
	for (const name of added) out.push({ kind: 'value', key: name.trim(), choice: { need: 'every' }, source });
	return out;
}

/** Skip: the pre-ticked choices, recorded as defaults (never as confirmed). */
export function changesOnSkip(defaults: DecisionChange[]): DecisionChange[] {
	return defaults.map((d) => ({ ...d, source: 'default' as const }));
}
