// The command registry (spec §12.3, plan Task B5). Every rail and overlay action is a named, pure command:
// (document, items, item, args) → the CM6 change to dispatch plus the item events to post. Commands never call the
// network and never mutate what they are given; the caller (Task C3) dispatches the transaction, then posts each
// event (api.postEvent) and updates the store with `statuses`.
//
// Events only ever carry the backend's user commands (api.USER_COMMANDS: apply, edit, undo, dismiss, restore,
// view, ask_chat), and `statuses` only the statuses those commands produce (store.COMMAND_STATUS): applied, open,
// dismissed. Engine-only statuses (pre_applied, addressed, stale) are never set from here.
import { ChangeSet, Text, type ChangeSpec, type StateEffect } from '@codemirror/state';
import { locate } from './anchors';
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
	/** textHash(doc), when the caller has it: lets a zero-width anchor be used as stored if the text is unchanged. */
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

/** Where the applied text sits now: the recorded position with its context, else a unique search for the text
 * with its context, else (non-empty text only) a unique search for the text itself. Null: it is not there
 * verbatim any more. */
function findApplied(doc: string, d: Record<string, unknown>): number | null {
	const insert = String(d.insert ?? '');
	const left = String(d.left ?? '');
	const right = String(d.right ?? '');
	const at = Number(d.from);
	const whole = left + insert + right;
	if (Number.isInteger(at) && at - left.length >= 0 && doc.startsWith(whole, at - left.length))
		return at;
	if (whole && count(doc, whole) === 1) return doc.indexOf(whole) + left.length;
	if (insert && count(doc, insert) === 1) return doc.indexOf(insert);
	return null;
}

/** How far the item's anchor has moved since the engine wrote it: located position minus stored start. */
function anchorShift(ctx: CommandCtx, item: ReviewItem): number | null {
	const a = item.anchor;
	if (!a) return null;
	if (a.text) {
		const loc = locate(ctx.doc, item);
		return loc ? loc.from - a.start : null;
	}
	const pos = ctx.widgetPos?.(item);
	const loc = locate(ctx.doc, item, { widgetPos: pos ?? null });
	if (loc) return loc.from - a.start;
	if (ctx.textHash && a.text_hash && ctx.textHash === a.text_hash) return 0;
	return null;
}

/** Re-insert removed text at `p` with one space on the side that touches other text. */
function placeRemoved(doc: string, p: number, text: string): TextChange {
	const prev = doc[p - 1];
	const next = doc[p];
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
		const at = findApplied(doc, d);
		if (at == null) return 'changed';
		return { from: at, to: at + String(d.insert).length, insert: String(d.removed ?? '') };
	}
	if (item.status !== 'pre_applied') return 'not_applied';
	const undo = item.evidence?.undo;
	const shift = anchorShift(ctx, item);
	if (shift == null) return 'changed';
	if (undo && Array.isArray(undo.final_span)) {
		const [j1, j2] = undo.final_span;
		const from = j1 + shift;
		const to = j2 + shift;
		if (from < 0 || to > doc.length || from > to) return 'changed';
		const a = item.anchor!;
		if (a.text) {
			// the anchor (the inserted text) must still lie inside the span being reverted
			const s = a.start + shift;
			if (s < from || s + a.text.length > to) return 'changed';
		}
		return { from, to, insert: undo.original_text ?? '' };
	}
	const removed = item.evidence?.removed_text;
	if (typeof removed === 'string' && removed && !item.anchor?.text) {
		return placeRemoved(doc, item.anchor!.start + shift, removed);
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
		return {
			changes: c,
			event: { itemId: item.id, command, detail: { from: c.from, to: c.to, insert: c.insert } },
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

const askChat: Command = (ctx) => {
	const item = ctx.item;
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
