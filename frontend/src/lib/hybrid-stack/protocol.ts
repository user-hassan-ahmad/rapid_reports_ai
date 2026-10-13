// Protocol library (spec 2026-10-13-protocol-library-design §3–4): the pick, quiet regions and segment level lines.
import { effectiveItems } from './regionState';
import type { StackUnit } from './types';
export type ProtocolVariant = { phases: string[]; line: string; default: boolean };
export type ProtocolOption = {
	id: string; display_name: string; protocol_line: string; laterality: 'none' | 'required'; variants: ProtocolVariant[];
};
export type ProtocolSearch = { options: ProtocolOption[]; not_listed_hint: boolean; promoted: string | null };
export type ProtocolPick = { id: string; phases: string[]; laterality: string | null; displayName: string; line: string };

export function pickBody(pick: ProtocolPick | null): { protocol_id?: string; phases?: string[]; laterality?: string | null } {
	return pick ? { protocol_id: pick.id, phases: pick.phases, laterality: pick.laterality } : {};
}

/** The committed pick as the picker's summary shows it: "MRI Knee (left)" and the protocol line ("No contrast"). */
export function pickSummary(pick: ProtocolPick): { name: string; line: string } {
	return { name: pick.displayName + (pick.laterality ? ` (${pick.laterality})` : ''), line: pick.line };
}

/** The pick's identity for the slim sheet: a different id, phase set or side has different normals. '' = no pick. */
export function pickKey(pick: ProtocolPick | null): string {
	return pick ? [pick.id, pick.phases.join(','), pick.laterality ?? ''].join('\u0001') : '';
}

/** A scan type with no pick behind it (a restored draft, an opened report, a revert) belongs in the free-text box. */
export function needsFreeText(scanType: string, pick: ProtocolPick | null): boolean {
	return !!scanType.trim() && !pick;
}

/** "Pick from the library" from free text: the typed text moves to the picker's search box and the scan type empties,
 *  so `needsFreeText` does not send the box straight back to free text. */
export function backToLibrary(scanType: string): { query: string; scanType: string; pick: null; freeText: false } {
	return { query: scanType.trim(), scanType: '', pick: null, freeText: false };
}

/** What a workspace is built from: the scan type, the history and the pick (null: free text). */
export type CaseIdentity = { scanType: string; history: string; pick: ProtocolPick | null };

/** The case details differ from the workspace's: the scan type, the history, or the pick (another phase set or side
 *  is a different case even when the display name is the same). `built` holds trimmed values. */
export function caseDirty(now: CaseIdentity, built: CaseIdentity): boolean {
	return now.scanType.trim() !== built.scanType || now.history.trim() !== built.history || pickKey(now.pick) !== pickKey(built.pick);
}

/** Pills in schema order: every non-quiet pill, plus a quiet region once something has been placed there. A quiet
 *  region among `pills` is dropped unless placed (the scratchpad passes every stack region). */
