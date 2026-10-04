import { ChangeSet, Text } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import {
	COMMANDS,
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
			evidence: { undo: { final_span: [j1, j1 + ' No ascites.'.length], original_text: '' } }
		});
		const u = run('undo', { doc: written, items: [it_], item: it_ });
		expect(after(written, u)).toBe(original);
		expect(u.event?.command).toBe('undo');
		expect(u.statuses).toEqual({ [it_.id]: 'open' });

		// the same after the user typed above it: the span moves with the anchor
		const moved = 'Clinical: pain.\n' + written;
		const u2 = run('undo', { doc: moved, items: [it_], item: it_ });
		expect(after(moved, u2)).toBe('Clinical: pain.\n' + original);
	});

	it('refuses a pre-applied insert whose text is gone', () => {
		const written = 'FINDINGS:\nThe liver is normal. No ascites.\nIMPRESSION:\nNormal.';
		const j1 = written.indexOf(' No ascites.');
		const it_ = item({
			status: 'pre_applied',
			edit: { mode: 'insert', after: null, section: 'FINDINGS', replace: 'No ascites.' },
			anchor: span(written, 'No ascites.'),
			evidence: { undo: { final_span: [j1, j1 + 12], original_text: '' } }
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

	it('prefers evidence.undo (live mode) and maps it through the widget position', () => {
		const i1 = original.indexOf('No ascites. ');
		const it_ = item({
			kind: 'removed',
			status: 'pre_applied',
			edit: { mode: 'remove', find: 'No ascites.' },
			anchor: { start: pos, end: pos, text: '' },
			evidence: {
				removed_text: 'No ascites.',
				undo: { final_span: [i1, i1], original_text: 'No ascites. ' }
			}
		});
		const moved = 'X\n' + written;
		const r = run('restore', { doc: moved, items: [it_], item: it_, widgetPos: () => pos + 2 });
		expect(after(moved, r)).toBe('X\n' + original);
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
				'next_item',
				'open_item',
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
			'open_item'
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
