/**
 * Editor marks for the dictation audit (tier 1 regex, tier 2 model or Jev). Each flag marks
 * its own span; a conflict between two statements also marks the other one, more lightly.
 * A flag is dropped as soon as the user edits its text: the next check (0.6 s later in the
 * lab) decides whether it still stands.
 */

export interface FlagLike {
	kind?: string;
	message?: string;
	start?: number;
	end?: number;
	from?: number;
	to?: number;
	related_start?: number | null;
	related_end?: number | null;
}

export interface IntegrityMark {
	from: number;
	to: number;
	kind: string;
	message: string;
	related: boolean;
}

export function integrityMarks(flags: FlagLike[], docLength = Infinity): IntegrityMark[] {
	const ok = (a: number, b: number) => a >= 0 && b <= docLength && a < b;
	const out: IntegrityMark[] = [];
	for (const f of flags) {
		const from = f.start ?? f.from ?? -1;
		const to = f.end ?? f.to ?? -1;
		if (!ok(from, to)) continue;
		const kind = f.kind ?? 'flag';
		const message = f.message ?? '';
		out.push({ from, to, kind, message, related: false });
		const rs = f.related_start;
		const re = f.related_end;
		if (rs != null && re != null && ok(rs, re)) {
			out.push({ from: rs, to: re, kind, message: `Conflicts with a later statement: ${message}`, related: true });
		}
	}
	return out;
}

/** Whether a change [fromA, toA) (old-document positions) edits the span [from, to).
 *  Text inserted exactly at either edge (dictation appending) does not. */
export function editTouches(fromA: number, toA: number, from: number, to: number): boolean {
	if (fromA === toA) return fromA > from && fromA < to;
	return fromA < to && toA > from;
}
