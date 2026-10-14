// Paired normals (side brief 2026-10-14): a finding dictated on a paired structure without its side leaves out both
// sides' normals and asks "Which side?" until a side is dictated (the next /assumed answer no longer asks). The ask is
// a blocking dictation check placed in its region's card: Confirm walks to it; "Keep without side" answers it, pair by
// pair (review F4). A failed side call keeps the last answer's open asks (review F2). In a region with findings, the
// normals left out are listed, struck through, under a label that says why.
import type { CheckAnswer, CheckFlag } from './checks';
import type { AssumedSnap } from './items';
import type { Dropped, SideAsk } from './types';

export type { SideAsk };

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

export const SIDE_KIND = 'side_missing';
const SEP = ' · ';
const SIDE_MESSAGE = 'A finding here is dictated without its side. Neither side’s normal is reported until you dictate the side.';

/** A pair's answer key: "Keep without side" is kept per pair, so a neighbouring pair joining the region's flag never
 *  re-opens a pair already kept (review F4). */
export const pairKey = (region: string, label: string) => `${SIDE_KIND}|${region}|${norm(label)}`;

/** One blocking check per region, listing its pairs not yet kept without a side, in the order the asks came. */
export function sideFlags(asks: SideAsk[], answers: Record<string, CheckAnswer> = {}): CheckFlag[] {
	const by = new Map<string, string[]>();
	for (const a of asks) if (answers[pairKey(a.region, a.label)] !== 'as_dictated') by.set(a.region, [...(by.get(a.region) ?? []), a.label]);
	return [...by].map(([region, labels]) => ({
		key: `${SIDE_KIND}|${region}`, kind: SIDE_KIND, blocking: true, tier: 2 as const,
		message: SIDE_MESSAGE, quote: labels.join(SEP), other: null, suggestion: '', unitId: null, region
	}));
}

/** The answer to a region flag, recorded on each pair it lists. */
export function answerPairs(flag: CheckFlag, how: CheckAnswer): Record<string, CheckAnswer> {
	return Object.fromEntries(flag.quote.split(SEP).map((l) => [pairKey(flag.region ?? '', l), how]));
}

/** A failed side call (review F2): the last answer's open asks stay, and their sentences stay out of the report, so an
 *  open ask never vanishes and lets Confirm through. A good answer is taken as it is. */
export function carrySides(prev: AssumedSnap | null, res: { assumed: Record<string, string[]>; dropped?: Dropped; side_asks?: SideAsk[] }, failed: boolean) {
	const asks = res.side_asks ?? [];
	if (!failed || !prev?.side_asks?.length) return { assumed: res.assumed, dropped: res.dropped, side_asks: asks };
	const assumed = { ...res.assumed };
	const dropped: Dropped = { ...(res.dropped ?? {}) };
	const carried = [...asks, ...prev.side_asks.filter((p) => !asks.some((a) => a.region === p.region && norm(a.label) === norm(p.label)))];
	for (const a of carried) {
		const out = new Set(a.sentences.map(norm));
		if (assumed[a.region]) assumed[a.region] = assumed[a.region].filter((s) => !out.has(norm(s)));
		const have = new Set((dropped[a.region] ?? []).map((d) => norm(d.sentence)));
		dropped[a.region] = [...(dropped[a.region] ?? []), ...a.sentences.filter((s) => !have.has(norm(s))).map((sentence) => ({ sentence, reason: 'side' }))];
	}
	return { assumed, dropped, side_asks: carried };
}

/** How a "Which side?" ask ended, for the gate (review F5):
 *  - kept_without_side: "Keep without side" was pressed;
 *  - open: the last answer still asks it (Confirm walks to it, so a gate seldom has one);
 *  - sided: the last answer places the pair's finding on the right, the left or both (the side was dictated);
 *  - gone: the last answer places no finding for the pair (the finding was removed or reworded away). */
export type SideEnding = 'kept_without_side' | 'open' | 'sided' | 'gone';

/** Every pair asked this session, with its last score and how it ended. */
export function sideRecord(seen: Record<string, SideAsk>, snap: AssumedSnap | null, answers: Record<string, CheckAnswer>) {
	const key = (a: { region: string; label: string }) => pairKey(a.region, a.label);
	const open = new Set((snap?.side_asks ?? []).map(key));
	const sided = new Set((snap?.side_choices ?? []).filter((c) => c.choice && c.choice !== 'no_side').map(key));
	return Object.values(seen).map((a) => {
		const k = key(a);
		const ended: SideEnding = answers[k] === 'as_dictated' ? 'kept_without_side' : open.has(k) ? 'open' : sided.has(k) ? 'sided' : 'gone';
		return { region: a.region, pair: a.label, score: a.score, answered_by: ended };
	});
}

/** The gate's side per pair Jev placed a finding for, as the Confirm answer read it (bilateral fix). */
export function sideChoices(snap: AssumedSnap | null) {
	return (snap?.side_choices ?? []).filter((c) => !!c.choice).map((c) => ({ region: c.region, pair: c.label, choice: c.choice!, applied: c.applied }));
}

/** Why a normal is left out, as the struck line says it (review F7): a conflict (contradicted, or a bilateral
 *  finding), a side not stated, or a side that could not be checked. */
const WHY: Record<string, string> = {
	contradicted: 'conflicts with dictation', both: 'conflicts with dictation', side: 'side not stated', side_unchecked: 'side not checked'
};
export type NotReported = Record<string, { why: string; sentences: string[] }[]>;

/** Region -> the normals left out for one of those reasons, grouped by reason. Never a removed or a covered one. */
export function notReported(snap: AssumedSnap | null, removed: string[]): NotReported {
	const gone = new Set(removed.map(norm));
	const out: NotReported = {};
	for (const [r, xs] of Object.entries(snap?.dropped ?? {})) {
		const groups = new Map<string, string[]>();
		for (const d of xs) {
			const why = WHY[d.reason];
			if (why && !gone.has(norm(d.sentence))) groups.set(why, [...(groups.get(why) ?? []), d.sentence]);
		}
		if (groups.size) out[r] = [...groups].map(([why, sentences]) => ({ why, sentences }));
	}
	return out;
}
