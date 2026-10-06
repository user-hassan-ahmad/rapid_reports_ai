import { ChangeSet, Text } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import {
	COMMANDS,
	findRecText,
	runCommand,
	type CommandCtx,
	type CommandResult,
	type ItemEvent
} from './commands';
import type { Edit, HistoryEntry, ReviewItem, Span } from './types';

const USER_COMMANDS = ['apply', 'edit', 'undo', 'dismiss', 'restore', 'view', 'ask_chat'];
const USER_STATUSES = ['applied', 'open', 'dismissed'];

let n = 0;
function item(over: Partial<ReviewItem> = {}): ReviewItem {
	n++;
	return {
		id: `i${n}`,
		key: `k${n}`,
		report_id: 'r1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		kind: 'omission',
		cls: 'action',
		section: 'FINDINGS',
		anchor: null,
		label: 'label',
		reason: 'reason',
		edit: null,
		evidence: null,
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

function span(doc: string, text: string, hash: string | null = null): Span {
	const start = doc.indexOf(text);
	return { start, end: start + text.length, text, text_hash: hash };
}

/** Apply a command's changes to `doc` exactly as CM6 would. */
function after(doc: string, r: CommandResult): string {
	if (!r.changes) return doc;
	return ChangeSet.of(r.changes, doc.length)
		.apply(Text.of(doc.split('\n')))
		.toString();
}

/** The history event a store would append after the caller posts `ev`. */
function hist(ev: ItemEvent): HistoryEntry {
	return { event: ev.command, actor: 'user', detail: ev.detail };
}

function run(name: keyof typeof COMMANDS, ctx: CommandCtx): CommandResult {
	const r = runCommand(name, ctx);
	for (const ev of [r.event, ...(r.events ?? [])].filter(Boolean) as ItemEvent[]) {
		expect(USER_COMMANDS).toContain(ev.command);
	}
	for (const s of Object.values(r.statuses ?? {})) expect(USER_STATUSES).toContain(s);
	return r;
}

/** live.rebase_items' evidence.undo for the span [j1, j2) of the written text. */
function undoOf(written: string, j1: number, j2: number, original_text: string) {
	return {
		final_span: [j1, j2] as [number, number],
		original_text,
		final_text: written.slice(j1, j2),
		left: written.slice(Math.max(0, j1 - 16), j1),
		right: written.slice(j2, j2 + 16)
	};
}

const DOC =
	'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney.\nIMPRESSION:\nLeft renal cyst.';
const SECTIONS = ['FINDINGS', 'IMPRESSION'];

describe('apply', () => {
	it('turns the edit into one change, posts apply and sets applied', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' } });
		const r = run('apply', { doc: DOC, items: [it_], item: it_, sections: SECTIONS });
		expect(after(DOC, r)).toBe(DOC.replace('a cyst', 'a 14 mm cyst'));
		expect(r.event?.command).toBe('apply');
		expect(r.event?.itemId).toBe(it_.id);
		expect(r.statuses).toEqual({ [it_.id]: 'applied' });
		expect(r.event?.detail).toMatchObject({ insert: 'a 14 mm cyst', removed: 'a cyst' });
	});

	it('appends an insert to its section', () => {
		const it_ = item({
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' }
		});
		const r = run('apply', { doc: DOC, items: [it_], item: it_, sections: SECTIONS });
		expect(after(DOC, r)).toBe(DOC.replace('left kidney.', 'left kidney. No ascites.'));
	});

	it('returns an error and no event when the edit cannot be placed', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'pancreas', replace: 'x' } });
		const r = run('apply', { doc: DOC, items: [it_], item: it_ });
		expect(r.error).toBe('not_found');
		expect(r.changes).toBeUndefined();
		expect(r.event).toBeUndefined();
	});

	it('refuses items that are not open, and items with no edit', () => {
		const done = item({
			status: 'applied',
			edit: { mode: 'replace', find: 'a cyst', replace: 'x' }
		});
		expect(run('apply', { doc: DOC, items: [done], item: done }).error).toBe('not_open');
		const bare = item();
		expect(run('apply', { doc: DOC, items: [bare], item: bare }).error).toBe('no_edit');
	});
});

