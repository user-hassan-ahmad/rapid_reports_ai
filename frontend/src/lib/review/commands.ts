// The command registry (spec §12.3, plan Task B5). Every rail and overlay action is a named, pure command:
// (document, items, item, args) → the CM6 change to dispatch plus the item events to post. Commands never call the
// network and never mutate what they are given; the caller (Task C3) dispatches the transaction, then posts each
// event (api.postEvent) and updates the store with `statuses`.
//
// Events only ever carry the backend's user commands (api.USER_COMMANDS: apply, edit, undo, dismiss, restore,
// view, ask_chat), and `statuses` only the statuses those commands produce (store.COMMAND_STATUS): applied, open,
// dismissed. Engine-only statuses (pre_applied, addressed, stale) are never set from here.
import { ChangeSet, Text, type ChangeSpec, type StateEffect } from '@codemirror/state';
import { locate, locateUndo } from './anchors';
import { toChanges, type EditLike, type TextChange } from './edits';
import type { ReviewItem, UserCommand } from './types';

/** The statuses a user command sets (backend store.COMMAND_STATUS, user commands only). */
export type UserStatus = 'applied' | 'open' | 'dismissed';

export interface ItemEvent {
	itemId: string;
	command: UserCommand;
	detail: Record<string, unknown>;
}

export interface CommandCtx {
	doc: string;
	items: readonly ReviewItem[];
	item?: ReviewItem | null;
	args?: Record<string, unknown>;
	/** The report's section names (edits.toChanges); without them ALL-CAPS "NAME:" lines bound sections. */
	sections?: readonly string[] | null;
	/** Where the editor field holds an item's widget (zero-width removal anchors), mapped through edits. */
	widgetPos?: (item: ReviewItem) => number | null | undefined;
	/** textHash(doc), when the caller has it. Live pre-applied edits use their stored offsets only when this equals
	 * the anchor's text_hash (the written text); otherwise they are re-found by context (anchors.locateUndo). */
	textHash?: string | null;
}

export type CommandError =
	| 'no_item'
	| 'not_open'
	| 'no_edit'
	| 'no_replacement'
	| 'not_found'
	| 'not_applied'
	| 'not_removal'
	| 'changed';

export interface CommandResult {
	changes?: ChangeSpec;
	effects?: StateEffect<unknown>[];
	event?: ItemEvent;
	/** apply_all: one event per applied item, in document order. */
	events?: ItemEvent[];
	statuses?: Record<string, UserStatus>;
	/** apply_all: eligible items whose edit could not be placed (an earlier edit consumed their text). */
	skipped?: string[];
	focus?: { itemId: string; from: number; to: number } | null;
	openChat?: string;
	request?: { type: 'rerun' } | { type: 'finalise'; applied: string[] };
	error?: CommandError;
}

export type Command = (ctx: CommandCtx) => CommandResult;

/** Characters of surrounding text kept with an applied edit, so undo can find it again verbatim. */
const CONTEXT = 16;
const ACTIONABLE: ReadonlySet<string> = new Set(['open', 'stale']);

const fail = (error: CommandError): CommandResult => ({ error });

function isRemoval(item: ReviewItem): boolean {
	const rt = item.evidence?.removed_text;
	return (typeof rt === 'string' && !!rt) || item.edit?.mode === 'remove';
}

/** Event detail for a change made at `from` (pre-change coordinates == post-change start) in `before`. */
function appliedDetail(before: string, c: TextChange): Record<string, unknown> {
	return {
		from: c.from,
		insert: c.insert,
		removed: before.slice(c.from, c.to),
		left: before.slice(Math.max(0, c.from - CONTEXT), c.from),
		right: before.slice(c.to, c.to + CONTEXT)
	};
}

function placeEdit(
	ctx: CommandCtx,
	item: ReviewItem,
	edit: EditLike,
	command: 'apply' | 'edit',
	extra = {}
): CommandResult {
	const c = toChanges(ctx.doc, edit, ctx.sections);
	if (!c) return fail('not_found');
	return {
		changes: c,
		event: { itemId: item.id, command, detail: { ...appliedDetail(ctx.doc, c), ...extra } },
		statuses: { [item.id]: 'applied' }
	};
}

