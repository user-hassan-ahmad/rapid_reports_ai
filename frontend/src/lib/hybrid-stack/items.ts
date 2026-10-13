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

export interface AssumedSnap { dictation: string; abnormal: string[]; untouched: string[]; assumed: Record<string, string[]>; offered: Record<string, string[]>; dictatedNormal?: string[]; flagged?: Record<string, string[]>; dropped?: Dropped; check_failed?: boolean; confirm_recheck?: boolean; confirmed?: boolean; failures?: number }

/** What the gate confirms as assumed: only the sentences /assumed answered for each region, in the state (abnormal
 *  or untouched) that region had when they were checked, minus removed ones. Never the raw sheet (review
 *  2026-10-12: a region missing from the reply fell back to the sheet; an untouched region's normals stayed
 *  assumed after it turned abnormal). Until /assumed answers, nothing is assumed. */
/** The /assumed answer is behind: a sheet exists and no answer was computed for this exact dictation. An answer for
 *  the empty dictation (the check run when the sheet loads, E6) is current until something is dictated. */
export function assumedStale(hasSheet: boolean, snap: AssumedSnap | null, dictation: string): boolean {
	if (!hasSheet) return false;
	if (snap === null || snap.dictation !== dictation) return true;
	// A failed answer for the empty dictation (the sheet load's rule call, round 1) is asked again, up to three tries,
	// so the tray recovers; once something is dictated a failure fails open, as before.
	return !!snap.check_failed && !dictation.trim() && (snap.failures ?? 1) < ASSUMED_RETRIES;
}
export const ASSUMED_RETRIES = 3;

/** A dictated-normal region (review R2) keeps the sentences the check left: the stated check removed what was said,
 *  so "ACL intact" keeps the PCL sentence. Like the others, only when it was checked in that same state. */
export function assumedFrom(snap: AssumedSnap | null, abnormal: string[], untouched: string[], removed: string[], dictatedNormal: string[] = []): Record<string, string[]> {
	if (!snap) return {};
	const gone = new Set(removed.map(norm));
	const out: Record<string, string[]> = {};
	const same = (r: string) =>
		abnormal.includes(r) ? snap.abnormal.includes(r) : dictatedNormal.includes(r) ? (snap.dictatedNormal ?? []).includes(r) : snap.untouched.includes(r);
	for (const r of [...abnormal, ...dictatedNormal, ...untouched]) {
		if (!same(r)) continue;
		const kept = (snap.assumed[r] ?? []).filter((x) => !gone.has(norm(x)));
		if (kept.length) out[r] = kept;
	}
	return out;
}

/** The assumed sentences the dictation may conflict with (review R1): Jev half-read them as covered or contradicted,
 *  so they are kept, highlighted, for the radiologist to confirm or remove. Only those `assumedFrom` still keeps. */
export function flaggedFrom(snap: AssumedSnap | null, abnormal: string[], untouched: string[], removed: string[], dictatedNormal: string[] = []): Record<string, string[]> {
	if (!snap?.flagged) return {};
	const out: Record<string, string[]> = {};
	for (const [r, xs] of Object.entries(assumedFrom(snap, abnormal, untouched, removed, dictatedNormal))) {
		const mine = new Set((snap.flagged[r] ?? []).map(norm));
		const kept = xs.filter((x) => mine.has(norm(x)));
		if (kept.length) out[r] = kept;
	}
	return out;
}

/** Whether `s` is flagged in one of `regions` (by region and normalised text: the same words elsewhere are not). */
export function isFlagged(flagged: Record<string, string[]>, regions: string[], s: string): boolean {
	return regions.some((r) => (flagged[r] ?? []).some((x) => norm(x) === norm(s)));
}

/** What a Confirm answer adds to what the radiologist was shown (round 1): a sentence now assumed, or now flagged, in
 *  a region that did not show it before (a rule the dictation un-hid, a row moving into the tray). Anything added is
 *  shown first and Confirm waits for another press; removals alone let it through. */