describe('edit', () => {
	it("applies the user's replacement in place of the proposed one", () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' } });
		const r = run('edit', {
			doc: DOC,
			items: [it_],
			item: it_,
			args: { replacement: 'a 15 mm cyst' }
		});
		expect(after(DOC, r)).toBe(DOC.replace('a cyst', 'a 15 mm cyst'));
		expect(r.event?.command).toBe('edit');
		expect(r.event?.detail).toMatchObject({ replacement: 'a 15 mm cyst' });
		expect(r.statuses).toEqual({ [it_.id]: 'applied' });
	});

	it('turns a removal into a replace of the same text', () => {
		const it_ = item({ edit: { mode: 'remove', find: 'There is a cyst in the left kidney.' } });
		const r = run('edit', {
			doc: DOC,
			items: [it_],
			item: it_,
			args: { replacement: 'There is a small cyst in the left kidney.' }
		});
		expect(after(DOC, r)).toBe(DOC.replace('a cyst', 'a small cyst'));
	});

	it('requires a replacement', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'x' } });
		expect(run('edit', { doc: DOC, items: [it_], item: it_ }).error).toBe('no_replacement');
	});
});

describe('undo', () => {
	it('inverts an applied edit when the replacement is still present verbatim', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' } });
		const a = run('apply', { doc: DOC, items: [it_], item: it_ });
		const doc2 = after(DOC, a);
		const applied = { ...it_, status: 'applied' as const, history: [hist(a.event!)] };
		const u = run('undo', { doc: doc2, items: [applied], item: applied });
		expect(after(doc2, u)).toBe(DOC);
		expect(u.event?.command).toBe('undo');
		expect(u.statuses).toEqual({ [it_.id]: 'open' });
	});

	it('follows the replacement when earlier text moved it', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' } });
		const a = run('apply', { doc: DOC, items: [it_], item: it_ });
		const doc2 = 'PREFIX\n' + after(DOC, a);
		const applied = { ...it_, status: 'applied' as const, history: [hist(a.event!)] };
		const u = run('undo', { doc: doc2, items: [applied], item: applied });
		expect(after(doc2, u)).toBe('PREFIX\n' + DOC);
	});

	it('refuses when the user changed the applied text', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'a 14 mm cyst' } });
		const a = run('apply', { doc: DOC, items: [it_], item: it_ });
		const doc2 = after(DOC, a).replace('14 mm', '16 mm');
		const applied = { ...it_, status: 'applied' as const, history: [hist(a.event!)] };
		const u = run('undo', { doc: doc2, items: [applied], item: applied });
		expect(u.error).toBe('changed');
		expect(u.changes).toBeUndefined();
		expect(u.event).toBeUndefined();
	});

	it('inverts an applied removal (empty replacement) using its surrounding text', () => {
		const doc = 'FINDINGS:\nThe liver is normal. No ascites. The spleen is normal.';
		const it_ = item({ edit: { mode: 'remove', find: 'No ascites.' } });
		const a = run('apply', { doc, items: [it_], item: it_ });
		const doc2 = after(doc, a);
		expect(doc2).toBe('FINDINGS:\nThe liver is normal. The spleen is normal.');
		const applied = { ...it_, status: 'applied' as const, history: [hist(a.event!)] };
		const u = run('undo', { doc: doc2, items: [applied], item: applied });
		expect(after(doc2, u)).toBe(doc);
	});

	it('undoes a live pre-applied insert from evidence.undo', () => {
		const original = 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNormal.';
		const written = 'FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNormal.';
		const j1 = original.indexOf('\nIMPRESSION');
		const it_ = item({
			status: 'pre_applied',
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' },
			anchor: span(written, 'No ascites.'),
			evidence: { undo: undoOf(written, j1, j1 + ' No ascites.'.length, '') }
		});
		const u = run('undo', { doc: written, items: [it_], item: it_ });
		expect(after(written, u)).toBe(original);
		expect(u.event?.command).toBe('undo');
		expect(u.statuses).toEqual({ [it_.id]: 'open' });

		// the same after the user typed above it: the span is re-found by its context
		const moved = 'Clinical: pain.\n' + written;
		const u2 = run('undo', { doc: moved, items: [it_], item: it_ });
		expect(after(moved, u2)).toBe('Clinical: pain.\n' + original);
	});

	it('never guesses where a live pre-applied edit sits: no context and no hash match is "changed"', () => {
		const original = 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNormal.';
		const written = 'FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNormal.';
		const j1 = original.indexOf('\nIMPRESSION');
		const it_ = item({
			status: 'pre_applied',
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' },
			anchor: { ...span(written, 'No ascites.'), text_hash: 'h1' },
			evidence: { undo: { final_span: [j1, j1 + 12], original_text: '' } }
		});
		const moved = 'Clinical: pain.\n' + written;
		expect(run('undo', { doc: moved, items: [it_], item: it_ }).error).toBe('changed');
		expect(run('undo', { doc: moved, items: [it_], item: it_, textHash: 'h2' }).error).toBe(
			'changed'
		);
		// the written text itself (hash match): the stored span is exact
		expect(
			after(written, run('undo', { doc: written, items: [it_], item: it_, textHash: 'h1' }))
		).toBe(original);
	});

	it('refuses a pre-applied insert whose text is gone', () => {
		const written = 'FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNormal.';
		const j1 = written.indexOf(' No ascites.');
		const it_ = item({
			status: 'pre_applied',
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' },
			anchor: span(written, 'No ascites.'),
			evidence: { undo: undoOf(written, j1, j1 + 12, '') }
		});
		const edited = written.replace('No ascites.', 'Trace ascites.');
		expect(run('undo', { doc: edited, items: [it_], item: it_ }).error).toBe('changed');
	});

	it('refuses items that were never applied', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'x' } });
		expect(run('undo', { doc: DOC, items: [it_], item: it_ }).error).toBe('not_applied');
	});
});