// ── apply / edit ────────────────────────────────────────────────────────────
const apply: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	if (!ACTIONABLE.has(item.status)) return fail('not_open');
	// A pre-applied (post-check) edit the user undid or restored: apply re-does exactly that change, found by the
	// context the undo / restore recorded, never by re-placing item.edit (its clause may now occur twice).
	const d = item.history.some((h) => h.event === 'pre_applied') ? lastReverted(item) : null;
	if (d) {
		const at = findApplied(ctx.doc, d, true); // context required: the bare text may sit elsewhere too
		if (at == null) return fail('changed');
		const c: TextChange = { from: at, to: at + String(d.insert).length, insert: String(d.removed) };
		return {
			changes: c,
			event: { itemId: item.id, command: 'apply', detail: appliedDetail(ctx.doc, c) },
			statuses: { [item.id]: 'applied' }
		};
	}
	if (!item.edit) return fail('no_edit');
	return placeEdit(ctx, item, item.edit, 'apply');
};

const edit: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	if (!ACTIONABLE.has(item.status)) return fail('not_open');
	const replacement = ctx.args?.replacement;
	if (typeof replacement !== 'string') return fail('no_replacement');
	let base: EditLike | null = item.edit ?? null;
	if (!base || base.mode === 'remove') {
		const find = base?.find ?? (item.anchor?.text || null);
		if (!find) return fail('no_edit');
		base = { mode: 'replace', find };
	}
	return placeEdit(ctx, item, { ...base, replace: replacement }, 'edit', { replacement });
};

// ── undo / restore ──────────────────────────────────────────────────────────
function count(text: string, needle: string): number {
	let n = 0;
	for (
		let i = text.indexOf(needle);
		i !== -1;
		i = text.indexOf(needle, i + Math.max(1, needle.length))
	)
		n++;
	return n;
}

/** The last apply/edit this item recorded (its event detail), if any. */
function lastApplied(item: ReviewItem): Record<string, unknown> | null {
	for (let k = item.history.length - 1; k >= 0; k--) {
		const h = item.history[k];
		if ((h.event === 'apply' || h.event === 'edit') && typeof h.detail?.insert === 'string')
			return h.detail;
	}
	return null;
}

/** The item's latest text event when it is an undo / restore that recorded what it replaced (its detail), else
 * null (the latest is an apply / edit, or there is none). */
function lastReverted(item: ReviewItem): Record<string, unknown> | null {
	for (let k = item.history.length - 1; k >= 0; k--) {
		const h = item.history[k];
		if (h.event === 'apply' || h.event === 'edit') return null;
		if (h.event === 'undo' || h.event === 'restore') {
			const d = h.detail;
			return d && typeof d.insert === 'string' && typeof d.removed === 'string' ? d : null;
		}
	}
	return null;
}

/** Where the applied text sits now: the recorded position with its context, else a unique search for the text
 * with its context, else (non-empty text only, unless `withContext`) a unique search for the text itself. Null: it
 * is not there verbatim any more. */
function findApplied(doc: string, d: Record<string, unknown>, withContext = false): number | null {
	const insert = String(d.insert ?? '');
	const left = String(d.left ?? '');
	const right = String(d.right ?? '');
	const at = Number(d.from);
	const whole = left + insert + right;
	if (Number.isInteger(at) && at - left.length >= 0 && doc.startsWith(whole, at - left.length))
		return at;
	if (whole && count(doc, whole) === 1) return doc.indexOf(whole) + left.length;
	if (!withContext && insert && count(doc, insert) === 1) return doc.indexOf(insert);
	return null;
}

/** Where a suggestion's applied text sits now, without the separating whitespace the insert carried: from its
 * apply event (recorded position and context), else the text itself when it occurs once. Null: not there verbatim. */
export function appliedSpan(doc: string, item: ReviewItem): { from: number; to: number } | null {
	const d = lastApplied(item);
	if (d) {
		const at = findApplied(doc, d);
		const insert = String(d.insert ?? '');
		const text = insert.trim();
		if (at != null && text) {
			const from = at + (insert.length - insert.trimStart().length);
			return { from, to: from + text.length };
		}
	}
	const text = item.edit?.replace?.trim();
	if (text && count(doc, text) === 1) {
		const from = doc.indexOf(text);
		return { from, to: from + text.length };
	}
	return null;
}

