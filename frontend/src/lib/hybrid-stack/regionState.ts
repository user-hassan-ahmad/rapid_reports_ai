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

/** Each findings region's own grouped sentences (or split parts), joined: what may cover that region's assumed
 *  normals (Task A3b). Technique, General, Conclusion and unplaced units cover nothing, so a conclusion or a bare
 *  "normal" leaves the template's normals offered. */
export function regionText(units: StackUnit[]): Record<string, string> {
	const out: Record<string, string[]> = {};
	for (const i of effectiveItems(units)) if (!FIXED.has(i.group)) (out[i.group] ??= []).push(i.text);
	return Object.fromEntries(Object.entries(out).map(([g, ts]) => [g, ts.join(' ')]));
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
		.map((u) => `${u.text}\u0001${u.group ?? ''}\u0001${u.abnormal ? 1 : 0}\u0001${(u.parts ?? []).map((p) => `${p.group}:${p.abnormal ? 1 : 0}`).join(',')}`)
		.join('\u0002');
	let h = 0;
	for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
	return `${s.length}:${(h >>> 0).toString(16)}`;
}

/** The regions' own sentences (and the free groups), as the grouped findings text. `extra`: labelled lines appended
 *  to a region's line (answered rows, assumed normals); a region with only extra lines still gets its line. */
export function findingsText(units: StackUnit[], groups: string[], extra: Map<string, string[]> = new Map()): string {
	// A sentence spanning regions goes to the generator whole, once, as dictated, under its joined label (hand read
	// 2026-10-12: fragments under each region lost the sentence); its regions still count as reported.
	const spanning = units.filter((u) => !u.heading && u.group !== null && u.parts && u.parts.length > 1);
	const spanIds = new Set(spanning.map((u) => u.id));
	const items = effectiveItems(units).filter((i) => !spanIds.has(i.unitId));
	const lines: string[] = [];
	const tech = items.filter((i) => i.group === TECHNIQUE).map((i) => i.text);
	if (tech.length) lines.push(tech.join(' '), '');
	for (const g of groups) {
		if (FIXED.has(g)) continue;
		const own = items.filter((i) => i.group === g).map((i) => i.text);
		const more = extra.get(g) ?? [];
		if (own.length || more.length) lines.push(`${g}: ${[...own, ...more].join(' ')}`);
	}
	for (const g of new Set(items.map((i) => i.group))) {
		if (!groups.includes(g) && !FIXED.has(g)) lines.push(`${g}: ${items.filter((i) => i.group === g).map((i) => i.text).join(' ')}`);
	}
	for (const u of spanning) {
		const spans = [...new Set((u.parts ?? []).map((p) => p.group))];
		const ordered = [...groups.filter((g) => spans.includes(g)), ...spans.filter((g) => !groups.includes(g))];
		lines.push(`${ordered.join(' · ')}: ${u.text}`);
	}
	for (const i of items) if (i.group === GENERAL) lines.push(i.text);
	// Fail open: a sentence the grouper never placed still reaches the report, as said.
	for (const u of units) if (u.group === null && !u.heading) lines.push(u.text);
	return lines.join('\n').trim();
}

const ANSWERED = 'Answered by the radiologist:';
const ASSUMED = 'Assumed normal (confirmed by the radiologist):';

/** What Generate receives in a stack session (checklist spec §7): answers only. The radiologist's sentences, the
 *  rows they answered with a tap, the region normals they confirmed, the confirmed conclusion, and what they
 *  removed (never to be asserted). */
export function buildFindingsBlock(units: StackUnit[], groups: string[], gate: GateRecord): string {
	const items = effectiveItems(units);
	const dictatedRegion = (r: string) => items.some((i) => i.group === r);
	const extra = new Map<string, string[]>();
	const add = (r: string, line: string) => extra.set(r, [...(extra.get(r) ?? []), line]);
	const standalone: string[] = [];
	for (const it of gate.items) {
		if (it.answered_by !== 'tap' || !it.sentences.length) continue;
		if (groups.includes(it.region) && (dictatedRegion(it.region) || it.kind === 'finding')) add(it.region, `${ANSWERED} ${it.sentences.join(' ')}`);
		else standalone.push(`${it.region || 'Referral question'} (answered by the radiologist): ${it.sentences.join(' ')}`);
	}
	const tray: string[] = [];
	for (const [r, sentences] of Object.entries(gate.assumed)) {
		if (!sentences.length) continue;
		if (dictatedRegion(r)) add(r, `${ASSUMED} ${sentences.join(' ')}`);
		else tray.push(`${r}: ${sentences.join(' ')}`);
	}
	const parts = [findingsText(units, groups, extra), standalone.join('\n')];
	if (tray.length) parts.push(`${ASSUMED} ${tray.join(' ')}`);
	// Regions with no sentences to confirm (no slim sheet yet): confirmed by name, as v2 did.
	const named = [...gate.assumed_normal.filter((r) => !gate.assumed[r]?.length),
		...gate.remainder_normal.filter((r) => !gate.assumed[r]?.length).map((r) => `remainder of ${r}`)];
	if (named.length) parts.push(`Confirmed normal (not dictated; confirmed by the radiologist): ${named.join('; ')}.`);
	if (gate.conclusion_text.trim()) parts.push(`Conclusion (confirmed by the radiologist): ${gate.conclusion_text.trim()}`);
	if (gate.removed.length) parts.push(`DO NOT ASSERT (removed by the radiologist): ${gate.removed.join(' ')}`);
	return parts.filter(Boolean).join('\n\n');
}
