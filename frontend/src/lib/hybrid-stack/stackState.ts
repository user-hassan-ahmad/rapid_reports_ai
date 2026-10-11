import type { StackUnit, StackView, ViewGroup, ViewRow } from './types';

const row = (u: StackUnit, text = u.text, partOf: number | null = null): ViewRow => ({
	unitId: u.id, text, structure: u.structure, partOf, pinned: u.pinned, children: []
});

/** The grouped view: groups in schema order, sentences in dictated order, attached sentences nested
 *  under their parent, heading-only sentences hidden, unplaced sentences kept apart ("just dictated"). */
export const JOIN = ' · ';

/** A sentence that spans regions is never cut up (hand read 2026-10-12): it stays whole, as dictated, under one
 *  heading joining its regions ("Pleura · Lungs and airways"), placed where its first region sits. */
export function buildView(units: StackUnit[], groups: string[]): StackView {
	const rows = new Map<string, ViewRow[]>(groups.map((g) => [g, []]));
	const members = new Map<string, string[]>(groups.map((g) => [g, [g]]));
	const byId = new Map<number, ViewRow>();
	const unplaced: ViewRow[] = [];
	const add = (g: string, r: ViewRow) => {
		if (!rows.has(g)) rows.set(g, []);
		rows.get(g)!.push(r);
	};
	for (const u of units) {
		if (u.heading) continue;
		if (u.group === null) {
			unplaced.push(row(u));
			continue;
		}
		if (u.attach_to !== null && byId.has(u.attach_to)) {
			byId.get(u.attach_to)!.children.push(row(u));
			continue;
		}
		if (u.parts && u.parts.length > 1) {
			const spans = [...new Set(u.parts.map((p) => p.group))];
			const ordered = [...groups.filter((g) => spans.includes(g)), ...spans.filter((g) => !groups.includes(g))];
			const name = ordered.length > 1 ? ordered.join(JOIN) : ordered[0];
			const r = row(u);
			byId.set(u.id, r);
			add(name, r);
			members.set(name, ordered);
			continue;
		}
		const r = row(u);
		byId.set(u.id, r);
		add(u.group, r);
	}
	const at = (name: string) => {
		const k = groups.indexOf((members.get(name) ?? [name])[0]);
		return k < 0 ? groups.length : k;
	};
	const out: ViewGroup[] = [];
	for (const [name, rs] of rows) if (rs.length) out.push({ name, rows: rs, members: members.get(name) ?? [name] });
	out.sort((a, b) => at(a.name) - at(b.name) || (a.members.length - b.members.length));
	return { groups: out, unplaced };
}

/** A drag to another group: the sentence is pinned there (the server never changes it again). */
export function moveUnit(units: StackUnit[], id: number, group: string): StackUnit[] {
	return units.map((u) => (u.id === id ? { ...u, group, pinned: true, attach_to: null, parts: null } : u));
}

/** Where the server's split starts a sentence (units.py): the start of the text, after a line break, or after
 *  whitespace that follows . ? ! */
function startsSentence(text: string, pos: number): boolean {
	if (pos === 0) return true;
	let k = pos - 1;
	if (!/\s/.test(text[k])) return false;
	while (k >= 0 && /\s/.test(text[k])) {
		if (text[k] === '\n') return true;
		k -= 1;
	}
	return k < 0 || /[.?!]/.test(text[k]);
}

/** Character offset of unit `id` in the verbatim text (the nth occurrence of its text where a sentence starts),
 *  so "Unremarkable." never matches inside "Pancreas: Unremarkable.". */
export function sentenceOffset(text: string, units: StackUnit[], id: number): number {
	const target = units.find((u) => u.id === id);
	if (!target) return -1;
	const nth = units.filter((u) => u.id < id && u.text === target.text).length;
	let seen = 0;
	for (let pos = text.indexOf(target.text); pos >= 0; pos = text.indexOf(target.text, pos + 1)) {
		const end = pos + target.text.length;
		if (startsSentence(text, pos) && (end === text.length || /\s/.test(text[end]))) {
			if (seen === nth) return pos;
			seen += 1;
		}
	}
	return -1;
}

