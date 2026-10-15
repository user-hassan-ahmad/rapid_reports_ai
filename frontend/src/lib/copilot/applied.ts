// Applied recommendations (spec 2026-10-14 §7): the item Apply writes from Calculate, and when it goes stale. Pure.
import type { AppliedRec } from '$lib/hybrid-stack/types';
import { sentenceOf } from './cards/questionnaire';
import { verdictKey } from './gate';
import type { Calculation, Card, DraftValue, Preview, Proposal } from './types';

export const CHANGED = 'The card changed while applying: check it and apply again';
export interface ApplyInput { key: string; card: Card; source: string; preview: Preview; calc: Calculation; pick: string | null; ticks: Record<string, string> }

/** The applied item, or CHANGED when Calculate disagrees with the card or has no complete sentence to write. */
export function buildApplied(x: ApplyInput): AppliedRec | string {
	let pr: Proposal | null = null;
	let outcome = '';
	let chosenFrom: number | undefined;
	if (x.pick == null) {
		const cardOutcome = (x.preview.trace?.['outcome'] as string | undefined) ?? null;
		if (!x.calc.outcome || x.calc.outcome !== cardOutcome || !x.calc.result) return CHANGED;
		pr = x.calc.result;
		outcome = x.calc.outcome;
	} else {
		const cands = x.calc.candidates ?? [];
		const c = cands.find((k) => k.outcome === x.pick);
		if (x.calc.outcome || !c?.proposal) return CHANGED;
		pr = c.proposal;
		outcome = c.outcome;
		chosenFrom = cands.length;
	}
	const sentence = sentenceOf(pr, x.source);
	return {
		key: x.key,
		finding_id: x.card.finding_id,
		pack: x.card.key,
		version: x.calc.pack || x.card.version,
		bundle: x.calc.bundle,
		source: x.source,
		outcome,
		verdict: verdictKey(x.preview),
		...(chosenFrom ? { chosen_from: chosenFrom } : {}),
		sentence,
		text: sentence,
		values: x.calc.values
			.filter((v) => v.value && v.state !== 'asked' && v.state !== 'not_applicable')
			.map((v) => ({
				input: v.input,
				value: v.value,
				state: (v.state === 'prefilled' || v.state === 'assumed') && x.ticks[v.input] === v.value ? 'confirmed' : v.state,
				...(v.quote ? { quote: v.quote } : {})
			}))
	};
}

/** 'finding' when the finding is gone (checked first: the session keeps a deleted finding's card until the next
 *  match); 'values' when the card is no longer grouped while its finding stayed (its text changed: `preview` null), when
 *  the card's outcome moved (it no longer applies, or its verdict differs from the line's), or when a value behind the
 *  line no longer shows the same; undefined when current. */
export function staleOf(rec: AppliedRec, preview: Preview | null, findingThere: boolean): AppliedRec['stale'] {
	if (!findingThere) return 'finding';
	if (!preview) return 'values';
	if (preview.state === 'does_not_apply' || verdictKey(preview) !== rec.verdict) return 'values';
	const shown = new Map((preview.draft ?? []).map((d) => [d.input, d.state === 'asked' || d.state === 'not_applicable' ? '' : d.value]));
	return rec.values.some((v) => shown.get(v.input) !== v.value) ? 'values' : undefined;
}

/** What the confirm record carries (spec §7.6): nothing while Apply is off. */
export function recommendationsForGate(on: boolean, applied: Record<string, AppliedRec> | undefined): AppliedRec[] {
	return on ? Object.values(applied ?? {}) : [];
}

/** A stable key for the lines the gate record carries (key and trimmed text, by key): any change to them stales a confirmed gate. */
export function recommendationsKey(recs: AppliedRec[]): string {
	return JSON.stringify(recs.map((r) => [r.key, r.text.trim()]).sort());
}