/** Where a recommendation's sentence sits now, or null. Besides the text verbatim (unique), the forms a neighbour's
 * removal leaves (edits.removeSpan's seam tidy): the first letter capitalised (the sentence now starts there) and a
 * trailing "," / ";" closed to "." (it now ends the line). */
export function findRecText(doc: string, text: string): { from: number; to: number } | null {
	if (!text) return null;
	const capped = text[0].toUpperCase() + text.slice(1);
	const closed = (t: string) => (/[;,]$/.test(t) ? `${t.slice(0, -1)}.` : t);
	for (const t of new Set([text, capped, closed(text), closed(capped)]))
		if (count(doc, t) === 1) {
			const from = doc.indexOf(t);
			return { from, to: from + t.length };
		}
	return null;
}

// ── recommendations: the checkbox toggles, order-independent ────────────────
// Neighbouring recommendations often share a line ("CT thorax is recommended; EUS sampling for diagnosis; MDT
// referral."). Removing one tidies the seam (edits.removeSpan: a dangling ";" closes to ".", the next clause is
// capitalised), so the seam context another removal or undo recorded no longer matches once a neighbour was
// toggled, and the checkbox stopped working. Instead every toggle rewrites the recommendation's paragraph to its
// canonical form: the paragraph as written (`orig_para`, carried in each removal's event detail) with the unticked
// recommendations removed in document order. Any order of toggles then gives the same text, and re-ticking all of
// them gives the paragraph back exactly.

/** The longest paragraph recorded in an event detail (the detail is bounded server side). */
const MAX_PARA = 3000;

const isRec = (i: ReviewItem) => i.kind === 'recommendation' && !!i.anchor?.text;

/** The paragraph (lines between blank lines) holding `pos`. */
function paragraphAt(doc: string, pos: number): { from: number; to: number } {
	let from = pos;
	while (from > 0 && !(doc[from - 1] === '\n' && (from < 2 || doc[from - 2] === '\n'))) from--;
	let to = pos;
	while (to < doc.length && !(doc[to] === '\n' && doc[to + 1] === '\n')) to++;
	return { from, to };
}

/** `para` with each of `texts` removed (edits.toChanges seam tidy), in their order in `para`; null if one is not
 * there. */
function canonical(para: string, texts: readonly string[]): string | null {
	let s = para;
	const ordered = [...texts].sort((a, b) => para.indexOf(a) - para.indexOf(b));
	for (const t of ordered) {
		const at = findRecText(s, t);
		if (!at) return null;
		const c = toChanges(s, { mode: 'remove', find: s.slice(at.from, at.to) });
		if (!c) return null;
		s = s.slice(0, c.from) + c.insert + s.slice(c.to);
	}
	return s;
}

/** A recommendation removed by its checkbox (status applied by `remove`). */
const recRemoved = (i: ReviewItem) => isRec(i) && i.status === 'applied' && lastApplied(i)?.action === 'remove';

/** The written paragraph around `item` and where its current form sits in `doc`, or null. */
function recParagraph(
	ctx: CommandCtx,
	item: ReviewItem
): { orig: string; from: number; to: number; removed: string[] } | null {
	const text = item.anchor!.text;
	const recs = ctx.items.filter(isRec);
	const removedIn = (orig: string) =>
		recs.filter((i) => recRemoved(i) && i.id !== item.id && orig.includes(i.anchor!.text)).map((i) => i.anchor!.text);
	const seen = new Set<string>();
	for (const i of [item, ...recs])
		for (let k = i.history.length - 1; k >= 0; k--) {
			const orig = i.history[k].detail?.orig_para;
			if (typeof orig !== 'string' || seen.has(orig) || !orig.includes(text)) continue;
			seen.add(orig);
			const removed = removedIn(orig);
			const cur = canonical(orig, item.status === 'applied' ? [...removed, text] : removed);
			if (cur != null && count(ctx.doc, cur) === 1) {
				const from = ctx.doc.indexOf(cur);
				return { orig, from, to: from + cur.length, removed };
			}
		}
	if (item.status === 'applied') return null;
	// no record yet: the paragraph is as written when none of its recommendations has been removed
	const at = findRecText(ctx.doc, text);
	if (!at) return null;
	const p = paragraphAt(ctx.doc, at.from);
	const orig = ctx.doc.slice(p.from, p.to);
	if (orig.length > MAX_PARA || !orig.includes(text)) return null;
	return { orig, ...p, removed: [] };
}