const SPLIT = /(?<=[.?!])\s+(?=\S)|\n+/;
const LIST_NUMBER = /^\d{1,2}\.$/;
const joinsNext = (frag: string, next: string): boolean =>
	LIST_NUMBER.test(frag) ||
	(frag.length <= 8 && frag.endsWith('.') && !/\s/.test(frag) && /^[a-z0-9]/.test(next));

/** The sentence units of the verbatim text, split as the server does (backend hybrid_stack/units.py). */
export function sentences(text: string): string[] {
	const frags = (text ?? '').split(SPLIT).map((s) => s.trim()).filter(Boolean);
	const out: string[] = [];
	for (let i = 0; i < frags.length; i++) {
		let cur = frags[i];
		while (i + 1 < frags.length && joinsNext(cur, frags[i + 1])) cur = `${cur} ${frags[++i]}`;
		out.push(cur);
	}
	return out;
}

/** Sentences of the verbatim text that no unit holds yet: shown at once under "Just dictated" while the
 *  grouper places them (no round trip before the radiologist sees their words). */
/** The text with its last sentence held back (hand read 2026-10-12): while recording, the sentence being spoken
 *  can still grow or be re-punctuated by the next utterance, so it stays in the live strip and is grouped only
 *  once the next sentence starts or recording stops. Each sentence then moves into its region once. */
export function closedText(verbatim: string): string {
	const all = sentences(verbatim);
	if (all.length < 2) return '';
	const last = all[all.length - 1];
	const at = verbatim.lastIndexOf(last);
	return at > 0 ? verbatim.slice(0, at).trimEnd() : '';
}

const words = (t: string) => new Set(t.toLowerCase().match(/[a-z0-9]+/g) ?? []);
/** A placed sentence the polish lightly reworded (a word, a full stop) is still the same sentence. */
export function similar(a: string, b: string): boolean {
	const x = words(a), y = words(b);
	if (!x.size || !y.size) return false;
	let common = 0;
	for (const w of x) if (y.has(w)) common += 1;
	return common / Math.max(x.size, y.size) >= 0.7;
}

/** What the live strip shows: the tail of the dictation after the last sentence the scratchpad holds (hand read
 *  2026-10-12: a placed sentence the polish reworded came back into the strip). A sentence matching a unit exactly,
 *  or nearly, counts as held; held sentences earlier in the text are never shown again. */
export function liveTail(verbatim: string, units: StackUnit[]): string[] {
	const all = sentences(verbatim);
	const pool = units.map((u) => u.text);
	const held = all.map((s) => {
		let k = pool.indexOf(s);
		if (k < 0) k = pool.findIndex((t) => similar(t, s));
		if (k < 0) return false;
		pool.splice(k, 1);
		return true;
	});
	const last = held.lastIndexOf(true);
	return all.slice(last + 1);
}

/** The change to the verbatim text that sets one line (a sentence, or one part of a split sentence) to
 *  `text`. Empty `text` removes the line and one space or line break beside it. Null: the line is not found. */
export function lineChange(
	verbatim: string, units: StackUnit[], id: number, part: number | null, text: string
): { from: number; to: number; insert: string } | null {
	const at = sentenceOffset(verbatim, units, id);
	const unit = units.find((u) => u.id === id);
	if (at < 0 || !unit) return null;
	let from = at;
	let to = at + unit.text.length;
	if (part !== null) {
		const p = unit.parts?.[part];
		const k = p ? unit.text.indexOf(p.text) : -1;
		if (!p || k < 0) return null;
		from = at + k;
		to = from + p.text.length;
	}
	if (text.trim()) return { from, to, insert: text.trim() };
	if (/[ \t]/.test(verbatim[to] ?? '')) to += 1;
	else if (from > 0 && /\s/.test(verbatim[from - 1])) from -= 1;
	return { from, to, insert: '' };
}

/** A sentence added to the end of the solid text as if dictated (a chip accepted): one space, or nothing
 *  after a line break, before it. */
export function appendSentence(solid: string, sentence: string): string {
	const s = sentence.trim();
	if (!solid) return s;
	return (/\s$/.test(solid) ? '' : ' ') + s;
}
