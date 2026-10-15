import { cardRef, type Group } from './state';

/** The number each finding carries in the rail and the scratchpad margin: 1, 2, 3… in rail order over the groups
 *  that have a finding and at least one card (the exam group has none). */
export function findingNumbers(groups: Group[]): Record<string, number> {
	const out: Record<string, number> = {};
	let n = 0;
	for (const g of groups) if (g.finding && g.cards.length) out[g.finding.id] = ++n;
	return out;
}

/** Open card refs in the order they were opened: refs no longer open drop out, newly open ones go last. */
export function trackOpen(order: string[], openNow: string[]): string[] {
	const now = new Set(openNow);
	const kept = order.filter((r) => now.has(r));
	return [...kept, ...openNow.filter((r) => !kept.includes(r))];
}

/** The finding being looked at: a hovered or focused one, else the finding of the most recently opened card. */
export function activeFindingOf(hover: string | null, openOrder: string[], groups: Group[]): string | null {
	if (hover) return hover;
	for (let i = openOrder.length - 1; i >= 0; i--) {
		const ref = openOrder[i];
		const g = groups.find((x) => x.finding && x.cards.some((c) => cardRef(c) === ref || ref.startsWith(`${cardRef(c)}#`)));
		if (g?.finding) return g.finding.id;
	}
	return null;
}

/** Move a ref to the most recent position (a card revealed by the walkthrough, even one already open). */
export function touch(order: string[], ref: string): string[] {
	return [...order.filter((r) => r !== ref), ref];
}

/** The ref of the first card in a finding's rail group (what its scratchpad marker reveals), or null. */
export function firstCardRef(groups: Group[], findingId: string): string | null {
	const g = groups.find((x) => x.finding?.id === findingId && x.cards.length);
	return g ? cardRef(g.cards[0]) : null;
}