/** The smallest change turning doc[from, to) into `next`. */
function narrow(doc: string, from: number, to: number, next: string): TextChange {
	const cur = doc.slice(from, to);
	let p = 0;
	while (p < cur.length && p < next.length && cur[p] === next[p]) p++;
	let s = 0;
	while (s < cur.length - p && s < next.length - p && cur[cur.length - 1 - s] === next[next.length - 1 - s]) s++;
	return { from: from + p, to: to - s, insert: next.slice(p, next.length - s) };
}

/** Untick: the paragraph without this recommendation (and the ones already removed). */
function removeRecommendation(ctx: CommandCtx, item: ReviewItem): TextChange & { orig: string } | null {
	const r = recParagraph(ctx, item);
	if (!r) return null;
	const next = canonical(r.orig, [...r.removed, item.anchor!.text]);
	return next == null ? null : { ...narrow(ctx.doc, r.from, r.to, next), orig: r.orig };
}

/** Re-tick: the paragraph with this recommendation back (the others as they are). */
function restoreRecommendation(ctx: CommandCtx, item: ReviewItem): TextChange | null {
	const r = recParagraph(ctx, item);
	if (!r) return null;
	const next = canonical(r.orig, r.removed);
	return next == null ? null : narrow(ctx.doc, r.from, r.to, next);
}

/** Where a zero-width removal without live undo info sits: the widget position the field tracks, else the stored
 * anchor when the document is the text it was made on. */
function removalPoint(ctx: CommandCtx, item: ReviewItem): number | null {
	const pos = ctx.widgetPos?.(item);
	const loc = locate(ctx.doc, item, { widgetPos: pos ?? null });
	if (loc) return loc.from;
	const a = item.anchor;
	if (a && ctx.textHash && a.text_hash && ctx.textHash === a.text_hash) return a.start;
	return null;
}

const WORD = /[\p{L}\p{N}_]/u;

/** Re-insert removed text at `p` with one space on the side that touches other text; null in the middle of a
 * word (a position that cannot be where the text came from). */
function placeRemoved(doc: string, p: number, text: string): TextChange | null {
	if (p < 0 || p > doc.length) return null;
	const prev = doc[p - 1];
	const next = doc[p];
	if (prev !== undefined && next !== undefined && WORD.test(prev) && WORD.test(next)) return null;
	const lead = prev !== undefined && !/\s/.test(prev) ? ' ' : '';
	const trail = next !== undefined && !/\s/.test(next) ? ' ' : '';
	return { from: p, to: p, insert: lead + text + trail };
}

/** The change that takes an applied or pre-applied item's text back, or an error. */
function revert(ctx: CommandCtx, item: ReviewItem): TextChange | CommandError {
	const doc = ctx.doc;
	if (item.status === 'applied') {
		const d = lastApplied(item);
		if (!d) return 'not_applied';
		if (d.action === 'remove' && isRec(item)) {
			const c = restoreRecommendation(ctx, item);
			if (c) return c;
		}
		const at = findApplied(doc, d);
		if (at == null) return 'changed';
		return { from: at, to: at + String(d.insert).length, insert: String(d.removed ?? '') };
	}
	if (item.status !== 'pre_applied') return 'not_applied';
	const undo = item.evidence?.undo;
	if (undo && Array.isArray(undo.final_span)) {
		// live mode: never a guessed position (hash match, else unique context)
		const at = locateUndo(doc, item, ctx.textHash);
		if (!at) return 'changed';
		return { from: at.from, to: at.to, insert: undo.original_text ?? '' };
	}
	const removed = item.evidence?.removed_text;
	if (typeof removed === 'string' && removed && !item.anchor?.text) {
		const p = removalPoint(ctx, item);
		if (p == null) return 'changed';
		return placeRemoved(doc, p, removed) ?? 'changed';
	}
	return 'not_applied';
}

