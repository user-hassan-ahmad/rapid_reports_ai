import { afterEach, describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import type { ReviewItem } from '../types';
import { fromItems } from './field';
import { reviewExtensions, setDensity, openPopover, LABELS } from './index';

// Tiny SYNTHETIC report: a dictated finding, a green normal, an amber check, an action item with an edit, a
// pre-applied insert, a removed (red) widget and an option.
const DICTATED = 'Simple cyst in the left kidney.';
const GREEN = 'The liver is normal.';
const AMBER = 'No hydronephrosis.';
const ACTION = 'The spleen measures 9 cm.';
const ADDED = 'No renal calculi.';
const REMOVED = 'The kidneys are normal.';
const OPTION = 'No free fluid.';
const report = `${DICTATED} ${GREEN} ${AMBER} ${ACTION} ${ADDED}`;

function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id' | 'kind' | 'cls'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		label: '',
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

function span(text: string) {
	const start = report.indexOf(text);
	return { start, end: start + text.length, text };
}

const ITEMS: ReviewItem[] = [
	item({ id: 'g1', kind: 'assumed_normal', cls: 'info', anchor: span(GREEN) }),
	item({
		id: 'c1',
		kind: 'check',
		cls: 'minor',
		anchor: span(AMBER),
		evidence: { check_reason: 'uncertain', pointer: 'simple cyst left kidney' }
	}),
	item({
		id: 'a1',
		kind: 'measurement',
		cls: 'action',
		lane: 'accuracy',
		label: 'Measurement differs',
		reason: 'The dictation gives 11 cm.',
		source_line: 'spleen eleven centimetres',
		anchor: span('9 cm'),
		edit: { mode: 'replace', find: '9 cm', replace: '11 cm' }
	}),
	item({
		id: 'p1',
		kind: 'omission',
		cls: 'action',
		status: 'pre_applied',
		label: 'Added from your dictation',
		reason: 'You dictated it.',
		anchor: span(ADDED),
		edit: { mode: 'insert', after: ACTION, replace: ADDED }
	}),
	item({
		id: 'r1',
		kind: 'removed',
		cls: 'action',
		status: 'pre_applied',
		anchor: { start: DICTATED.length, end: DICTATED.length, text: '' },
		evidence: { removed_text: REMOVED, pointer: 'kidneys: simple cyst' }
	}),
	item({
		id: 'o1',
		kind: 'option',
		cls: 'minor',
		lane: 'additions',
		reason: 'often reported',
		edit: { mode: 'insert', after: AMBER, replace: OPTION }
	})
];

const views: EditorView[] = [];
afterEach(() => {
	for (const v of views.splice(0)) {
		v.dom.remove();
		v.destroy();
	}
});

function mount(opts: Partial<Parameters<typeof reviewExtensions>[0]> = {}) {
	const onCommand = vi.fn();
	const byId = new Map(ITEMS.map((i) => [i.id, i]));
	const state = EditorState.create({
		doc: report,
		extensions: reviewExtensions({
			onCommand,
			getItem: (id) => byId.get(id),
			initial: fromItems(report, ITEMS).items,
			...opts
		})
	});
	const parent = document.createElement('div');
	document.body.append(parent);
	const view = new EditorView({ state, parent });
	views.push(view);
	return { view, onCommand };
}

const tick = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

function markEl(view: EditorView, id: string): HTMLElement {
	const el = view.dom.querySelector<HTMLElement>(`[data-rv-id="${id}"]`);
	if (!el) throw new Error(`no mark ${id}`);
	return el;
}

function click(el: Element) {
	el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
}

function popover(view: EditorView): HTMLElement | null {
	return view.dom.querySelector<HTMLElement>('.rv-popover');
}

function buttonIn(root: Element, name: string): HTMLButtonElement {
	const b = [...root.querySelectorAll('button')].find((x) => x.textContent?.trim() === name);
	if (!b) throw new Error(`no button ${name} in ${root.textContent}`);
	return b as HTMLButtonElement;
}

async function openOn(view: EditorView, id: string): Promise<HTMLElement> {
	click(markEl(view, id));
	await tick();
	const p = popover(view);
	if (!p) throw new Error('popover did not open');
	return p;
}

describe('review decorations', () => {
	it('renders marks with their class, id and accessible name', () => {
		const { view } = mount();
		const g = markEl(view, 'g1');
		expect(g.classList.contains('rv-normal')).toBe(true);
		expect(g.textContent).toBe(GREEN);
		expect(g.getAttribute('aria-label')).toContain(LABELS.normal);
		const c = markEl(view, 'c1');
		expect(c.classList.contains('rv-check')).toBe(true);
		expect(c.getAttribute('aria-label')).toContain(LABELS.check);
		expect(markEl(view, 'a1').classList.contains('rv-action')).toBe(true);
		expect(markEl(view, 'p1').classList.contains('rv-preapplied')).toBe(true);
	});

	it('Quiet density by default, on the editor element; setDensity changes it', async () => {
		const { view } = mount();
		expect(view.dom.dataset.density).toBe('quiet');
		view.dispatch({ effects: setDensity.of('full') });
		expect(view.dom.dataset.density).toBe('full');
		const { view: v2 } = mount({ density: 'hidden' });
		expect(v2.dom.dataset.density).toBe('hidden');
	});

	it('clicking a mark opens the popover with label, reason, dictation and the edit as a diff', async () => {
		const { view } = mount();
		const p = await openOn(view, 'a1');
		expect(p.textContent).toContain('Measurement differs');
		expect(p.textContent).toContain('The dictation gives 11 cm.');
		expect(p.textContent).toContain('You dictated: “spleen eleven centimetres”');
		expect(p.querySelector('del')?.textContent).toBe('9 cm');
		expect(p.querySelector('ins')?.textContent).toBe('11 cm');
		for (const name of ['Apply', 'Edit', 'Dismiss']) expect(buttonIn(p, name)).toBeTruthy();
	});

	it('Apply dispatches the command callback and closes the popover', async () => {
		const { view, onCommand } = mount();
		const p = await openOn(view, 'a1');
		click(buttonIn(p, 'Apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1', undefined);
		await tick();
		expect(popover(view)).toBeNull();
	});

	it('Escape closes the popover', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await tick();
		expect(popover(view)).toBeNull();
	});

	it('Edit opens an inline input; confirming sends the edit command with the replacement', async () => {
		const { view, onCommand } = mount();
		const p = await openOn(view, 'a1');
		click(buttonIn(p, 'Edit'));
		const input = p.querySelector('input') as HTMLInputElement;
		expect(input.value).toBe('11 cm');
		input.value = '12 cm';
		input.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
		);
		expect(onCommand).toHaveBeenCalledWith('edit', 'a1', { replacement: '12 cm' });
	});

	it('a check offers Keep / Remove', async () => {
		const { view, onCommand } = mount();
		const p = await openOn(view, 'c1');
		expect(p.textContent).toContain('one of your findings makes it uncertain');
		expect(p.textContent).toContain('simple cyst left kidney');
		click(buttonIn(p, 'Keep'));
		expect(onCommand).toHaveBeenCalledWith('keep', 'c1', undefined);
		const p2 = await openOn(view, 'c1');
		click(buttonIn(p2, 'Remove'));
		expect(onCommand).toHaveBeenCalledWith('remove', 'c1', undefined);
	});

	it('a pre-applied insert offers Undo', async () => {
		const { view, onCommand } = mount();
		const p = await openOn(view, 'p1');
		expect(() => buttonIn(p, 'Apply')).toThrow();
		click(buttonIn(p, 'Undo'));
		expect(onCommand).toHaveBeenCalledWith('undo', 'p1', undefined);
	});

	it("a removed widget's text is shown but is not in the document; Restore dispatches restore", () => {
		const { view, onCommand } = mount();
		const w = view.dom.querySelector<HTMLElement>('[data-rv-widget="r1"]')!;
		expect(w.textContent).toContain(REMOVED);
		expect(w.getAttribute('aria-label')).toContain(LABELS.removed);
		expect(view.state.doc.toString()).not.toContain(REMOVED);
		click(buttonIn(w, 'Restore'));
		expect(onCommand).toHaveBeenCalledWith('restore', 'r1', undefined);
	});

	it('an option widget is not in the document; Include dispatches apply', () => {
		const { view, onCommand } = mount();
		const w = view.dom.querySelector<HTMLElement>('[data-rv-widget="o1"]')!;
		expect(w.textContent).toContain(OPTION);
		expect(w.getAttribute('aria-label')).toContain(LABELS.option);
		expect(view.state.doc.toString()).not.toContain(OPTION);
		click(buttonIn(w, 'Include'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'o1', undefined);
	});

	it('draws a gutter marker per item line, keyed by cls, with an accessible name', () => {
		const { view } = mount();
		const markers = [...view.dom.querySelectorAll<HTMLElement>('.rv-gutter-marker')];
		expect(markers.length).toBe(1); // one line: the highest cls wins
		expect(markers[0].classList.contains('rv-gutter-action')).toBe(true);
		expect(markers[0].getAttribute('aria-label')).toBeTruthy();
	});

	it('defines --rv-* tokens on the editor (light by default)', () => {
		const { view } = mount();
		expect(getComputedStyle(view.dom).getPropertyValue('--rv-red-line').trim()).toBe('#cf3b3b');
	});

	it('openPopover with an unknown id shows nothing', async () => {
		const { view } = mount();
		view.dispatch({ effects: openPopover.of('nope') });
		await tick();
		expect(popover(view)).toBeNull();
	});
});
