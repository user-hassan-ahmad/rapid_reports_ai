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

function chip(view: EditorView): HTMLElement | null {
	return view.dom.querySelector<HTMLElement>('.rv-chip');
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

function hoverOn(el: Element) {
	el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
}

function actionsOf(c: Element): string[] {
	return [...c.querySelectorAll('button')].map((b) => b.getAttribute('data-rv-chip-action') ?? '');
}

function actionBtn(c: Element, action: string): HTMLButtonElement {
	const b = c.querySelector<HTMLButtonElement>(`button[data-rv-chip-action="${action}"]`);
	if (!b) throw new Error(`no ${action} in chip ${c.textContent}`);
	return b;
}

function targetEl(view: EditorView, id: string): HTMLElement {
	return (
		view.dom.querySelector<HTMLElement>(`[data-rv-id="${id}"]`) ??
		view.dom.querySelector<HTMLElement>(`[data-rv-widget="${id}"]`)!
	);
}

/** Click / tap opens the chip at once. */
async function openOn(view: EditorView, id: string): Promise<HTMLElement> {
	click(targetEl(view, id));
	await tick();
	const c = chip(view);
	if (!c || c.getAttribute('data-rv-chip') !== id) throw new Error('chip did not open');
	return c;
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

	it('hovering a mark opens its chip after ~200 ms: one line, icon + rationale + icon buttons', async () => {
		const { view } = mount();
		hoverOn(markEl(view, 'a1'));
		await pause(60);
		expect(chip(view)).toBeNull(); // not instant
		await pause(250);
		const c = chip(view)!;
		expect(c).not.toBeNull();
		expect(c.getAttribute('data-rv-chip')).toBe('a1');
		expect(c.querySelector('.rv-chip-icon')!.textContent).toBe('✕');
		expect(c.querySelector('.rv-chip-text')!.textContent).toBe('Measurement differs');
		expect(actionsOf(c)).toEqual(['apply', 'dismiss', 'reveal']);
		for (const b of c.querySelectorAll('button')) {
			expect(b.getAttribute('aria-label')).toBeTruthy();
			expect(b.title).toBeTruthy();
		}
		// one line, no diff box, no Edit
		expect(c.querySelector('del, ins, input')).toBeNull();
		expect(c.getBoundingClientRect().height).toBeLessThan(34);
	});

	it('chips by type: check, normal, pre-applied, removed and option widgets', async () => {
		const { view } = mount();
		const cases: [string, string, string, string[]][] = [
			['c1', '?', 'given “simple cyst left kidney”', ['keep', 'remove', 'reveal']],
			['g1', '✓', 'assumed normal', ['remove', 'reveal']],
			['p1', '↶', 'added from your dictation', ['undo', 'reveal']],
			['r1', '↺', 'contradicts your dictation', ['restore', 'reveal']],
			['o1', '+', 'suggested', ['apply', 'reveal']]
		];
		for (const [id, icon, text, actions] of cases) {
			const c = await openOn(view, id);
			expect(c.getAttribute('data-rv-chip')).toBe(id);
			expect(c.querySelector('.rv-chip-icon')!.textContent).toBe(icon);
			expect(c.querySelector('.rv-chip-text')!.textContent).toBe(text);
			expect(actionsOf(c)).toEqual(actions);
		}
	});

	it('chip buttons run the commands through the command callback and close the chip', async () => {
		const { view, onCommand } = mount();
		click(actionBtn(await openOn(view, 'c1'), 'keep'));
		expect(onCommand).toHaveBeenCalledWith('keep', 'c1', undefined);
		click(actionBtn(await openOn(view, 'r1'), 'restore'));
		expect(onCommand).toHaveBeenCalledWith('restore', 'r1', undefined);
		click(actionBtn(await openOn(view, 'o1'), 'apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'o1', undefined);
		click(actionBtn(await openOn(view, 'a1'), 'apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1', undefined);
		await tick();
		expect(chip(view)).toBeNull();
	});

	it('after an action the range ticks and fades (no toast)', async () => {
		const { view } = mount();
		click(actionBtn(await openOn(view, 'c1'), 'keep'));
		await tick();
		expect(view.dom.querySelector('.rv-flash')?.textContent).toBe(AMBER);
		expect(view.dom.querySelector('.rv-flash-tick')).not.toBeNull();
		await pause(800);
		expect(view.dom.querySelector('.rv-flash')).toBeNull();
	});

	it('the chip stays open while the pointer is on it and closes when it leaves', async () => {
		const { view } = mount();
		const mark = markEl(view, 'a1');
		const c = await openOn(view, 'a1');
		mark.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: c }));
		c.dispatchEvent(new MouseEvent('mouseenter'));
		await pause(400);
		expect(chip(view)).not.toBeNull();
		c.dispatchEvent(new MouseEvent('mouseleave'));
		await pause(400);
		expect(chip(view)).toBeNull();
	});

	it('Escape closes the chip', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await tick();
		expect(chip(view)).toBeNull();
	});

	it('keyboard: the caret moving into a mark opens its chip; Tab moves focus onto its buttons', async () => {
		const { view } = mount();
		const at = report.indexOf(AMBER) + 2;
		view.focus();
		view.dispatch({ selection: { anchor: at }, userEvent: 'select' });
		await tick();
		expect(chip(view)?.getAttribute('data-rv-chip')).toBe('c1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
		);
		expect(document.activeElement?.getAttribute('data-rv-chip-action')).toBe('keep');
		view.dispatch({ selection: { anchor: 0 }, userEvent: 'select' });
		await tick();
		expect(chip(view)).toBeNull();
	});

	it('› asks the host to show the item in the rail', async () => {
		const onReveal = vi.fn();
		const { view, onCommand } = mount({ onReveal });
		click(actionBtn(await openOn(view, 'c1'), 'reveal'));
		expect(onReveal).toHaveBeenCalledWith('c1');
		expect(onCommand).not.toHaveBeenCalled();
	});

	it('hovering ⏎ previews the fix inline: old struck, new as ghost text; leaving clears it', async () => {
		const { view } = mount();
		const c = await openOn(view, 'a1');
		const apply = actionBtn(c, 'apply');
		apply.dispatchEvent(new MouseEvent('mouseenter'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del')?.textContent).toBe('9 cm');
		expect(view.dom.querySelector('.rv-preview-ins')?.textContent).toBe('11 cm');
		expect(view.state.doc.toString()).toBe(report); // a preview, not an edit
		expect(view.dom.querySelector('.rv-chip del, .rv-chip ins')).toBeNull(); // no diff box
		apply.dispatchEvent(new MouseEvent('mouseleave'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del, .rv-preview-ins')).toBeNull();
	});

	it("widgets show their text but are not in the document (removed, option)", () => {
		const { view } = mount();
		const r = view.dom.querySelector<HTMLElement>('[data-rv-widget="r1"]')!;
		expect(r.textContent).toContain(REMOVED);
		expect(r.getAttribute('aria-label')).toContain(LABELS.removed);
		const o = view.dom.querySelector<HTMLElement>('[data-rv-widget="o1"]')!;
		expect(o.textContent).toContain(OPTION);
		expect(o.getAttribute('aria-label')).toContain(LABELS.option);
		expect(view.state.doc.toString()).not.toContain(REMOVED);
		expect(view.state.doc.toString()).not.toContain(OPTION);
		expect(r.querySelector('button')).toBeNull(); // actions live on the chip
	});

	it('quiet at rest: every mark is a thin underline with no fill', () => {
		const { view } = mount();
		for (const id of ['g1', 'c1', 'a1', 'p1']) {
			const cs = getComputedStyle(markEl(view, id));
			expect(cs.backgroundColor, id).toBe('rgba(0, 0, 0, 0)');
			expect(cs.textDecorationLine, id).toContain('underline');
			expect(cs.textDecorationThickness, id).toBe('1px');
		}
	});

	it('the open chip lights its mark (full colour + tint)', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		const lit = view.dom.querySelector<HTMLElement>('.rv-active')!;
		expect(lit.textContent).toBe('9 cm');
		const bg = getComputedStyle(lit.querySelector('.rv-action') ?? lit).backgroundColor;
		expect(bg).not.toBe('rgba(0, 0, 0, 0)');
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
		expect(chip(view)).toBeNull();
	});
});

describe('chip inside the report editor', () => {
	it('stays visible when the host theme hides .cm-tooltip (ReportEditor does)', async () => {
		const byId = new Map(ITEMS.map((i) => [i.id, i]));
		const hostTheme = EditorView.theme({ '.cm-tooltip': { display: 'none' } }, { dark: true });
		const state = EditorState.create({
			doc: report,
			extensions: [
				hostTheme,
				reviewExtensions({
					onCommand: vi.fn(),
					getItem: (id) => byId.get(id),
					initial: fromItems(report, ITEMS).items
				})
			]
		});
		const parent = document.createElement('div');
		document.body.append(parent);
		const view = new EditorView({ state, parent });
		views.push(view);
		const p = await openOn(view, 'c1');
		expect(getComputedStyle(p).display).not.toBe('none');
	});
});

describe('chip placement never covers text', () => {
	// SYNTHETIC prose in a narrow wrapped editor: two paragraphs separated by a blank line.
	const FILL = 'The structure is unremarkable and the adjacent tissues are preserved without change. ';
	const P1 = FILL.repeat(3) + 'Last words here.';
	const P2 = 'Mark here starts the second paragraph. ' + FILL.repeat(2);
	const DEFAULT_DOC = `${P1}\n\n${P2}`;

	function textRects(view: EditorView): DOMRect[] {
		const out: DOMRect[] = [];
		const walk = document.createTreeWalker(view.contentDOM, NodeFilter.SHOW_TEXT);
		for (let n = walk.nextNode(); n; n = walk.nextNode()) {
			if (!n.textContent?.trim()) continue;
			const r = document.createRange();
			r.selectNodeContents(n);
			out.push(...[...r.getClientRects()].filter((x) => x.width > 0 && x.height > 0));
		}
		return out;
	}
	const hits = (a: DOMRect, b: DOMRect) =>
		a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;

	function mountAt(text: string, top = 200, DOC = DEFAULT_DOC) {
		const start = DOC.indexOf(text);
		const it_ = item({ id: 'k', kind: 'check', cls: 'minor', anchor: { start, end: start + text.length, text }, evidence: { check_reason: 'uncertain', pointer: 'a dictated finding' } });
		const state = EditorState.create({
			doc: DOC,
			extensions: [
				EditorView.lineWrapping,
				EditorView.theme({ '.cm-content': { fontSize: '16px', lineHeight: '1.6', fontFamily: 'sans-serif' } }),
				reviewExtensions({ onCommand: vi.fn(), getItem: () => it_, initial: fromItems(DOC, [it_]).items })
			]
		});
		const parent = document.createElement('div');
		parent.style.cssText = `position:absolute;left:20px;top:${top}px;width:440px`;
		document.body.append(parent);
		const view = new EditorView({ state, parent });
		views.push(view);
		return view;
	}

	async function placed(view: EditorView) {
		const c = await openOn(view, 'k');
		await pause(200); // past the chip's fade-and-rise
		await tick();
		const rects = [...view.dom.querySelectorAll<HTMLElement>('[data-rv-id="k"]')].flatMap((e) => [...e.getClientRects()]);
		const markTop = Math.min(...rects.map((r) => r.top));
		const markBottom = Math.max(...rects.map((r) => r.bottom));
		return { chip: c.getBoundingClientRect(), markTop, markBottom, text: textRects(view) };
	}

	it('sits clear above the mark when the space above is free (blank line), over no text', async () => {
		const { chip: r, markTop, text } = await placed(mountAt('Mark here'));
		expect(r.bottom).toBeLessThanOrEqual(markTop);
		expect(text.filter((t) => hits(r, t))).toEqual([]);
	});

	it('goes below when the line above is full text and the line below is free', async () => {
		const { chip: r, markBottom, text } = await placed(mountAt('Last words here.'));
		expect(r.top).toBeGreaterThanOrEqual(markBottom);
		expect(text.filter((t) => hits(r, t))).toEqual([]);
	});

	it('mid-paragraph (full lines above and below): moves to the nearest text-free spot, never over text', async () => {
		const doc = `FINDINGS:\n${'The structure is unremarkable and the adjacent tissues are preserved without change. '.repeat(1)}Target mark sits here. ${FILL.repeat(3)}`;
		const view = mountAt('Target mark', 200, doc);
		const { chip: r, markTop, markBottom, text } = await placed(view);
		expect(r.bottom <= markTop || r.top >= markBottom).toBe(true);
		expect(text.filter((t) => hits(r, t))).toEqual([]);
	});

	it('goes below when there is no room above (top of the viewport)', async () => {
		const view = mountAt('The structure', 0);
		const { chip: r, markBottom } = await placed(view);
		expect(r.top).toBeGreaterThanOrEqual(markBottom);
	});
});