function reverting(command: 'undo' | 'restore'): Command {
	return (ctx) => {
		const item = ctx.item;
		if (!item) return fail('no_item');
		if (command === 'restore' && !isRemoval(item)) return fail('not_removal');
		const c = revert(ctx, item);
		if (typeof c === 'string') return fail(c);
		const doc = ctx.doc;
		return {
			changes: c,
			event: {
				itemId: item.id,
				command,
				detail: {
					from: c.from,
					to: c.to,
					insert: c.insert,
					removed: doc.slice(c.from, c.to),
					left: doc.slice(Math.max(0, c.from - CONTEXT), c.from),
					right: doc.slice(c.to, c.to + CONTEXT)
				}
			},
			statuses: { [item.id]: 'open' }
		};
	};
}

// ── dismiss / ask_chat / navigation ─────────────────────────────────────────
const dismiss: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	if (!ACTIONABLE.has(item.status)) return fail('not_open');
	return {
		event: { itemId: item.id, command: 'dismiss', detail: {} },
		statuses: { [item.id]: 'dismissed' }
	};
};

/** Take the item's anchored text out of the report (e.g. an assumed normal the radiologist does not want). Posted
 * as `edit` with an empty replacement, so undo finds the seam by its context like any applied edit. */
const remove: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	if (!ACTIONABLE.has(item.status)) return fail('not_open');
	let find = item.anchor?.text;
	if (!find) return fail('no_edit');
	if (isRec(item)) {
		const c = removeRecommendation(ctx, item);
		if (c) {
			const { orig, ...change } = c;
			return {
				changes: change,
				event: {
					itemId: item.id,
					command: 'edit',
					detail: { ...appliedDetail(ctx.doc, change), action: 'remove', replacement: '', orig_para: orig }
				},
				statuses: { [item.id]: 'applied' }
			};
		}
		// a neighbour's removal may have re-cased or re-punctuated it (findRecText)
		const at = findRecText(ctx.doc, find);
		if (at) find = ctx.doc.slice(at.from, at.to);
	}
	return placeEdit(ctx, item, { mode: 'remove', find }, 'edit', {
		action: 'remove',
		replacement: ''
	});
};

/** Keep the text as written: the item is answered with no change (posted as `dismiss`, detail action "keep"). */
const keep: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	if (!ACTIONABLE.has(item.status)) return fail('not_open');
	return {
		event: { itemId: item.id, command: 'dismiss', detail: { action: 'keep' } },
		statuses: { [item.id]: 'dismissed' }
	};
};

const askChat: Command = (ctx) => {
	const item = ctx.item;
	// no item: a question from outside the item list (the rail's Guidelines tab), its text in args.text
	const text = typeof ctx.args?.text === 'string' ? ctx.args.text : '';
	if (!item && text.trim()) return { openChat: text };
	if (!item) return fail('no_item');
	const on = item.anchor?.text ? `\n\nOn: "${item.anchor.text}"` : '';
	return {
		openChat: `${item.label}: ${item.reason}${on}`,
		event: { itemId: item.id, command: 'ask_chat', detail: {} }
	};
};

const openItem: Command = (ctx) => {
	const item = ctx.item;
	if (!item) return fail('no_item');
	const loc = locate(ctx.doc, item, { widgetPos: ctx.widgetPos?.(item) ?? null });
	return {
		focus: loc ? { itemId: item.id, ...loc } : null,
		event: { itemId: item.id, command: 'view', detail: {} }
	};
};

/** The next open action/minor item after `item` in document order, wrapping. Navigation only: no event. */
const nextItem: Command = (ctx) => {
	const placed = ctx.items
		.filter((i) => i.status === 'open' && (i.cls === 'action' || i.cls === 'minor'))
		.map((i) => ({ i, loc: locate(ctx.doc, i, { widgetPos: ctx.widgetPos?.(i) ?? null }) }))
		.filter((x): x is { i: ReviewItem; loc: { from: number; to: number } } => !!x.loc)
		.sort((a, b) => a.loc.from - b.loc.from || a.loc.to - b.loc.to);
	if (!placed.length) return { focus: null };
	let k = 0;
	const cur = ctx.item;
	if (cur) {
		const idx = placed.findIndex((x) => x.i.id === cur.id);
		if (idx >= 0) k = (idx + 1) % placed.length;
		else {
			const here = locate(ctx.doc, cur, { widgetPos: ctx.widgetPos?.(cur) ?? null });
			const after = here ? placed.findIndex((x) => x.loc.from > here.from) : -1;
			k = after >= 0 ? after : 0;
		}
	}
	const { i, loc } = placed[k];
	return { focus: { itemId: i.id, ...loc } };
};