export function addedAtConfirm(before: { assumed: Record<string, string[]>; flagged: Record<string, string[]> },
	after: { assumed: Record<string, string[]>; flagged: Record<string, string[]> }): string[] {
	const added = (b: Record<string, string[]>, a: Record<string, string[]>) =>
		Object.entries(a).flatMap(([r, xs]) => xs.filter((x) => !(b[r] ?? []).some((y) => norm(y) === norm(x))));
	return [...new Set([...added(before.assumed, after.assumed), ...added(before.flagged, after.flagged)])];
}

/** The session's template context-rule decision (review R5): condition -> P(met), decided once from the clinical
 *  history by the first good /assumed reply (the workspace load), as `fixedReferrals` is for the referral rows. */
export interface SessionRules { history: string; rules: Record<string, number> }

/** What the next /assumed sends: the kept decision while the history is the one it was decided from; else null, and
 *  the server decides (one call). */
export function rulesToSend(fixed: SessionRules | null, history: string): Record<string, number> | null {
	return fixed && fixed.history === history ? fixed.rules : null;
}

/** The first good reply's decision is kept; later replies never replace it. A failed reply keeps nothing. */
export function keepRules(fixed: SessionRules | null, history: string, res: { rules?: Record<string, number> | null; error?: string | null }): SessionRules | null {
	if (rulesToSend(fixed, history)) return fixed;
	return res.rules && !res.error ? { history, rules: res.rules } : null;
}

/** Confirm records the gate only on an answer computed at Confirm (`confirmed`: every rule re-asked with the
 *  dictation) for the dictation now on screen (review round 1): never on a live answer. */
export function confirmReady(snap: AssumedSnap | null, dictation: string): boolean {
	return !!snap?.confirmed && snap.dictation === dictation;
}

/** The Confirm re-ask failed where the live answer it replaced had not (re-review minor): Confirm must not gate the
 *  emptied tray a failure leaves; the live answer is kept and the radiologist confirms again. */
export function confirmRecheckFailed(live: AssumedSnap | null, after: AssumedSnap | null): boolean {
	return !!after?.confirmed && !!after.check_failed && !live?.check_failed;
}

/** The key a recorded gate is valid for: the scan type first, so a gate never survives a scan-type change. */
export function gateKeyOf(scanType: string, parts: string[]): string {
	return [scanType, ...parts].join('\u0003');
}

/** Rows over the writer's caps (E1b): shown behind one quiet "N more checks" line instead of vanishing. `rows`: the
 *  capped rows to show there (not already among the open rows, not skipped); `waiting`: N, the ones still asked;
 *  `show`: the line is shown while any is asked or a tapped answer sits behind it. */
export function moreLine(capped: StackItem[], items: StackItem[], tapped: string[], removed: string[], skipped: string[]): { rows: StackItem[]; waiting: number; show: boolean } {
	const open = new Set(items.map((i) => i.id));
	const rows = capped.filter((c) => !open.has(c.id) && !skipped.includes(c.id));
	const waitingN = rows.filter((r) => waiting(r, tapped, removed, skipped)).length;
	return { rows, waiting: waitingN, show: waitingN > 0 || rows.some((r) => tapped.includes(r.id)) };
}

/** Where each row of an /items or re-check reply goes: the checklist or behind the line. A row the dictation answered
 *  that was behind the line folds there, quietly, never among the region cards. A quiet re-check never moves a row:
 *  it saw the capped rows only to fold the answered ones. A full reply's caps decide the rest (it may promote one). */
export function splitReply(res: { items: StackItem[]; capped: StackItem[] }, wasCapped: string[], wasOpen: string[], recheck: boolean): { items: StackItem[]; capped: StackItem[] } {
	const capped = new Set(wasCapped);
	const open = new Set(wasOpen);
	const behind = (r: StackItem) => capped.has(r.id) && (recheck || (r.answered && !open.has(r.id)));
	// A re-check's capped row that was not behind the line before (an open row its caps pushed out) stays on the
	// checklist: a re-check never loses a row.
	const stays = (r: StackItem) => !recheck || capped.has(r.id);
	return {
		items: [...res.items.filter((r) => !behind(r)), ...res.capped.filter((r) => !stays(r))],
		capped: [...res.items.filter(behind), ...res.capped.filter(stays)]
	};
}
