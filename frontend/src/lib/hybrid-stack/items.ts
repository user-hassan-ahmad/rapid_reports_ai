// Checklist rows (spec 2026-10-11-scratchpad-checklist §3): pure helpers for the view and the scratchpad.
import { effectiveItems } from './regionState';
import type { Dropped, StackItem, StackUnit } from './types';

export const QUIET_MAX = 3;

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

/** The answer button: always "✓ Normal" beside the normal wordings it adds (its title lists them). */
export function answerLabel(_sentences: string[]): string {
	return '✓ Normal';
}

/** Where a finding check sits: under the region of the dictated sentence that set it off (its source_text), so a row
 *  always sits next to the sentence it is about, whichever model placed what (hand read 2026-10-12). Falls back to
 *  the writer's region. */
// A finding row belongs to a findings region: a phrase that also appears in the conclusion (or technique, or a
// sweeping General line) never moves the row there (live 2026-10-12: "perforation" in the conclusion sent the
// appendix row above the cards).
const NOT_FINDINGS = new Set(['Conclusion', 'Technique', 'General']);

export function anchorRegion(item: StackItem, units: StackUnit[]): string {
	const src = norm(item.source_text ?? '');
	if (item.kind !== 'finding' || !src) return item.region;
	for (const u of units) {
		if (u.heading || u.group === null || NOT_FINDINGS.has(u.group)) continue;
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

export interface AssumedSnap { dictation: string; abnormal: string[]; untouched: string[]; assumed: Record<string, string[]>; offered: Record<string, string[]>; dropped?: Dropped; check_failed?: boolean }

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

/** Rows over the writer's caps (E1b): shown behind "N more checks" instead of vanishing. The capped rows still to
 *  show there: not already among the open rows (a later reply may promote one), not skipped. */
export function moreRows(capped: StackItem[], items: StackItem[], skipped: string[]): StackItem[] {
	const open = new Set(items.map((i) => i.id));
	return capped.filter((c) => !open.has(c.id) && !skipped.includes(c.id));
}

/** A quiet re-check sends the open and the capped rows together; its reply is split back by where each row came from,
 *  so the re-check never promotes a capped row onto the checklist. A capped row the dictation answered joins the
 *  rows (it shows green and folds like any row); one still asked stays capped. */
export function splitRecheck(res: { items: StackItem[]; capped: StackItem[] }, cappedIds: string[]): { items: StackItem[]; capped: StackItem[] } {
	const was = new Set(cappedIds);
	const all = [...res.items, ...res.capped];
	return {
		items: all.filter((r) => !was.has(r.id) || r.answered),
		capped: all.filter((r) => was.has(r.id) && !r.answered)
	};
}
