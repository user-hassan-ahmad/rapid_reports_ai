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
	if (e.source === 'setup') return e.quote ? `From the study setup: '${e.quote}'` : 'study setup: stated';
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
	if (card.wording) return { ...card.wording };
	const withWording = card.choices.filter((x) => x.choice && x.choice.use === true);
	const pick = withWording.find((x) => x.id === selectedId) ?? withWording[0];
	if (!pick?.choice) return {};
	const c = pick.choice as { default?: string; when_met?: string; condition?: string };
	return { default: c.default ?? '', when_met: c.when_met ?? '', condition: c.condition ?? '' };
}

/** The change an answer records; null when it needs wording the radiologist has not written. */
export function changeFor(card: DecisionCard, a: Answer, source: ChangeSource): DecisionChange | null {
	if (!card.ledger_kind) return null;
	const c = card.choices.find((x) => x.id === a.choiceId);
	if (!c) return null;
	if (c.choice) return { kind: card.ledger_kind, key: card.key, choice: c.choice, source };
	if (!a.edited) return null;
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
