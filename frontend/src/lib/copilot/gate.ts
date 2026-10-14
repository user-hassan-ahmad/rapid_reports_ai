// The confirm gate sees the guideline panel (spec §7.12 item 5). Pure: which cards are significant, and which of
// them still block Confirm given the conclusion check and the radiologist's "Seen, leave as is" taps.
// Failures never block (integration D24): a card whose preview failed, timed out or is loading has no verdict.
import { columnRef, columnTitles, openQuestions, verdictOf } from './cards/format';
import { closedView, errorOf, type ColumnView } from './cards/view';
import type { CopilotState } from './session';
import { cardRef, kindOf, quiet } from './state';
import type { Card, ConclusionCategory, Preview } from './types';

export type { ConclusionCategory } from './types';

/** `key`: the card ref, or `<cardRef>#<pack key>` for one sibling column (the ref "Seen" and the check use);
 *  `card`: the card ref the rail opens; `reason`: why the conclusion did not clear it. */
export type Unresolved = { key: string; name: string; card?: string; reason?: string };

/** none 0 < follow-up imaging 1 < further tests 2 < referral 3 (Hassan 2026-10-14). */
const RANK: Record<string, number> = { none: 0, surveillance: 1, workup: 2, refer: 3 };
const PHRASE: Record<ConclusionCategory, string> = {
	none: 'no recommendation',
	surveillance: 'follow-up imaging',
	workup: 'further tests',
	refer: 'referral'
};
/** The verdict's category when it is one the gate ranks above none (surveillance, workup, refer), else null. */
function rankedCategory(p: Preview): ConclusionCategory | null {
	const c = verdictOf(p)?.category ?? '';
	return RANK[c] > 0 ? (c as ConclusionCategory) : null;
}

/** A card that must clear before Confirm: a current verdict (draft outcome or most likely) of category surveillance,
 *  workup or refer, an outcome-changing open question, or a scope doubt. Never a missing, degraded or
 *  does_not_apply preview, a reference (tier 2) or an off-modality card. */
export function significant(p: Preview | null | undefined, card?: Card): boolean {
	if (!p || p.degraded || p.state === 'does_not_apply') return false;
	if (card && (card.reference || card.needs_modality)) return false;
	return !!rankedCategory(p) || openQuestions(p).length > 0 || (p.scope_doubt?.length ?? 0) > 0;
}

/** What "Seen" holds: the verdict's category and headline, so a changed verdict re-opens the card. */
export function verdictKey(p: Preview | null | undefined): string {
	const v = verdictOf(p);
	return v ? `${v.category}|${v.headline}` : '';
}

export interface GateTarget { key: string; card: Card; name: string; preview: Preview }

/** Every card or sibling column with a settled preview (not loading, not failed), in rail order. Only the cards
 *  that carry "Seen, leave as is" (pack cards: finding or exam, not a quiet line), so Confirm is always one tap
 *  away. */
export function targets(state: CopilotState): GateTarget[] {
	const out: GateTarget[] = [];
	const settled = (v: ColumnView | null | undefined) => (v && !v.loading && !errorOf(v) ? (v.result?.preview ?? null) : null);
	for (const g of state.groups)
		for (const c of g.cards) {
			if (c.reference || c.needs_modality) continue;
			const ref = cardRef(c);
			const view = state.views[ref] ?? closedView;
			const kind = kindOf(c, !!view.fromOther);
			if (kind !== 'finding' && kind !== 'exam') continue;
			if (!c.siblings.length) {
				if (kind === 'exam' && view.result && quiet(c, view.result.preview)) continue;
				const p = settled(view);
				if (p) out.push({ key: ref, card: c, name: c.name, preview: p });
				continue;
			}
			const titles = columnTitles(c, Object.fromEntries(Object.entries(view.columns ?? {}).map(([k, v]) => [k, v.result])));
			for (const t of titles) {
				const p = settled(view.columns?.[t.key] ?? (t.key === c.key ? view : null));
				if (p) out.push({ key: columnRef(c, t.key), card: c, name: t.title, preview: p });
			}
		}
	return out;
}

/** The significant cards still blocking Confirm. One clears when the conclusion recommends at least as much as its
 *  verdict (rank), or, with no ranked verdict (an open question or a scope doubt), anything but none; or when
 *  "Seen" was tapped on its current verdict. A failed check (null) clears nothing. */
export function unresolved(state: CopilotState, seen: Record<string, string>, concl: Record<string, ConclusionCategory | null>): Unresolved[] {
	const out: Unresolved[] = [];
	for (const t of targets(state)) {
		if (!significant(t.preview, t.card)) continue;
		if (seen[t.key] !== undefined && seen[t.key] === verdictKey(t.preview)) continue;
		const cat = rankedCategory(t.preview);
		const c = concl[t.key];
		if (c != null && (cat ? RANK[c] >= RANK[cat] : c !== 'none')) continue;
		const u: Unresolved = { key: t.key, card: cardRef(t.card), name: t.name };
		if (c != null && cat) u.reason = `Conclusion gives ${PHRASE[c]}; ${t.name} says ${PHRASE[cat]}`;
		out.push(u);
	}
	return out;
}