describe('restore', () => {
	const original = 'FINDINGS:\nThe liver is normal. No ascites. The spleen is normal.';
	const written = 'FINDINGS:\nThe liver is normal. The spleen is normal.';
	const pos = written.indexOf('The spleen');

	it('re-inserts evidence.removed_text at the widget position', () => {
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			lane: 'accuracy',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: pos, end: pos, text: '' },
			evidence: { removed_text: 'No ascites.' }
		});
		const r = run('restore', { doc: written, items: [it_], item: it_, widgetPos: () => pos });
		expect(after(written, r)).toBe(original);
		expect(r.event?.command).toBe('restore');
		expect(r.statuses).toEqual({ [it_.id]: 'open' });

		// a widget sitting just before the separating space
		const r2 = run('restore', { doc: written, items: [it_], item: it_, widgetPos: () => pos - 1 });
		expect(after(written, r2)).toBe(original);
	});

	it('live mode: restores evidence.undo at the span re-found by its context, never at the widget position', () => {
		const i1 = original.indexOf('No ascites. ');
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: pos, end: pos, text: '', text_hash: 'h1' },
			evidence: { removed_text: 'No ascites.', undo: undoOf(written, i1, i1, 'No ascites. ') }
		});
		const moved = 'X\n' + written;
		const r = run('restore', { doc: moved, items: [it_], item: it_, widgetPos: () => 0 });
		expect(after(moved, r)).toBe('X\n' + original);
		expect(r.statuses).toEqual({ [it_.id]: 'open' });

		// the user edited earlier text and the report reloaded: a stale offset would land mid-word
		const edited = written.replace('The liver', 'On review the liver');
		const r2 = run('restore', { doc: edited, items: [it_], item: it_, widgetPos: () => pos });
		expect(after(edited, r2)).toBe(original.replace('The liver', 'On review the liver'));

		// the context itself was edited: refuse rather than guess
		const gone = written.replace('normal. The spleen', 'normal. A spleen');
		expect(run('restore', { doc: gone, items: [it_], item: it_, widgetPos: () => pos }).error).toBe(
			'changed'
		);
		// an evidence.undo without context is placed only on the written text itself
		const bare = {
			...it_,
			evidence: {
				removed_text: 'No ascites.',
				undo: { final_span: [i1, i1] as [number, number], original_text: 'No ascites. ' }
			}
		};
		expect(
			run('restore', { doc: moved, items: [bare], item: bare, widgetPos: () => pos + 2 }).error
		).toBe('changed');
		expect(
			after(written, run('restore', { doc: written, items: [bare], item: bare, textHash: 'h1' }))
		).toBe(original);
	});

	it('refuses to re-insert removed text in the middle of a word', () => {
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: pos, end: pos, text: '' },
			evidence: { removed_text: 'No ascites.' }
		});
		const mid = written.indexOf('spleen') + 3;
		expect(
			run('restore', { doc: written, items: [it_], item: it_, widgetPos: () => mid }).error
		).toBe('changed');
	});

	it('needs a widget position (or a matching text hash) to place the text', () => {
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: pos, end: pos, text: '', text_hash: 'h1' },
			evidence: { removed_text: 'No ascites.' }
		});
		expect(run('restore', { doc: written, items: [it_], item: it_ }).error).toBe('changed');
		const r = run('restore', { doc: written, items: [it_], item: it_, textHash: 'h1' });
		expect(after(written, r)).toBe(original);
	});

	it('only restores removals', () => {
		const it_ = item({ status: 'applied', edit: { mode: 'replace', find: 'a', replace: 'b' } });
		expect(run('restore', { doc: DOC, items: [it_], item: it_ }).error).toBe('not_removal');
	});
});

