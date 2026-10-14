// Paired normals (side brief 2026-10-14): a finding dictated on a paired structure without its side leaves out both
// sides' normals and asks "Which side?" until a side is dictated (the next /assumed answer no longer asks). The ask is
// a blocking dictation check placed in its region's card: Confirm walks to it; "Keep without side" answers it.
// In a region with findings, the normals left out because they conflict with the dictation are listed, struck through.
import type { CheckAnswer, CheckFlag } from './checks';
import type { AssumedSnap } from './items';
import type { SideAsk } from './types';

export type { SideAsk };

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

export const SIDE_KIND = 'side_missing';
const SIDE_MESSAGE = 'A finding here is dictated without its side. Neither side’s normal is reported until you dictate the side.';

/** One blocking check per region, in the order the asks came. */
export function sideFlags(asks: SideAsk[]): CheckFlag[] {
	const by = new Map<string, string[]>();
	for (const a of asks) by.set(a.region, [...(by.get(a.region) ?? []), a.label]);
	return [...by].map(([region, labels]) => ({
		key: `${SIDE_KIND}|${region}|${labels.map(norm).join('|')}`, kind: SIDE_KIND, blocking: true, tier: 2 as const,
		message: SIDE_MESSAGE, quote: labels.join(' · '), other: null, suggestion: '', unitId: null, region
	}));
}

/** The gate's evidence: every ask seen this session and how it ended (kept without a side, gone because the
 *  dictation now gives the side or no longer has the finding, or still open). */
export function sideRecord(seen: Record<string, CheckFlag>, live: CheckFlag[], answers: Record<string, CheckAnswer>) {
	const open = new Set(live.map((f) => f.key));
	return Object.values(seen).map((f) => ({
		region: f.region ?? '', pairs: f.quote.split(' · '),
		answered_by: answers[f.key] === 'as_dictated' ? ('as_dictated' as const) : open.has(f.key) ? ('open' as const) : ('dictated' as const)
	}));
}

/** Region -> normals left out because they conflict with the dictation: contradicted, or a side not dictated. Never a
 *  removed or a covered one. */
export function notReported(snap: AssumedSnap | null, removed: string[]): Record<string, string[]> {
	const gone = new Set(removed.map(norm));
	const out: Record<string, string[]> = {};
	for (const [r, xs] of Object.entries(snap?.dropped ?? {})) {
		const kept = xs.filter((d) => (d.reason === 'contradicted' || d.reason === 'side') && !gone.has(norm(d.sentence))).map((d) => d.sentence);
		if (kept.length) out[r] = kept;
	}
	return out;
}