// ── apply_all ───────────────────────────────────────────────────────────────
/** Apply every open, unsuppressed item with an edit matching `args.lane` / `args.kind` / `args.cls`, in document
 * order. Each edit is placed on the text as the earlier ones left it (edits are text-anchored, so later anchors
 * re-locate themselves); the steps compose into one change set on the original document. */
const applyAll: Command = (ctx) => {
	const { lane, kind, cls } = (ctx.args ?? {}) as { lane?: string; kind?: string; cls?: string };
	const eligible = ctx.items.filter(
		(i) =>
			i.status === 'open' &&
			i.cls !== 'suppress' &&
			!!i.edit &&
			(lane == null || i.lane === lane) &&
			(kind == null || i.kind === kind) &&
			(cls == null || i.cls === cls)
	);
	const pos = (i: ReviewItem): number => {
		const loc = locate(ctx.doc, i);
		if (loc) return loc.from;
		const probe = i.edit?.find || i.edit?.after;
		const k = probe ? ctx.doc.indexOf(probe) : -1;
		return k >= 0 ? k : Number.POSITIVE_INFINITY;
	};
	const ordered = eligible
		.map((i, n) => ({ i, p: pos(i), n }))
		.sort((a, b) => a.p - b.p || a.n - b.n)
		.map((x) => x.i);

	let cur = ctx.doc;
	let all = ChangeSet.empty(ctx.doc.length);
	const steps: { item: ReviewItem; c: TextChange; removed: string; set: ChangeSet }[] = [];
	const skipped: string[] = [];
	for (const item of ordered) {
		const c = toChanges(cur, item.edit, ctx.sections);
		if (!c) {
			skipped.push(item.id);
			continue;
		}
		const set = ChangeSet.of(c, cur.length);
		steps.push({ item, c, removed: cur.slice(c.from, c.to), set });
		all = all.compose(set);
		cur = cur.slice(0, c.from) + c.insert + cur.slice(c.to);
	}

	const batch = { lane: lane ?? null, kind: kind ?? null, cls: cls ?? null };
	const events: ItemEvent[] = [];
	const statuses: Record<string, UserStatus> = {};
	steps.forEach(({ item, c, removed }, k) => {
		let from = c.from;
		for (const later of steps.slice(k + 1)) from = later.set.mapPos(from, 1);
		const end = from + c.insert.length;
		events.push({
			itemId: item.id,
			command: 'apply',
			detail: {
				from,
				insert: c.insert,
				removed,
				left: cur.slice(Math.max(0, from - CONTEXT), from),
				right: cur.slice(end, end + CONTEXT),
				batch
			}
		});
		statuses[item.id] = 'applied';
	});
	return { ...(steps.length ? { changes: all } : {}), events, statuses, skipped };
};

// ── rerun / finalise ────────────────────────────────────────────────────────
const rerun: Command = () => ({ request: { type: 'rerun' } });

/** The items the radiologist kept (applied by hand or pre-applied by the engine), for `options_applied`. */
const finalise: Command = (ctx) => ({
	request: {
		type: 'finalise',
		applied: ctx.items
			.filter((i) => i.status === 'applied' || i.status === 'pre_applied')
			.map((i) => i.id)
	}
});

export const COMMANDS = {
	apply,
	edit,
	undo: reverting('undo'),
	restore: reverting('restore'),
	dismiss,
	remove,
	keep,
	apply_all: applyAll,
	ask_chat: askChat,
	open_item: openItem,
	next_item: nextItem,
	rerun,
	finalise
} satisfies Record<string, Command>;

export type CommandName = keyof typeof COMMANDS;

export function runCommand(name: CommandName, ctx: CommandCtx): CommandResult {
	return COMMANDS[name](ctx);
}

/** The document after a command's changes (previews and tests). */
export function applyResult(doc: string, r: CommandResult): string {
	if (!r.changes) return doc;
	return ChangeSet.of(r.changes, doc.length)
		.apply(Text.of(doc.split('\n')))
		.toString();
}