describe('remove / keep', () => {
	it('remove takes the anchored text out, posts edit and sets applied; undo puts it back', () => {
		const doc = 'FINDINGS:\nThe liver is normal. No ascites. The spleen is normal.';
		const it_ = item({ kind: 'assumed_normal', cls: 'info', anchor: span(doc, 'No ascites.') });
		const r = run('remove', { doc, items: [it_], item: it_ });
		expect(after(doc, r)).toBe('FINDINGS:\nThe liver is normal. The spleen is normal.');
		expect(r.event?.command).toBe('edit');
		expect(r.event?.detail).toMatchObject({ action: 'remove', replacement: '' });
		expect(r.statuses).toEqual({ [it_.id]: 'applied' });
		const applied = { ...it_, status: 'applied' as const, history: [hist(r.event!)] };
		const doc2 = after(doc, r);
		expect(after(doc2, run('undo', { doc: doc2, items: [applied], item: applied }))).toBe(doc);
	});

	it('remove needs anchored text that occurs once', () => {
		const doc = 'A. No ascites. B. No ascites.';
		const it_ = item({ anchor: span(doc, 'No ascites.') });
		expect(run('remove', { doc, items: [it_], item: it_ }).error).toBe('not_found');
		const bare = item({ anchor: null });
		expect(run('remove', { doc, items: [bare], item: bare }).error).toBe('no_edit');
	});

	it('keep changes nothing and posts dismiss with action keep', () => {
		const it_ = item({ kind: 'check', cls: 'minor', anchor: span(DOC, 'The liver is normal.') });
		const r = run('keep', { doc: DOC, items: [it_], item: it_ });
		expect(r.changes).toBeUndefined();
		expect(r.event).toEqual({ itemId: it_.id, command: 'dismiss', detail: { action: 'keep' } });
		expect(r.statuses).toEqual({ [it_.id]: 'dismissed' });
	});
});

describe('dismiss / ask_chat / navigation', () => {
	it('dismiss changes nothing and posts dismiss', () => {
		const it_ = item();
		const r = run('dismiss', { doc: DOC, items: [it_], item: it_ });
		expect(r.changes).toBeUndefined();
		expect(r.event).toEqual({ itemId: it_.id, command: 'dismiss', detail: {} });
		expect(r.statuses).toEqual({ [it_.id]: 'dismissed' });
	});

	it('ask_chat returns a prefill naming the item', () => {
		const it_ = item({
			label: 'Kidney size',
			reason: 'Dictated size missing',
			anchor: span(DOC, 'a cyst')
		});
		const r = run('ask_chat', { doc: DOC, items: [it_], item: it_ });
		expect(r.openChat).toContain('Kidney size');
		expect(r.openChat).toContain('Dictated size missing');
		expect(r.openChat).toContain('"a cyst"');
		expect(r.event?.command).toBe('ask_chat');
		expect(r.statuses).toBeUndefined();
	});

	it('ask_chat with no item takes the text from args (guidelines "Ask"), posting no item event', () => {
		const r = run('ask_chat', { doc: DOC, items: [], item: null, args: { text: 'Re: Bosniak IIF' } });
		expect(r.error).toBeUndefined();
		expect(r.openChat).toBe('Re: Bosniak IIF');
		expect(r.event).toBeUndefined();
		expect(run('ask_chat', { doc: DOC, items: [], item: null }).error).toBe('no_item');
	});

	it('open_item focuses the located anchor and posts view', () => {
		const it_ = item({ anchor: span(DOC, 'a cyst') });
		const r = run('open_item', { doc: DOC, items: [it_], item: it_ });
		expect(r.focus).toEqual({
			itemId: it_.id,
			from: DOC.indexOf('a cyst'),
			to: DOC.indexOf('a cyst') + 6
		});
		expect(r.event?.command).toBe('view');
		expect(r.changes).toBeUndefined();
	});

	it('next_item walks open action/minor items in document order and wraps', () => {
		const a = item({ anchor: span(DOC, 'Left renal cyst.') });
		const b = item({ anchor: span(DOC, 'The liver'), cls: 'minor' });
		const c = item({ anchor: span(DOC, 'a cyst'), status: 'dismissed' });
		const d = item({ anchor: span(DOC, 'left kidney'), cls: 'info' });
		const items = [a, b, c, d];
		expect(run('next_item', { doc: DOC, items }).focus?.itemId).toBe(b.id);
		expect(run('next_item', { doc: DOC, items, item: b }).focus?.itemId).toBe(a.id);
		expect(run('next_item', { doc: DOC, items, item: a }).focus?.itemId).toBe(b.id);
		expect(run('next_item', { doc: DOC, items, item: a }).event).toBeUndefined();
	});
});

