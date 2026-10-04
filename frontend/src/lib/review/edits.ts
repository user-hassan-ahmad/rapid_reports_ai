// Edit application: a review item's `Edit` → one CM6 change. A port of the backend's
// `review_engine/verifier.py` `apply_edit` (with `_remove_span`, `_renumber`, `_mid_word`, `_append_point` and
// the heading rules), so the text the rail writes is exactly the text the verifier checked. `edits.test.ts`
// holds parity vectors generated from the backend; keep the two in step.
//
// Where `lib/utils/impressionOptions.ts` and the backend differ (its IMPRESSION-only heading match and its
// "after the last complete sentence" append point), the backend wins: it is the text the fix was verified on.

/** The backend `Edit` (review_engine/items.py). Local until `types.ts` lands; structurally compatible. */
export interface EditLike {
	mode: 'replace' | 'insert' | 'upgrade' | 'remove';
	find?: string | null;
	replace?: string | null;
	after?: string | null;
	section?: string | null;
}

/** A single CM6 change (assignable to `ChangeSpec`). */
export interface TextChange {
	from: number;
	to: number;
	insert: string;
}

// ── headings ────────────────────────────────────────────────────────────────
const HEADING = /^([A-Z][A-Z /&()-]{2,}):\s*$/;
const NUMBERED = /^([ \t]*)(\d{1,2})([.)])([ \t]+)/;
const EMPTY_ITEM = /^\s*(?:\d+[.)]|[-*•])\s*$/;
const EOL = /^\r?\n/;

const normName = (s: string): string => s.trim().replace(/:+$/, '').trim().toLowerCase();

function knownNames(names: readonly string[]): Set<string> {
	return new Set(names.filter(Boolean).map(normName));
}

/** A section boundary: a known section name, or (none known) an ALL-CAPS "NAME:" line. */
function isHeading(line: string, names: readonly string[]): boolean {
	const s = line.trim();
	if (!s) return false;
	const known = knownNames(names);
	return known.size ? known.has(normName(s)) : HEADING.test(s);
}

/** Any heading-like line (a section heading or a region sub-heading). */
function isLabel(line: string, names: readonly string[]): boolean {
	const s = line.trim();
	return !!s && (HEADING.test(s) || isHeading(s, names));
}

/** (normalised name, line start, line end) for each section heading line. */
function headings(doc: string, names: readonly string[]): [string, number, number][] {
	const out: [string, number, number][] = [];
	let i = 0;
	for (const line of doc.split('\n')) {
		if (isHeading(line, names)) out.push([normName(line), i, i + line.length]);
		i += line.length + 1;
	}
	return out;
}

/** (heading line end, next heading start or doc end) for the first heading called `name`. */
function sectionBody(
	doc: string,
	name: string | null | undefined,
	names: readonly string[]
): [number, number] | null {
	if (!name) return null;
	const hs = headings(doc, names);
	const want = normName(name);
	for (let k = 0; k < hs.length; k++) {
		if (hs[k][0] === want) return [hs[k][2], k + 1 < hs.length ? hs[k + 1][1] : doc.length];
	}
	return null;
}

// ── helpers mirroring Python str semantics ──────────────────────────────────
/** Python `str.count` (non-overlapping). */
function count(text: string, needle: string): number {
	let n = 0;
	for (let i = text.indexOf(needle); i !== -1; i = text.indexOf(needle, i + needle.length)) n++;
	return n;
}

const once = (text: string, needle: string | null | undefined): needle is string =>
	!!needle && count(text, needle) === 1;

const isAlnum = (c: string | undefined): boolean => !!c && /[\p{L}\p{N}]/u.test(c);
const isSpace = (c: string | undefined): boolean => !!c && /\s/.test(c);
const rstripST = (s: string): string => s.replace(/[ \t]+$/, '');
const lstripST = (s: string): string => s.replace(/^[ \t]+/, '');

function cap(s: string): string {
	const c = s.slice(0, 1);
	return c && c === c.toLowerCase() && c !== c.toUpperCase() ? c.toUpperCase() + s.slice(1) : s;
}

/** True when position i splits a word (alphanumerics on both sides). */
function midWord(doc: string, i: number): boolean {
	return 0 < i && i < doc.length && isAlnum(doc[i - 1]) && isAlnum(doc[i]);
}

// ── remove ──────────────────────────────────────────────────────────────────
/** Numbered lines directly following a removed item `n` move up one (n+1 → n, n+2 → n+1, …). */
function renumber(after: string, n: number): string {
	const lines = after.split('\n');
	for (let k = 0; k < lines.length; k++) {
		const m = NUMBERED.exec(lines[k]);
		if (!m || Number(m[2]) !== n + k + 1) break;
		lines[k] = `${m[1]}${n + k}${m[3]}${m[4]}` + lines[k].slice(m[0].length);
	}
	return lines.join('\n');
}