export function visiblePills(groups: string[], pills: string[], quiet: string[], placed: Set<string>): string[] {
	if (!quiet.length) return pills;
	const isQuiet = new Set(quiet);
	const show = new Set([...pills.filter((p) => !isQuiet.has(p)), ...quiet.filter((q) => placed.has(q))]);
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

/** A normal's identity for removal: the same sentence with or without the "Elsewhere, " lead, case and the full stop
 *  ignored, so × or an edit on either form removes both. */
export function assumedKey(s: string): string {
	return s.trim().replace(/^elsewhere,\s*/i, '').toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');
}

/** The assumed normals minus every removed (or edited) sentence, in either form; regions left empty are dropped. */
export function withoutRemoved(assumed: Record<string, string[]>, removed: string[]): Record<string, string[]> {
	if (!removed.length) return assumed;
	const gone = new Set(removed.map(assumedKey));
	const out: Record<string, string[]> = {};
	for (const [r, xs] of Object.entries(assumed)) {
		const kept = xs.filter((x) => !gone.has(assumedKey(x)));
		if (kept.length) out[r] = kept;
	}
	return out;
}

/** The region normals the /assumed check sees: every region but the segments. A segment's normal is decided here
 *  (E1, e2e 2026-10-13): the check read the segment line against the whole dictation, with no notion of which levels
 *  are the segment's, and dropped all three segments once any level was dictated. */
export function withoutSegments(normals: Record<string, string[]>, levelGroups: Record<string, string[]>): Record<string, string[]> {
	const out: Record<string, string[]> = {};
	for (const [r, xs] of Object.entries(normals)) if (!(r in levelGroups)) out[r] = xs;
	return out;
}

/** The checked normals plus each segment's sheet line while its own region is untouched (nothing placed there).
 *  A segment never takes its line from the check, even from a stale answer. */
export function withSegmentNormals(
	checked: Record<string, string[]>, normals: Record<string, string[]>, levelGroups: Record<string, string[]>, untouched: string[],
	blocked: Set<string> = new Set()
): Record<string, string[]> {
	const out = withoutSegments(checked, levelGroups);
	for (const seg of Object.keys(levelGroups)) if (normals[seg]?.length && untouched.includes(seg) && !blocked.has(seg)) out[seg] = normals[seg];
	return out;
}

/** What the tray, the counts and the gate's `assumed` record hold: the checked normals and the untouched segments'
 *  lines, a segment reading "Elsewhere, …" once one of its levels has something placed, minus every removal. */
export function shownNormals(
	checked: Record<string, string[]>, normals: Record<string, string[]>, levelGroups: Record<string, string[]>,
	untouched: string[], placed: Set<string>, removed: string[], blocked: Set<string> = new Set()
): Record<string, string[]> {
	return withoutRemoved(withElsewhere(withSegmentNormals(checked, normals, levelGroups, untouched, blocked), levelGroups, placed), removed);
}

/** Regions with something placed in them: every split part counts, not only the unit's first group (re-review of
 *  74eab7ec). The same source `regionStates` reads; headings and unplaced units place nothing. */
export function placedRegions(units: StackUnit[]): Set<string> {
	return new Set(effectiveItems(units).map((i) => i.group));
}

const MULTILEVEL = /\bmulti-?\s?level\b/i;
const esc = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A level label ("C5/6", "T12/L1", "L5/S1") as written in dictation: "/", "-" or a dash between, the second letter
 *  optional when it repeats the first ("C5-C6"), spaces allowed; never inside a longer label ("C5/67", "AC5/6"). */
function levelPattern(label: string): RegExp {
	const m = /^([A-Za-z])\s*(\d+)\s*\/\s*([A-Za-z])?\s*(\d+)$/.exec(label.trim());
	if (!m) return new RegExp(`(?<![A-Za-z0-9])${esc(label.trim())}(?![0-9])`, 'i');
	const [, a, n1, b, n2] = m;
	const second = !b || b.toLowerCase() === a.toLowerCase() ? `(?:${a}\\s*)?` : `${b}\\s*`;
	return new RegExp(`(?<![A-Za-z0-9])${a}\\s*${n1}\\s*[/\\-\u2013\u2014]\\s*${second}${n2}(?![0-9])`, 'i');
}

/** The junction words that name two segments each (ruling): thoracolumbar, cervicothoracic, and lumbosacral. */
const SEGMENT_WORDS: Record<string, string[]> = {
	cervical: ['cervical', 'cervicothoracic'],
	thoracic: ['thoracic', 'cervicothoracic', 'thoracolumbar'],
	lumbar: ['lumbar', 'lumbosacral', 'thoracolumbar']
};

/** The segment named in prose, as whole words in any case: "Cervical levels" → cervical or cervicothoracic. */
function segmentWords(segment: string): RegExp {
	const word = segment.trim().split(/\s+/)[0].toLowerCase();
	const words = SEGMENT_WORDS[word] ?? [word];
	return new RegExp(`\\b(?:${words.map(esc).join('|')})\\b`, 'i');
}

/** Misfiled-finding backstop for a segment's sheet line (controller ruling, re-review of 74eab7ec): withheld when an
 *  abnormal sentence placed outside the segment's own regions names one of its levels or the segment itself, or when
 *  any abnormal sentence says "multilevel". Deterministic and errs toward omission; `abnormal` holds abnormal (or not
 *  yet grouped) sentences only, so a placed normal mention ("normal cervical lordosis") never withholds the line. */
export function segmentBlocked(segment: string, levels: string[], abnormal: { group: string | null; text: string }[]): boolean {
	const own = new Set([segment, ...levels]);
	const pats = [segmentWords(segment), ...levels.map(levelPattern)];
	return abnormal.some(({ group, text }) => MULTILEVEL.test(text) || (!(group !== null && own.has(group)) && pats.some((p) => p.test(text))));
}

/** The segments whose sheet line is withheld, from every abnormal sentence (split parts, General, Other findings) and
 *  every ungrouped tail unit whatever its flag (ruling: its state is not known yet). */
export function blockedSegments(levelGroups: Record<string, string[]>, units: StackUnit[]): Set<string> {
	const abnormal: { group: string | null; text: string }[] = [];
	for (const u of units) {
		if (u.heading) continue;
		if (u.group === null) abnormal.push({ group: null, text: u.text });
		else if (u.parts && u.parts.length > 1) for (const p of u.parts) { if (p.abnormal) abnormal.push({ group: p.group, text: p.text }); }
		else if (u.abnormal) abnormal.push({ group: u.group, text: u.text });
	}
	if (!abnormal.length) return new Set();
	return new Set(Object.entries(levelGroups).filter(([seg, levels]) => segmentBlocked(seg, levels, abnormal)).map(([seg]) => seg));
}