describe('apply_all', () => {
	const doc =
		'FINDINGS:\nThe liver is normal. There is a cyst in the left kidney. The spleen is enlarged.';
	const mk = (find: string, replace: string, over: Partial<ReviewItem> = {}) =>
		item({ edit: { mode: 'replace', find, replace } as Edit, anchor: span(doc, find), ...over });

	it('applies each eligible open item in document order, re-locating after earlier edits shift anchors', () => {
		const late = mk('The spleen is enlarged.', 'The spleen is enlarged at 15 cm.');
		const early = mk('a cyst', 'a 14 mm simple cyst');
		const r = run('apply_all', { doc, items: [late, early], args: { lane: 'coverage' } });
		expect(after(doc, r)).toBe(
			'FINDINGS:\nThe liver is normal. There is a 14 mm simple cyst in the left kidney. The spleen is enlarged at 15 cm.'
		);
		expect(r.events?.map((e) => e.itemId)).toEqual([early.id, late.id]);
		expect(r.events?.every((e) => e.command === 'apply')).toBe(true);
		expect(r.statuses).toEqual({ [early.id]: 'applied', [late.id]: 'applied' });

		// each event's position is in the final document, so undo finds it there
		const final = after(doc, r);
		const ev = r.events![1];
		expect(
			final.slice(
				ev.detail.from as number,
				(ev.detail.from as number) + (ev.detail.insert as string).length
			)
		).toBe('The spleen is enlarged at 15 cm.');
		const lateApplied = { ...late, status: 'applied' as const, history: [hist(ev)] };
		const u = run('undo', { doc: final, items: [lateApplied], item: lateApplied });
		expect(after(final, u)).toBe(doc.replace('a cyst', 'a 14 mm simple cyst'));
	});

	it('filters by lane or kind and skips non-open, suppressed or unplaceable items', () => {
		const a = mk('a cyst', 'a 14 mm cyst', { lane: 'accuracy' });
		const b = mk('The liver is normal.', 'The liver is normal in size.', { kind: 'partial' });
		const c = mk('left kidney', 'right kidney', { status: 'dismissed' });
		const d = mk('The spleen', 'Spleen', { cls: 'suppress' });
		const e = mk('pancreas', 'x');
		const byLane = run('apply_all', { doc, items: [a, b, c, d, e], args: { lane: 'coverage' } });
		expect(Object.keys(byLane.statuses ?? {})).toEqual([b.id]);
		expect(byLane.skipped).toEqual([e.id]);
		const byKind = run('apply_all', { doc, items: [a, b, c, d, e], args: { kind: 'partial' } });
		expect(Object.keys(byKind.statuses ?? {})).toEqual([b.id]);
	});

	it('skips an item whose text an earlier edit consumed', () => {
		const a = mk('a cyst in the left kidney', 'a renal cyst');
		const b = mk('left kidney', 'left kidney (lower pole)');
		const r = run('apply_all', { doc, items: [a, b], args: {} });
		expect(after(doc, r)).toBe(doc.replace('a cyst in the left kidney', 'a renal cyst'));
		expect(r.skipped).toEqual([b.id]);
	});

	it('returns nothing to dispatch when no item is eligible', () => {
		const r = run('apply_all', { doc, items: [], args: { lane: 'coverage' } });
		expect(r.changes).toBeUndefined();
		expect(r.events).toEqual([]);
	});
});

