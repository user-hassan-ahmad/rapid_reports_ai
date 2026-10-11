// Check chips (spec 2026-10-11 §4): at most three per abnormal region, six on screen, regions in schema order.
import { effectiveItems } from './regionState';
import type { StackUnit } from './types';

export const PER_REGION = 3;
export const ON_SCREEN = 6;

export interface VisibleChip { region: string; text: string }

export function visibleChips(byRegion: Record<string, string[]>, abnormalRegions: string[]): VisibleChip[] {
	const out: VisibleChip[] = [];
	for (const region of abnormalRegions) {
		for (const text of (byRegion[region] ?? []).slice(0, PER_REGION)) {
			if (out.length >= ON_SCREEN) return out;
			out.push({ region, text });
		}
	}
	return out;
}

/** The region's abnormal sentences: what its chips are asked for, and the key that re-asks them on change. */
export function abnormalSentences(units: StackUnit[], region: string): string[] {
	return effectiveItems(units).filter((i) => i.group === region && i.abnormal).map((i) => i.text);
}

export const sentencesKey = (sentences: string[]): string => sentences.map((s) => s.trim().toLowerCase()).join('\u0001');

/** Remove captured chips everywhere (click, dictation or voice): they never come back for that region key. */
export function withoutChips(byRegion: Record<string, string[]>, gone: string[]): Record<string, string[]> {
	const drop = new Set(gone.map((c) => c.trim().toLowerCase()));
	const out: Record<string, string[]> = {};
	for (const [r, cs] of Object.entries(byRegion)) out[r] = cs.filter((c) => !drop.has(c.trim().toLowerCase()));
	return out;
}
