// Protocol library (spec 2026-10-13-protocol-library-design §3–4): the pick, quiet regions and segment level lines.
export type ProtocolVariant = { phases: string[]; line: string; default: boolean };
export type ProtocolOption = {
	id: string; display_name: string; protocol_line: string; laterality: 'none' | 'required'; variants: ProtocolVariant[];
};
export type ProtocolSearch = { options: ProtocolOption[]; not_listed_hint: boolean; promoted: string | null };
export type ProtocolPick = { id: string; phases: string[]; laterality: string | null; displayName: string; line: string };

export function pickBody(pick: ProtocolPick | null): { protocol_id?: string; phases?: string[]; laterality?: string | null } {
	return pick ? { protocol_id: pick.id, phases: pick.phases, laterality: pick.laterality } : {};
}

/** The pick's identity for the slim sheet: a different id, phase set or side has different normals. '' = no pick. */
export function pickKey(pick: ProtocolPick | null): string {
	return pick ? [pick.id, pick.phases.join(','), pick.laterality ?? ''].join('\u0001') : '';
}

/** A scan type with no pick behind it (a restored draft, an opened report, a revert) belongs in the free-text box. */
export function needsFreeText(scanType: string, pick: ProtocolPick | null): boolean {
	return !!scanType.trim() && !pick;
}

/** Pills in schema order: every non-quiet pill, plus a quiet region once something has been placed there. */
export function visiblePills(groups: string[], pills: string[], quiet: string[], placed: Set<string>): string[] {
	if (!quiet.length) return pills;
	const show = new Set([...pills, ...quiet.filter((q) => placed.has(q))]);
	return groups.filter((g) => show.has(g));
}

const lowerFirst = (s: string) => (s.length > 1 && s[1] === s[1].toUpperCase() && /[A-Z]/.test(s[1]) ? s : s[0].toLowerCase() + s.slice(1));

/** A segment's normal line reads "Elsewhere, …" once any level in that segment has been dictated. */
export function withElsewhere(
	assumed: Record<string, string[]>, levelGroups: Record<string, string[]>, dictated: Set<string>
): Record<string, string[]> {
	const out: Record<string, string[]> = { ...assumed };
	for (const [group, levels] of Object.entries(levelGroups)) {
		if (!out[group] || !levels.some((l) => dictated.has(l))) continue;
		out[group] = out[group].map((s) => (s.startsWith('Elsewhere') ? s : `Elsewhere, ${lowerFirst(s)}`));
	}
	return out;
}