describe('registry', () => {
	it('names every command and never sends an engine-only command', () => {
		expect(Object.keys(COMMANDS).sort()).toEqual(
			[
				'apply',
				'apply_all',
				'ask_chat',
				'dismiss',
				'edit',
				'finalise',
				'keep',
				'next_item',
				'open_item',
				'remove',
				'rerun',
				'restore',
				'undo'
			].sort()
		);
	});

	it('rerun and finalise only describe the request', () => {
		const a = item({ status: 'applied' });
		const p = item({ status: 'pre_applied' });
		const o = item();
		expect(run('rerun', { doc: DOC, items: [a] })).toEqual({ request: { type: 'rerun' } });
		expect(run('finalise', { doc: DOC, items: [a, p, o] })).toEqual({
			request: { type: 'finalise', applied: [a.id, p.id] }
		});
	});

	it('commands that need an item say so', () => {
		for (const name of [
			'apply',
			'edit',
			'undo',
			'dismiss',
			'restore',
			'ask_chat',
			'open_item',
			'remove',
			'keep'
		] as const) {
			expect(run(name, { doc: DOC, items: [] }).error).toBe('no_item');
		}
	});

	it('is pure: never mutates the items it is given', () => {
		const it_ = item({ edit: { mode: 'replace', find: 'a cyst', replace: 'x' } });
		const snap = JSON.stringify(it_);
		run('apply', { doc: DOC, items: [it_], item: it_ });
		run('dismiss', { doc: DOC, items: [it_], item: it_ });
		expect(JSON.stringify(it_)).toBe(snap);
	});
});

describe('re-apply after undo / restore of a pre-applied item', () => {
	const PRE = { event: 'pre_applied', actor: 'post_check', detail: {} } as HistoryEntry;

	it('apply after undoing a post-check insertion puts back exactly what the check wrote; undo works again', () => {
		const original = 'FINDINGS:\nThe liver is normal.\nIMPRESSION:\nNormal.';
		const written = 'FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNormal.';
		const j1 = original.indexOf('\nIMPRESSION');
		let it_ = item({
			status: 'pre_applied',
			// an edit that could not place itself here (no such anchor): the inverse must not depend on it
			edit: {
				mode: 'insert',
				after: 'Not in the report.',
				section: 'FINDINGS',
				replace: 'No ascites.'
			},
			anchor: span(written, 'No ascites.'),
			evidence: { undo: undoOf(written, j1, j1 + ' No ascites.'.length, '') },
			history: [PRE]
		});
		const u = run('undo', { doc: written, items: [it_], item: it_ });
		const undone = after(written, u);
		expect(undone).toBe(original);
		it_ = { ...it_, status: 'open', history: [...it_.history, hist(u.event!)] };

		const a = run('apply', { doc: undone, items: [it_], item: it_, sections: SECTIONS });
		expect(a.error).toBeUndefined();
		const reapplied = after(undone, a);
		expect(reapplied).toBe(written);
		expect(a.event?.command).toBe('apply');
		expect(a.statuses).toEqual({ [it_.id]: 'applied' });

		it_ = { ...it_, status: 'applied', history: [...it_.history, hist(a.event!)] };
		expect(after(reapplied, run('undo', { doc: reapplied, items: [it_], item: it_ }))).toBe(
			original
		);
	});

	it('apply after restoring a removal whose clause occurs twice removes the restored occurrence', () => {
		const original =
			'FINDINGS:\nNo ascites. The liver is normal.\nIMPRESSION:\nNo ascites. Normal study.';
		const written = 'FINDINGS:\nNo ascites. The liver is normal.\nIMPRESSION:\nNormal study.';
		const i1 = written.indexOf('Normal study.');
		let it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.', section: 'IMPRESSION' },
			anchor: { start: i1, end: i1, text: '', text_hash: 'h1' },
			evidence: { removed_text: 'No ascites.', undo: undoOf(written, i1, i1, 'No ascites. ') },
			history: [PRE]
		});
		const r = run('restore', { doc: written, items: [it_], item: it_ });
		const restored = after(written, r);
		expect(restored).toBe(original);
		it_ = { ...it_, status: 'open', history: [...it_.history, hist(r.event!)] };

		const a = run('apply', { doc: restored, items: [it_], item: it_, sections: SECTIONS });
		expect(after(restored, a)).toBe(written);

		// the restored text was changed since: refuse rather than guess
		const edited = restored.replace('No ascites. Normal', 'No free fluid. Normal');
		expect(run('apply', { doc: edited, items: [it_], item: it_ }).error).toBe('changed');
	});

	it('records where the reverted text now sits in the undo / restore event', () => {
		const written = 'FINDINGS:\nNo ascites. The liver is normal.\nIMPRESSION:\nNormal study.';
		const i1 = written.indexOf('Normal study.');
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: i1, end: i1, text: '', text_hash: 'h1' },
			evidence: { removed_text: 'No ascites.', undo: undoOf(written, i1, i1, 'No ascites. ') },
			history: [PRE]
		});
		const r = run('restore', { doc: written, items: [it_], item: it_ });
		expect(r.event?.detail).toEqual({
			from: i1,
			to: i1,
			insert: 'No ascites. ',
			removed: '',
			left: written.slice(i1 - 16, i1),
			right: written.slice(i1, i1 + 16)
		});
	});
});

