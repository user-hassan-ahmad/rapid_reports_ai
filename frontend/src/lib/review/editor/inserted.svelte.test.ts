import { afterEach, describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import type { ReviewItem } from '../types';
import { runCommand } from '../commands';
import { commandTransaction, fromItems, reviewItems } from './field';
import { reviewExtensions, setEmphasis } from './index';
import { chatItem } from '../chat';

// SYNTHETIC report with one suggestion (an option item) per test.
const DOC = 'FINDINGS:\nThe pancreas has a mass. No ascites.\n\nIMPRESSION:\nPancreatic mass.';
const TEXT = 'No portal vein thrombosis.';

function sugg(over: Partial<ReviewItem> = {}): ReviewItem {
	return {
		id: 'o1',
		key: 'o1',
		report_id: 'r',
		run_id: 'run',
		lane: 'additions',
		kind: 'option',
		cls: 'minor',
		detectors: [],
		label: '',
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		section: 'FINDINGS',
		edit: { mode: 'insert', after: 'The pancreas has a mass.', replace: TEXT },
		...over
	};
}

const views: EditorView[] = [];
afterEach(() => {
	vi.useRealTimers();
	for (const v of views.splice(0)) {
		v.dom.remove();
		v.destroy();
	}
});

function mount(doc: string, items: ReviewItem[]) {
	const state = EditorState.create({
		doc,
		extensions: reviewExtensions({
			onCommand: () => {},
			getItem: (id) => items.find((i) => i.id === id),
			initial: fromItems(doc, items).items
		})
	});
	const parent = document.createElement('div');
	document.body.append(parent);
	const view = new EditorView({ state, parent });
	views.push(view);
	return view;
}

/** Tick: run the apply command and dispatch its transaction, as the viewer does. Returns the applied item. */
function tickIt(view: EditorView, item: ReviewItem): ReviewItem {
	const r = runCommand('apply', { doc: view.state.doc.toString(), items: [item], item });
	view.dispatch(commandTransaction(view.state, r, [item]));
	return { ...item, status: 'applied', history: [{ event: 'apply', detail: r.event!.detail } as never] };
}

const tinted = (view: EditorView) => [...view.dom.querySelectorAll('.rv-inserted')].map((e) => e.textContent).join('|');

describe('inserted suggestion text', () => {
	it('an applied chat edit tints its new text and flashes it, like a ticked suggestion', () => {
		const chat = { ...chatItem('r', 'm1', 0, { section: 'FINDINGS', find: 'No ascites.', replace: 'No ascites or free fluid.' }), status: 'open' as const };
		const view = mount(DOC, [chat]);
		tickIt(view, chat);
		expect(view.state.doc.toString()).toContain('No ascites or free fluid.');
		expect(tinted(view)).toBe('No ascites or free fluid.');
		expect(view.dom.querySelector('.rv-inserted-flash')?.textContent).toBe('No ascites or free fluid.');
	});

	it('ticking tints exactly the inserted text; unticking removes text and tint', () => {
		const open = sugg();
		const view = mount(DOC, [open]);
		expect(tinted(view)).toBe('');
		const applied = tickIt(view, open);
		expect(view.state.doc.toString()).toContain(`mass. ${TEXT} No ascites.`);
		expect(tinted(view)).toBe(TEXT);
		const r = runCommand('undo', { doc: view.state.doc.toString(), items: [applied], item: applied });
		view.dispatch(commandTransaction(view.state, r, [applied]));
		expect(view.state.doc.toString()).toBe(DOC);
		expect(tinted(view)).toBe('');
		expect(reviewItems(view.state).inserted).toEqual([]);
	});

	it('the mark maps through edits before it', () => {
		const view = mount(DOC, [sugg()]);
		tickIt(view, sugg());
		view.dispatch({ changes: { from: 0, insert: 'XX' } });
		expect(tinted(view)).toBe(TEXT);
	});

	it('a reload with an applied option still shows the tint (located from its apply event)', () => {
		const open = sugg();
		const probe = mount(DOC, [open]);
		const applied = tickIt(probe, open);
		const after = probe.state.doc.toString();
		const view = mount(after, [applied]);
		expect(tinted(view)).toBe(TEXT);
	});

	it('shows in Key and All, hidden in Off', () => {
		const open = sugg();
		const view = mount(DOC, [open]);
		tickIt(view, open);
		const el = view.dom.querySelector<HTMLElement>('.rv-inserted')!;
		const bg = () => getComputedStyle(el).backgroundColor;
		view.dispatch({ effects: setEmphasis.of(['ai']) });
		const key = bg();
		expect(key).not.toBe('rgba(0, 0, 0, 0)');
		view.dispatch({ effects: setEmphasis.of(['ai', 'normals']) });
		expect(bg()).toBe(key);
		view.dispatch({ effects: setEmphasis.of([]) });
		expect(bg()).toBe('rgba(0, 0, 0, 0)');
	});

	it('ticking flashes the inserted range for about 1.2 s, then clears', async () => {
		vi.useFakeTimers();
		const open = sugg();
		const view = mount(DOC, [open]);
		tickIt(view, open);
		expect([...view.dom.querySelectorAll('.rv-inserted-flash')].map((e) => e.textContent).join('')).toBe(TEXT);
		vi.advanceTimersByTime(1300);
		expect(view.dom.querySelector('.rv-inserted-flash')).toBeNull();
		expect(tinted(view)).toBe(TEXT); // the tint stays
	});
});
