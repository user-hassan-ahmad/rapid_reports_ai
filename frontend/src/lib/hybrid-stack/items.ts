// Checklist rows (spec 2026-10-11-scratchpad-checklist §3): pure helpers for the view and the scratchpad.
import { effectiveItems } from './regionState';
import type { StackItem, StackUnit } from './types';

export const QUIET_MAX = 3;

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

/** The answer button: always "✓ Normal" beside the normal wordings it adds (its title lists them). */
export function answerLabel(_sentences: string[]): string {
	return '✓ Normal';
}

/** Where a finding check sits: under the region of the dictated sentence that set it off (its source_text), so a row
 *  always sits next to the sentence it is about, whichever model placed what (hand read 2026-10-12). Falls back to
 *  the writer's region. */
export function anchorRegion(item: StackItem, units: StackUnit[]): string {
	const src = norm(item.source_text ?? '');
	if (item.kind !== 'finding' || !src) return item.region;
	for (const u of units) {
		if (u.heading || u.group === null) continue;
		if (u.parts && u.parts.length > 1) {
			const part = u.parts.find((p) => norm(p.text).includes(src));
			if (part) return part.group;
			if (norm(u.text).includes(src)) return u.parts[0].group;
		} else if (norm(u.text).includes(src)) return u.group;
	}
	return item.region;
}

/** The sentences a tap will add: the row's own, minus any the radiologist removed with ×. */
export function rowSentences(item: StackItem, removed: string[]): string[] {
	const gone = new Set(removed.map(norm));
	return item.sentences.filter((s) => !gone.has(norm(s)));
}

export const waiting = (i: StackItem, tapped: string[], removed: string[], skipped: string[]) =>
	!i.answered && !tapped.includes(i.id) && !skipped.includes(i.id) && rowSentences(i, removed).length > 0;

/** Referral rows still waiting: the gate stays locked while any is open (the clinical question is always answered:
 *  ✓, dictated, or "Not assessed"). */
export function openCount(items: StackItem[], tapped: string[], removed: string[], skipped: string[] = []): number {
	return items.filter((i) => i.kind === 'referral' && waiting(i, tapped, removed, skipped)).length;
}

/** Finding checks left unanswered: they never block; nothing is stated for them. */
export function unansweredChecks(items: StackItem[], tapped: string[], removed: string[], skipped: string[] = []): number {
	return items.filter((i) => i.kind === 'finding' && waiting(i, tapped, removed, skipped)).length;
}

export function quietLine(sentences: string[], max = QUIET_MAX): { shown: string[]; more: number } {
	return { shown: sentences.slice(0, max), more: Math.max(0, sentences.length - max) };
}

/** Every abnormal sentence, parts included: the writer's cache key (its rows change only when these change). */
export function abnormalAll(units: StackUnit[]): string[] {
	return effectiveItems(units).filter((i) => i.abnormal).map((i) => i.text);
}

export interface AssumedSnap { dictation: string; abnormal: string[]; untouched: string[]; assumed: Record<string, string[]> }

/** What the gate confirms as assumed: only the sentences /assumed answered for each region, in the state (abnormal
 *  or untouched) that region had when they were checked, minus removed ones. Never the raw sheet (review
 *  2026-10-12: a region missing from the reply fell back to the sheet; an untouched region's normals stayed
 *  assumed after it turned abnormal). Until /assumed answers, nothing is assumed. */
export function assumedFrom(snap: AssumedSnap | null, abnormal: string[], untouched: string[], removed: string[]): Record<string, string[]> {
	if (!snap) return {};
	const gone = new Set(removed.map(norm));
	const out: Record<string, string[]> = {};
	const same = (r: string) => (abnormal.includes(r) ? snap.abnormal.includes(r) : snap.untouched.includes(r));
	for (const r of [...abnormal, ...untouched]) {
		if (!same(r)) continue;
		const kept = (snap.assumed[r] ?? []).filter((x) => !gone.has(norm(x)));
		if (kept.length) out[r] = kept;
	}
	return out;
}
