// Sub-pills (Hassan 2026-10-14, option A): a template paragraph that covers several structures shows one assumed
// chip per structure. The paragraph stays the region everywhere else (grouping, the assumed check, Generate); this
// only regroups the sentences the region already keeps. A sentence no structure owns stays on the paragraph's chip.
import { assumedKey } from './protocol';

export interface Chip { key: string; region: string; label: string; sentences: string[] }

/** The assumed chips of one region: one per structure with a sentence still kept, then the paragraph's own chip for
 *  the rest. Never empty: with nothing kept, the paragraph chip alone (empty), as today. */
export function regionChips(region: string, kept: string[], structures: Record<string, string[]> | undefined): Chip[] {
	if (!structures || !Object.keys(structures).length) return [{ key: region, region, label: region, sentences: kept }];
	const claimed = new Set<number>();
	const out: Chip[] = [];
	for (const [label, own] of Object.entries(structures)) {
		const keys = new Set(own.map(assumedKey));
		const mine = kept.filter((s, i) => !claimed.has(i) && keys.has(assumedKey(s)) && claimed.add(i));
		if (mine.length) out.push({ key: `${region}\u0001${label}`, region, label, sentences: mine });
	}
	const rest = kept.filter((_, i) => !claimed.has(i));
	if (rest.length || !out.length) out.push({ key: region, region, label: region, sentences: rest });
	return out;
}

/** Structures the dictation answered: none of their sentences is still assumed, and none was removed by the
 *  radiologist (a removed sentence is theirs, not the dictation's). */
export function coveredStructures(assumed: string[], removed: string[], structures: Record<string, string[]> | undefined): string[] {
	if (!structures) return [];
	const kept = new Set(assumed.map(assumedKey));
	const gone = new Set(removed.map(assumedKey));
	return Object.entries(structures)
		.filter(([, own]) => own.length && own.every((s) => !kept.has(assumedKey(s)) && !gone.has(assumedKey(s))))
		.map(([label]) => label);
}
