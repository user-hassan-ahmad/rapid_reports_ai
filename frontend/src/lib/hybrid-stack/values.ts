// The value cluster (requirements spec 2026-10-12 part 1): the template's required values as chips. The server fills
// what the dictation states (Jev decides, code reads the number); the radiologist types the rest or marks them N/A.
// The radiologist's own entries, N/A marks and kept "stated" chips are never overwritten by a fill. Open and check
// chips block Confirm (walkthrough stops); filling ones hold it while the fill runs.
import type { ValueChip, ValueFill } from './types';

const key = (s: string) => s.trim().toLowerCase();
const opened = (item: string): ValueChip => ({ item, state: 'open', value: null, quote: null });
const own = (c: ValueChip) => c.state === 'entered' || c.state === 'na';

export function initialChips(items: string[]): ValueChip[] {
	return items.map(opened);
}

/** A fill is running: every chip but the radiologist's own shows progress and holds Confirm. */
export function startFill(chips: ValueChip[]): ValueChip[] {
	return chips.map((c) => (own(c) ? c : { ...c, state: 'filling' }));
}

/** A fill from the server: entered and N/A chips stand; a stated value with its sentence is filled; one with no
 *  sentence named needs a look (check), unless the radiologist already kept it; anything else is open. */
export function mergeFill(chips: ValueChip[], fill: ValueFill[]): ValueChip[] {
	const by = new Map(fill.map((f) => [key(f.item), f]));
	return chips.map((c) => {
		if (own(c)) return c;
		const f = by.get(key(c.item));
		if (!f || f.state !== 'filled') return opened(c.item);
		if (f.quote) return { item: c.item, state: 'filled', value: f.value, quote: f.quote };
		return c.kept ? { item: c.item, state: 'filled', value: null, quote: null, kept: true } : { item: c.item, state: 'check', value: null, quote: null };
	});
}

/** The fill failed: chips the dictation filled are open again (never blocks on the network). */
export const failFill = (chips: ValueChip[]): ValueChip[] => mergeFill(chips, []);

/** A typed value; empty reopens the chip. */
export function enterValue(chips: ValueChip[], item: string, text: string): ValueChip[] {
	const t = text.trim();
	return chips.map((c) => (c.item !== item ? c : t ? { item, state: 'entered', value: t, quote: null } : opened(item)));
}

export function markNa(chips: ValueChip[], item: string): ValueChip[] {
	return chips.map((c) => (c.item === item ? { item, state: 'na', value: null, quote: null } : c));
}

/** The radiologist looked at a "stated?" chip and keeps it: stated in the dictation, no value read. */
export function keepStated(chips: ValueChip[], item: string): ValueChip[] {
	return chips.map((c) => (c.item === item ? { item, state: 'filled', value: null, quote: null, kept: true } : c));
}

/** "Mark rest N/A": every open chip (a sequence not acquired); a stated one is never marked N/A in bulk. */
export function markRestNa(chips: ValueChip[]): ValueChip[] {
	return chips.map((c) => (c.state === 'open' ? { item: c.item, state: 'na', value: null, quote: null } : c));
}

/** Items that block Confirm and are walkthrough stops: open, or stated with no sentence named. */
export const blockingValues = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'open' || c.state === 'check').map((c) => c.item);
export const isFilling = (chips: ValueChip[]): boolean => chips.some((c) => c.state === 'filling');
export const naItems = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'na').map((c) => c.item);
/** Values filled from the dictation: sent with Generate so the post-generation backstop checks the report states each. */
export const filledItems = (chips: ValueChip[]): string[] => chips.filter((c) => c.state === 'filled').map((c) => c.item);
export const valuesKey = (chips: ValueChip[]): string => chips.map((c) => `${c.item}\u0001${c.state}\u0001${c.value ?? ''}`).join('\u0002');

/** What Generate states as the radiologist's answers: only values they typed (Hassan 2026-10-13). A filled value
 *  reaches the report through the dictation alone. */
export const valueStatements = (chips: ValueChip[]): string[] =>
	chips.filter((c) => c.state === 'entered' && c.value).map((c) => `${c.item} ${c.value}`);

export function chipLabel(c: ValueChip): string {
	if (c.state === 'na') return `${c.item} N/A`;
	if (c.state === 'open') return `${c.item} —`;
	if (c.state === 'filling') return `${c.item} …`;
	if (c.state === 'check') return `${c.item} stated?`;
	return c.value ? `${c.item} ${c.value}` : `${c.item} stated`;
}
