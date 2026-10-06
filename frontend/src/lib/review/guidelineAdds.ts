// "Add to report" on the Guidelines tab: a guideline card or classification offers it only when the review engine
// already holds a matching open additions item (an S4 suggestion with an insert edit). The button runs the rail's
// `apply` on that item, so the item stays the one owner of the insert (no second copy, the ghost goes with it).
// Pure; no DOM.
import type { GuidelineEntry, RichClassificationGrade } from '$lib/guidelines/types';
import type { ReviewItem } from './types';

const norm = (v: unknown): string => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().toLowerCase() : '');

/** An open additions suggestion the radiologist can add: an insert with text, never suppressed. */
export function isAddable(it: ReviewItem): boolean {
	return (
		it.lane === 'additions' &&
		it.status === 'open' &&
		it.cls !== 'suppress' &&
		it.edit?.mode === 'insert' &&
		!!it.edit.replace?.trim()
	);
}

function cardOf(it: ReviewItem): number | null {
	const c = it.citation?.card;
	const n = typeof c === 'number' ? c : typeof c === 'string' && c.trim() ? Number(c) : NaN;
	return Number.isFinite(n) ? n : null;
}

/** The item belongs to this guideline card: same card number, else (no numbers) the same finding text. */
function sameCard(it: ReviewItem, g: GuidelineEntry): boolean {
	const card = cardOf(it);
	if (card != null && g.finding_number != null) return card === g.finding_number;
	const f = norm(it.evidence?.finding);
	return !!f && f === norm(g.finding);
}

const CARD_ORDER = ['follow_up', 'grade', 'threshold', 'option'];

/** The open additions item to add for a guideline card (follow-up first, then grade, threshold, option). */
export function itemForCard(items: readonly ReviewItem[], g: GuidelineEntry): ReviewItem | null {
	const hits = items.filter((i) => isAddable(i) && sameCard(i, g));
	const rank = (i: ReviewItem) => {
		const k = CARD_ORDER.indexOf(i.kind);
		return k < 0 ? CARD_ORDER.length : k;
	};
	return hits.sort((a, b) => rank(a) - rank(b))[0] ?? null;
}

/** The open additions item for one classification of a card: same system and grade (and card, when numbered). */
export function itemForClassification(
	items: readonly ReviewItem[],
	g: GuidelineEntry,
	cls: Pick<RichClassificationGrade, 'system' | 'grade'>
): ReviewItem | null {
	const sys = norm(cls.system);
	const grade = norm(cls.grade);
	if (!sys || !grade) return null;
	return (
		items.find((i) => {
			if (!isAddable(i) || norm(i.evidence?.system) !== sys || norm(i.evidence?.grade) !== grade) return false;
			const card = cardOf(i);
			return card == null || g.finding_number == null || card === g.finding_number;
		}) ?? null
	);
}
