import type { StackUnit, StackView, ViewGroup, ViewRow } from './types';

const row = (u: StackUnit, text = u.text, partOf: number | null = null): ViewRow => ({
	unitId: u.id, text, structure: u.structure, partOf, pinned: u.pinned, children: []
});

/** The grouped view: groups in schema order, sentences in dictated order, attached sentences nested
 *  under their parent, heading-only sentences hidden, unplaced sentences kept apart ("just dictated"). */
export function buildView(units: StackUnit[], groups: string[]): StackView {
	const rows = new Map<string, ViewRow[]>(groups.map((g) => [g, []]));
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
			u.parts.forEach((p, k) => {
				const r = row(u, p.text, u.id);
				if (k === 0) byId.set(u.id, r);
				add(p.group, r);
			});
			continue;
		}
		const r = row(u);
		byId.set(u.id, r);
		add(u.group, r);
	}
	const out: ViewGroup[] = [];
	for (const [name, rs] of rows) if (rs.length) out.push({ name, rows: rs });
	return { groups: out, unplaced };
}

/** A drag to another group: the sentence is pinned there (the server never changes it again). */
export function moveUnit(units: StackUnit[], id: number, group: string): StackUnit[] {
	return units.map((u) => (u.id === id ? { ...u, group, pinned: true, attach_to: null, parts: null } : u));
}

/** Character offset of unit `id` in the verbatim text (the nth occurrence of its sentence). */
export function sentenceOffset(text: string, units: StackUnit[], id: number): number {
	const target = units.find((u) => u.id === id);
	if (!target) return -1;
	const nth = units.filter((u) => u.id < id && u.text === target.text).length;
	let pos = -1;
	for (let k = 0; k <= nth; k++) {
		pos = text.indexOf(target.text, pos + 1);
		if (pos < 0) return -1;
	}
	return pos;
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
export function liveTail(verbatim: string, units: StackUnit[]): string[] {
	const held = new Map<string, number>();
	for (const u of units) held.set(u.text, (held.get(u.text) ?? 0) + 1);
	return sentences(verbatim).filter((s) => {
		const n = held.get(s) ?? 0;
		if (n > 0) {
			held.set(s, n - 1);
			return false;
		}
		return true;
	});
}