describe('adjacent recommendations (remove / undo in any order)', () => {
	// SYNTHETIC: two recommendation clauses on one line, as the provenance pass emits them.
	const A = 'CT thorax is recommended for staging;';
	const B = 'EUS sampling is advised.';
	const D = `IMPRESSION:\nPancreatic mass. ${A} ${B}`;
	const recOf = (text: string, doc = D) =>
		item({
			kind: 'recommendation',
			cls: 'minor',
			lane: 'additions',
			anchor: span(doc, text),
			edit: { mode: 'remove', find: text }
		});

	/** Toggle one recommendation's checkbox (remove when in the report, undo when removed) against `doc`, with
	 * every item in context, the item updated as the store would. */
	function toggle(doc: string, all: ReviewItem[], id: string): [string, ReviewItem[]] {
		const it = all.find((i) => i.id === id)!;
		const name = it.status === 'applied' ? 'undo' : 'remove';
		const r = run(name, { doc, items: all, item: it });
		expect(r.error, `${name} ${it.anchor?.text} on ${JSON.stringify(doc)}`).toBeUndefined();
		const next = { ...it, status: r.statuses![it.id], history: [...it.history, hist(r.event!)] };
		return [after(doc, r), all.map((i) => (i.id === id ? next : i))];
	}

	function walk(d0: string, texts: string[], seq: number[]): void {
		let items = texts.map((t) => recOf(t, d0));
		let doc = d0;
		for (const k of seq) {
			[doc, items] = toggle(doc, items, items[k].id);
			items.forEach((i, j) => {
				const there = findRecText(doc, texts[j]);
				expect(!!there, `${texts[j]} in ${JSON.stringify(doc)}`).toBe(i.status !== 'applied');
			});
			if (items.every((i) => i.status !== 'applied')) expect(doc).toBe(d0);
		}
	}

	it('the stuck sequence: re-ticking one after its neighbour was removed puts it back, in order', () => {
		walk(D, [A, B], [0, 1, 0, 1]); // remove A, remove B, restore A, restore B
		walk(D, [A, B], [1, 0, 1, 0]);
		walk(D, [A, B], [0, 1, 1, 0]);
		walk(D, [A, B], [1, 0, 0, 1]);
	});

	it('any toggle order, many cycles, keeps every checkbox working (seeded walk, three neighbours)', () => {
		const C = 'urgent MDT referral for treatment planning.';
		const d3 = `IMPRESSION:\nPancreatic mass. ${A} EUS sampling for diagnosis; ${C}\n\nDr A Person`;
		let seed = 7;
		const rnd = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) % 3;
		walk(d3, [A, 'EUS sampling for diagnosis;', C], Array.from({ length: 60 }, rnd));
	});

	it('removes a neighbour the first removal re-cased; restoring both brings back the text as written', () => {
		const b2 = 'tissue sampling is advised.';
		const d2 = `IMPRESSION:\nPancreatic mass. ${A} ${b2}`;
		walk(d2, [A, b2], [0, 1, 1, 0, 0, 1, 0, 1]);
	});
});
