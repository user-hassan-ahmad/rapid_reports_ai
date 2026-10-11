// Scratchpad v2 region state and the confirmed findings block (spec 2026-10-11 §2.1, §6). Pure functions
// of the units: the verbatim text stays the only text; this decides where each region shows.
import type { GateRecord, RegionStates, StackUnit } from './types';

export const TECHNIQUE = 'Technique';
export const GENERAL = 'General';
export const CONCLUSION = 'Conclusion';
export const OTHER = 'Other findings';
const FIXED = new Set([TECHNIQUE, GENERAL, CONCLUSION]);

export interface Item { unitId: number; part: number | null; text: string; group: string; abnormal: boolean }

/** What each unit contributes: a split unit its parts, any other unit itself (attached units already carry
 *  their parent's group from the server). Headings and unplaced units contribute nothing. */
export function effectiveItems(units: StackUnit[]): Item[] {
	const out: Item[] = [];
	for (const u of units) {
		if (u.heading || u.group === null) continue;
		if (u.parts && u.parts.length > 1) {
			u.parts.forEach((p, k) => out.push({ unitId: u.id, part: k, text: p.text, group: p.group, abnormal: !!p.abnormal }));
		} else out.push({ unitId: u.id, part: null, text: u.text, group: u.group, abnormal: !!u.abnormal });
	}
	return out;
}

/** pillRegions: the schema's regions except the catch-all (the tray). */
export function regionStates(units: StackUnit[], pillRegions: string[]): RegionStates {
	const items = effectiveItems(units);
	const abnormal = pillRegions.filter((r) => items.some((i) => i.group === r && i.abnormal));
	const normalWords = (r: string): string[] => {
		const words = new Set<string>();
		for (const i of items) if (i.group === r && !i.abnormal) words.add(i.text);
		for (const u of units) if (!u.heading && !u.abnormal && u.covers.includes(r)) words.add(u.text);
		return [...words];
	};
	const dictatedNormal: RegionStates['dictatedNormal'] = [];
	const assumedNormal: string[] = [];
	for (const r of pillRegions) {
		if (abnormal.includes(r)) continue;
		const words = normalWords(r);
		if (words.length) dictatedNormal.push({ region: r, words });
		else assumedNormal.push(r);
	}
	const remainder = abnormal.filter((r) => normalWords(r).length === 0);
	return { abnormal, dictatedNormal, assumedNormal, remainder };
}

/** Whether a free group (General, Other findings) shows in the scratchpad. */
export function showsGroup(units: StackUnit[], group: string): boolean {
	const items = effectiveItems(units).filter((i) => i.group === group);
	return group === GENERAL ? items.some((i) => i.abnormal) : items.length > 0;
}

export function conclusionText(units: StackUnit[]): string {
	return units.filter((u) => u.group === CONCLUSION && !u.heading).map((u) => u.text).join(' ');
}

/** Changes whenever the findings change (text or placement), the conclusion excluded. */
export function findingsHash(units: StackUnit[]): string {
	const s = units.filter((u) => u.group !== CONCLUSION && !u.heading)
		.map((u) => `${u.text}\u0001${u.group ?? ''}\u0001${u.abnormal ? 1 : 0}`).join('\u0002');
	let h = 0;
	for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
	return `${s.length}:${(h >>> 0).toString(16)}`;
}

/** The regions' own sentences (and the free groups), as the grouped findings text: no gate lines. */
export function findingsText(units: StackUnit[], groups: string[]): string {
	const items = effectiveItems(units);
	const lines: string[] = [];
	const tech = items.filter((i) => i.group === TECHNIQUE).map((i) => i.text);
	if (tech.length) lines.push(tech.join(' '), '');
	for (const g of groups) {
		if (FIXED.has(g)) continue;
		const own = items.filter((i) => i.group === g).map((i) => i.text);
		if (own.length) lines.push(`${g}: ${own.join(' ')}`);
	}
	for (const g of new Set(items.map((i) => i.group))) {
		if (!groups.includes(g) && !FIXED.has(g)) lines.push(`${g}: ${items.filter((i) => i.group === g).map((i) => i.text).join(' ')}`);
	}
	for (const i of items) if (i.group === GENERAL) lines.push(i.text);
	// Fail open: a sentence the grouper never placed still reaches the report, as said.
	for (const u of units) if (u.group === null && !u.heading) lines.push(u.text);
	return lines.join('\n').trim();
}

/** What Generate receives in a stack session (spec §6): the grouped findings, the confirmed normals and the
 *  confirmed conclusion. The generator phrases; it does not get anything the radiologist did not say or confirm. */
export function buildFindingsBlock(units: StackUnit[], groups: string[], gate: GateRecord): string {
	const parts = [findingsText(units, groups)];
	const normals = [...gate.assumed_normal, ...gate.remainder_normal.map((r) => `remainder of ${r}`)];
	if (normals.length) parts.push(`Confirmed normal (not dictated; confirmed by the radiologist): ${normals.join('; ')}.`);
	if (gate.conclusion_text.trim()) parts.push(`Conclusion (confirmed by the radiologist): ${gate.conclusion_text.trim()}`);
	return parts.filter(Boolean).join('\n\n');
}
