// Findings-triggered template rows (spec 2026-10-13-findings-triggered-rows-design): pure helpers for the scratchpad.
// A template row asks the template's own question; Yes or No writes the template's own sentence; Not assessed writes
// nothing. Its required statements join the assumed tray.
import type { StackItem } from './types';

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

/** Yes or No on a template row: the answer record keeps only the sentence chosen (what Generate states). */
export function chooseTemplate(item: StackItem, which: 'yes' | 'no'): StackItem {
	const s = (which === 'yes' ? item.yes : item.no) ?? '';
	return { ...item, sentences: s ? [s] : [] };
}

/** The rows the view shows: an answered template row shows the sentence chosen, not both. */
export function withChosen(items: StackItem[], tapped: Record<string, StackItem>): StackItem[] {
	return items.map((i) => (i.kind === 'template' && tapped[i.id] ? tapped[i.id] : i));
}

/** The region normals offered to the assumed check: each region's met required statements first (never cut by the
 *  per-region cap), then the sheet's own, without repeats. */
export function withRequired(normals: Record<string, string[]>, required: Record<string, string[]>): Record<string, string[]> {
	const out: Record<string, string[]> = {};
	for (const r of [...Object.keys(required), ...Object.keys(normals)]) {
		if (out[r]) continue;
		const seen = new Set<string>();
		out[r] = [...(required[r] ?? []), ...(normals[r] ?? [])].filter((s) => {
			const k = norm(s);
			if (seen.has(k)) return false;
			seen.add(k);
			return true;
		});
	}
	return out;
}

/** Template rows answered (or skipped) whose condition a successful full review no longer meets: not in its reply.
 *  Their answers are dropped (an answer stands only while its condition is met). */
export function unmetTemplate(answered: Record<string, StackItem>, reply: { items: StackItem[]; capped: StackItem[] }): string[] {
	const live = new Set([...reply.items, ...reply.capped].map((r) => r.id));
	return Object.values(answered).filter((r) => r.kind === 'template' && !live.has(r.id)).map((r) => r.id);
}

/** The template rows' part of the gate key: each answered row's chosen sentence and the required statements met. */
export function templateKey(tapped: Record<string, StackItem>, required: Record<string, string[]>): string {
	const rows = Object.values(tapped).filter((r) => r.kind === 'template').map((r) => `${r.id}=${r.sentences.join(' ')}`).sort();
	return JSON.stringify([rows, required]);
}

/** What a successful full review does to the template's state: its met required statements replace the old ones, and
 *  answers (tapped or skipped) to template rows it no longer returns are dropped. A failed trigger (`trigger_error`)
 *  returns null: nothing changes, so answers the radiologist gave explicitly stay. */
export function reviewTemplate<S extends { item: StackItem }>(
	res: { items: StackItem[]; capped: StackItem[]; required?: Record<string, string[]>; trigger_error?: string | null },
	tapped: Record<string, StackItem>,
	skipped: Record<string, S>
): { required: Record<string, string[]>; tapped: Record<string, StackItem>; skipped: Record<string, S> } | null {
	if (res.trigger_error) return null;
	const skippedItems = Object.fromEntries(Object.entries(skipped).map(([k, v]) => [k, v.item]));
	const gone = new Set([...unmetTemplate(tapped, res), ...unmetTemplate(skippedItems, res)]);
	return {
		required: res.required ?? {},
		tapped: Object.fromEntries(Object.entries(tapped).filter(([k]) => !gone.has(k))),
		skipped: Object.fromEntries(Object.entries(skipped).filter(([k]) => !gone.has(k)))
	};
}
