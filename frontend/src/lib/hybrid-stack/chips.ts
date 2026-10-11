// Check chips (spec 2026-10-11 §4): the finding-linked negatives of each abnormal region. An included chip is in
// the report unless the radiologist removes it (and is confirmed at the gate); an optional one is opt-in.
import { effectiveItems } from './regionState';
import type { Chip, StackUnit } from './types';

export const PER_REGION = 3;
export const ON_SCREEN = 6;

export interface VisibleChip extends Chip { region: string }

/** Included chips always show (they will be stated); optional chips fill the screen up to ON_SCREEN. */
export function visibleChips(byRegion: Record<string, Chip[]>, abnormalRegions: string[]): VisibleChip[] {
	const all = abnormalRegions.flatMap((region) => (byRegion[region] ?? []).slice(0, PER_REGION).map((c) => ({ ...c, region })));
	const included = all.filter((c) => c.state === 'included');
	const room = Math.max(0, ON_SCREEN - included.length);
	const optional = all.filter((c) => c.state === 'optional').slice(0, room);
	return all.filter((c) => included.includes(c) || optional.includes(c));
}

export function includedChips(byRegion: Record<string, Chip[]>, abnormalRegions: string[]): { region: string; text: string }[] {
	return visibleChips(byRegion, abnormalRegions).filter((c) => c.state === 'included').map(({ region, text }) => ({ region, text }));
}

/** The region's abnormal sentences: what its chips are asked for, and the key that re-asks them on change. */
export function abnormalSentences(units: StackUnit[], region: string): string[] {
	return effectiveItems(units).filter((i) => i.group === region && i.abnormal).map((i) => i.text);
}

export const sentencesKey = (sentences: string[]): string => sentences.map((s) => s.trim().toLowerCase()).join('\u0001');

const norm = (s: string) => s.trim().toLowerCase();

/** Chips removed, stated or contradicted: gone everywhere, and never offered again this session. */
export function withoutChips(byRegion: Record<string, Chip[]>, gone: string[]): Record<string, Chip[]> {
	const drop = new Set(gone.map(norm));
	const out: Record<string, Chip[]> = {};
	for (const [r, cs] of Object.entries(byRegion)) out[r] = cs.filter((c) => !drop.has(norm(c.text)));
	return out;
}

export function withState(byRegion: Record<string, Chip[]>, text: string, state: Chip['state']): Record<string, Chip[]> {
	const out: Record<string, Chip[]> = {};
	for (const [r, cs] of Object.entries(byRegion)) out[r] = cs.map((c) => (norm(c.text) === norm(text) ? { ...c, state } : c));
	return out;
}