/** Splice out [i, i+n) and tidy only the seam (backend `_remove_span`). CRLF-safe. */
function removeSpan(doc: string, i: number, n: number): string {
	let a = doc.slice(0, i);
	let b = doc.slice(i + n);
	let at = rstripST(a);
	let bt = lstripST(b);
	const ls = at.lastIndexOf('\n') + 1;
	const le = bt.indexOf('\n');
	const lineHead = at.slice(ls);
	if (
		lineHead.trim() &&
		EMPTY_ITEM.test(lineHead + (le < 0 ? bt : bt.slice(0, le)).replace(/\r+$/, ''))
	) {
		// a numbered or bulleted item left holding only its marker loses its line too
		let before = at.slice(0, ls);
		let after = le < 0 ? '' : bt.slice(le + 1);
		const m = NUMBERED.exec(lineHead + ' ');
		if (m) after = renumber(after, Number(m[2]));
		if (!after && before.endsWith('\n'))
			before = before.slice(0, before.endsWith('\r\n') ? -2 : -1);
		return before + after;
	}
	const eol = EOL.exec(bt);
	if (!at || at.endsWith('\n')) {
		// seam at a line start
		a = at;
		b = bt;
		if (eol) {
			// the line is now empty: drop it
			b = b.slice(eol[0].length);
			const nxt = EOL.exec(b);
			if (nxt && /(?:^|\n)[ \t\r]*\n$/.test(a)) b = b.slice(nxt[0].length); // a whole paragraph went
		} else if (!b && a.endsWith('\n')) {
			a = a.slice(0, a.endsWith('\r\n') ? -2 : -1);
		} else {
			b = cap(b); // a leading item went: the sentence starts here
		}
	} else if (!bt || eol || bt === '\r') {
		// seam at a line end
		a = at;
		b = bt;
		if (a.endsWith(',') || a.endsWith(';')) a = a.slice(0, -1) + '.'; // a dangling separator closes it
	} else {
		let sp: string;
		if ('.,;:'.includes(bt[0]) && '.,;:!?'.includes(at[at.length - 1])) {
			// the removed text left its punctuation behind
			if (',;:'.includes(at[at.length - 1]) && '.;'.includes(bt[0])) {
				at = at.slice(0, -1);
				sp = '';
			} else {
				bt = lstripST(bt.slice(1));
				sp = ' ';
			}
		} else {
			sp =
				a !== at && b !== bt
					? ' '
					: (a.slice(at.length) + b.slice(0, b.length - bt.length)).slice(0, 1);
		}
		if ('.!?'.includes(at[at.length - 1])) bt = cap(bt);
		a = at + sp;
		b = bt;
	}
	return a + b;
}

// ── insert ──────────────────────────────────────────────────────────────────
/** Insert with no `after`: [position, separator] at the end of `edit.section`'s body. */
function appendPoint(
	doc: string,
	edit: EditLike,
	names: readonly string[]
): [number, string] | null {
	const body = sectionBody(doc, edit.section, names);
	if (!body) return null;
	const [a, e] = body;
	const text = doc.slice(a, e).trimEnd();
	if (!text.trim()) return [a, '\n'];
	const m = NUMBERED.exec(text.slice(text.lastIndexOf('\n') + 1));
	if (m) {
		// a numbered list (IMPRESSION): the insert is the next item
		const nl = doc.includes('\r\n') ? '\r\n' : '\n';
		return [a + text.length, `${nl}${m[1]}${Number(m[2]) + 1}${m[3]}${m[4]}`];
	}
	return [a + text.length, ' '];
}

// ── public ──────────────────────────────────────────────────────────────────
/** The change that applies `edit`, or null when it cannot be placed exactly once (backend `apply_edit`).
 * Remove returns the smallest change around the removed span (seam tidy and any renumbering), never the whole
 * document. `sections` are the report's known section names; without them ALL-CAPS "NAME:" lines bound sections. */
export function toChanges(
	doc: string,
	edit: EditLike | null | undefined,
	sections?: readonly string[] | null
): TextChange | null {
	if (!edit) return null;
	const names = sections ?? [];
	const m = edit.mode;
	if ((m === 'replace' || m === 'upgrade') && once(doc, edit.find) && edit.replace != null) {
		const from = doc.indexOf(edit.find);
		return { from, to: from + edit.find.length, insert: edit.replace };
	}
	if (m === 'remove' && once(doc, edit.find)) {
		const i = doc.indexOf(edit.find);
		const n = edit.find.length;
		if (midWord(doc, i) || midWord(doc, i + n)) return null; // find starts or ends mid-word
		return diffAround(doc, removeSpan(doc, i, n), i, i + n);
	}
	const text = (edit.replace ?? '').trim();
	if (m !== 'insert' || !text) return null;
	const anchor = (edit.after ?? '').trim();
	if (anchor) {
		if (!once(doc, anchor)) return null;
		const at = doc.indexOf(anchor) + anchor.length;
		if (at < doc.length && !isSpace(doc[at])) return null; // anchor ends mid-word
		return { from: at, to: at, insert: (isLabel(anchor, names) ? '\n' : ' ') + text };
	}
	if (edit.after != null) return null; // a blank anchor is not "append to the section"
	const pt = appendPoint(doc, edit, names);
	if (!pt) return null;
	return { from: pt[0], to: pt[0], insert: pt[1] + text };
}

/** The document with `edit` applied, or null (the backend's `apply_edit` output, for parity and previews). */
export function applyEditText(
	doc: string,
	edit: EditLike | null | undefined,
	sections?: readonly string[] | null
): string | null {
	const c = toChanges(doc, edit, sections);
	return c ? doc.slice(0, c.from) + c.insert + doc.slice(c.to) : null;
}

/** The single change turning `before` into `after`, kept to cover [lo, hi) (the removed span) so the change sits
 * at the edit site: common prefix up to `lo`, common suffix up to `hi`. */
function diffAround(before: string, after: string, lo: number, hi: number): TextChange {
	let p = 0;
	const maxP = Math.min(lo, after.length);
	while (p < maxP && before[p] === after[p]) p++;
	let s = 0;
	const maxS = Math.min(before.length - hi, after.length - p);
	while (s < maxS && before[before.length - 1 - s] === after[after.length - 1 - s]) s++;
	return { from: p, to: before.length - s, insert: after.slice(p, after.length - s) };
}
