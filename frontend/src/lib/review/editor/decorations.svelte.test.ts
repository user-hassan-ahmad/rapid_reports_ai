import { afterEach, describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import type { ReviewItem } from '../types';
import { fromItems } from './field';
import { reviewExtensions, setDensity, setEmphasis, openPopover, LABELS } from './index';

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

function control(view: EditorView): HTMLElement | null {
	return view.dom.querySelector<HTMLElement>('.rv-inline');
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

function hoverOn(el: Element) {
	el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
}

function actionsOf(c: Element): string[] {
	return [...c.querySelectorAll('button')].map((b) => b.getAttribute('data-rv-action') ?? '');
}

function iconsOf(c: Element): string[] {
	return [...c.querySelectorAll('button')].map((b) => b.textContent ?? '');
}

function actionBtn(c: Element, action: string): HTMLButtonElement {
	const b = c.querySelector<HTMLButtonElement>(`button[data-rv-action="${action}"]`);
	if (!b) throw new Error(`no ${action} in control ${c.textContent}`);
	return b;
}

function targetEl(view: EditorView, id: string): HTMLElement {
	return (
		view.dom.querySelector<HTMLElement>(`[data-rv-id="${id}"]`) ??
		view.dom.querySelector<HTMLElement>(`[data-rv-widget="${id}"]`)!
	);
}

/** Click / tap opens the control at once. */
async function openOn(view: EditorView, id: string): Promise<HTMLElement> {
	click(targetEl(view, id));
	await tick();
	const c = control(view);
	if (!c || c.getAttribute('data-rv-inline') !== id) throw new Error('control did not open');
	return c;
}

/** Colour reads must not land mid-transition. */
function noTransitions() {
	const st = document.createElement('style');
	st.textContent = '.cm-editor * { transition: none !important; }';
	document.head.append(st);
	styles.push(st);
}
const styles: HTMLStyleElement[] = [];
afterEach(() => styles.splice(0).forEach((s) => s.remove()));

const lastRect = (e: Element) => {
	const rs = [...e.getClientRects()];
	return rs[rs.length - 1];
};

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

	it('hovering a mark expands an inline control at the END of that mark, inside the text flow (no floating tooltip)', async () => {
		const { view } = mount();
		const mark = markEl(view, 'c1');
		hoverOn(mark);
		await pause(60);
		expect(control(view)).toBeNull(); // not instant
		await pause(250);
		const c = control(view)!;
		expect(c).not.toBeNull();
		expect(c.getAttribute('data-rv-inline')).toBe('c1');
		// in the text flow: inside the content, never a tooltip
		expect(view.contentDOM.contains(c)).toBe(true);
		expect(view.dom.querySelector('.cm-tooltip')).toBeNull();
		expect(c.closest('.rv-mark')).toBeNull(); // after the highlight, not part of it
		// right at the mark's end, on its line
		const end = lastRect(mark);
		const r = c.getBoundingClientRect();
		expect(Math.abs(r.left - end.right)).toBeLessThan(8);
		expect(r.top).toBeLessThan(end.bottom);
		expect(r.bottom).toBeGreaterThan(end.top);
		// simple icons: ✓ keep, ✕ remove; no "?" and no rail link on a check
		expect(actionsOf(c)).toEqual(['keep', 'remove']);
		expect(iconsOf(c)).toEqual(['✓', '✕']);
		expect(c.textContent).not.toContain('?');
		for (const b of c.querySelectorAll('button')) {
			expect(b.getAttribute('aria-label')).toBeTruthy();
			expect(b.title).toBeTruthy();
		}
		expect(c.getAttribute('aria-label')).toBeTruthy();
		// width / opacity animate in (~120 ms)
		expect(getComputedStyle(c).animationName).toContain('rv-inline-in');
		expect(getComputedStyle(c).animationDuration).toBe('0.12s');
		// compact: no taller than the line
		expect(r.height).toBeLessThanOrEqual(end.height + 1);
	});

	it('controls by type: check, normal, action, pre-applied, removed and option widgets', async () => {
		const { view } = mount();
		const cases: [string, string[], string[]][] = [
			['c1', ['keep', 'remove'], ['✓', '✕']],
			['g1', ['keep', 'remove'], ['✓', '✕']],
			['a1', ['apply', 'dismiss', 'reveal'], ['✓', '✕', '›']],
			['p1', ['undo'], ['↶']],
			['r1', ['restore'], ['↺']],
			['o1', ['apply', 'dismiss'], ['✓', '✕']]
		];
		for (const [id, actions, icons] of cases) {
			const c = await openOn(view, id);
			expect(actionsOf(c), id).toEqual(actions);
			expect(iconsOf(c), id).toEqual(icons);
		}
	});

	it('a widget’s control sits right after the widget', async () => {
		const { view } = mount();
		const w = view.dom.querySelector<HTMLElement>('[data-rv-widget="o1"]')!;
		const c = await openOn(view, 'o1');
		expect(Math.abs(c.getBoundingClientRect().left - lastRect(w).right)).toBeLessThan(8);
	});

	it('control buttons run the commands through the command callback and collapse the control', async () => {
		const { view, onCommand } = mount();
		click(actionBtn(await openOn(view, 'c1'), 'keep'));
		expect(onCommand).toHaveBeenCalledWith('keep', 'c1', undefined);
		click(actionBtn(await openOn(view, 'g1'), 'remove'));
		expect(onCommand).toHaveBeenCalledWith('remove', 'g1', undefined);
		click(actionBtn(await openOn(view, 'r1'), 'restore'));
		expect(onCommand).toHaveBeenCalledWith('restore', 'r1', undefined);
		click(actionBtn(await openOn(view, 'o1'), 'apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'o1', undefined);
		click(actionBtn(await openOn(view, 'o1'), 'dismiss'));
		expect(onCommand).toHaveBeenCalledWith('dismiss', 'o1', undefined);
		click(actionBtn(await openOn(view, 'p1'), 'undo'));
		expect(onCommand).toHaveBeenCalledWith('undo', 'p1', undefined);
		click(actionBtn(await openOn(view, 'a1'), 'apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1', undefined);
		await tick();
		expect(control(view)).toBeNull();
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

	it('stays open while the pointer is on the mark or the control; collapses when it leaves both', async () => {
		const { view } = mount();
		const mark = markEl(view, 'a1');
		const c = await openOn(view, 'a1');
		mark.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: c }));
		c.dispatchEvent(new MouseEvent('mouseenter'));
		await pause(400);
		expect(control(view)).not.toBeNull();
		// back onto its own mark: still open
		c.dispatchEvent(new MouseEvent('mouseleave', { relatedTarget: mark }));
		await pause(400);
		expect(control(view)).not.toBeNull();
		// off both
		mark.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }));
		await pause(400);
		expect(control(view)).toBeNull();
	});

	it('Escape collapses the control, from the editor or from one of its buttons', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
		);
		await tick();
		expect(control(view)).toBeNull();
		const c = await openOn(view, 'c1');
		const keep = actionBtn(c, 'keep');
		keep.focus();
		keep.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
		await tick();
		expect(control(view)).toBeNull();
	});

	it('keyboard: the caret moving into a mark opens its control; Tab focuses its buttons; arrows move between them', async () => {
		const { view } = mount();
		const at = report.indexOf(AMBER) + 2;
		view.focus();
		view.dispatch({ selection: { anchor: at }, userEvent: 'select' });
		await tick();
		expect(control(view)?.getAttribute('data-rv-inline')).toBe('c1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
		);
		expect(document.activeElement?.getAttribute('data-rv-action')).toBe('keep');
		document.activeElement!.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
		);
		expect(document.activeElement?.getAttribute('data-rv-action')).toBe('remove');
		await pause(300);
		expect(control(view)).not.toBeNull(); // focus on the control keeps it open
		view.focus();
		view.dispatch({ selection: { anchor: 0 }, userEvent: 'select' });
		await tick();
		expect(control(view)).toBeNull();
	});

	it('› on a flagged issue asks the host to show its rail card; checks and normals have no link', async () => {
		const onReveal = vi.fn();
		const { view, onCommand } = mount({ onReveal });
		click(actionBtn(await openOn(view, 'a1'), 'reveal'));
		expect(onReveal).toHaveBeenCalledWith('a1');
		expect(onCommand).not.toHaveBeenCalled();
		for (const id of ['c1', 'g1']) expect(actionsOf(await openOn(view, id))).not.toContain('reveal');
	});

	it('hovering an apply ✓ previews the fix inline: old struck, new as ghost text; leaving clears it', async () => {
		const { view } = mount();
		const c = await openOn(view, 'a1');
		const apply = actionBtn(c, 'apply');
		apply.dispatchEvent(new MouseEvent('mouseenter'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del')?.textContent).toBe('9 cm');
		expect(view.dom.querySelector('.rv-preview-ins')?.textContent).toBe('11 cm');
		expect(view.state.doc.toString()).toBe(report); // a preview, not an edit
		apply.dispatchEvent(new MouseEvent('mouseleave'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del, .rv-preview-ins')).toBeNull();
	});

	it('the control never enters the document text', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		expect(view.state.doc.toString()).toBe(report);
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
		expect(r.querySelector('button')).toBeNull(); // actions live on the inline control
	});

	it('one consistent underline for every AI highlight: soft dotted, no fill, discreet at rest', () => {
		const { view } = mount();
		noTransitions();
		const styles = ['g1', 'p1', 'c1', 'a1'].map((id) => getComputedStyle(markEl(view, id)));
		for (const [i, cs] of styles.entries()) {
			expect(cs.backgroundColor, String(i)).toBe('rgba(0, 0, 0, 0)');
			expect(cs.textDecorationLine).toContain('underline');
			expect(cs.textDecorationStyle).toBe('dotted');
			expect(cs.textDecorationThickness).toBe(styles[0].textDecorationThickness);
		}
		// no dashed (or solid / double) variant anywhere
		expect(new Set(styles.map((s) => s.textDecorationStyle))).toEqual(new Set(['dotted']));
		// discreet: at rest each line is softer than when lit
		for (const id of ['g1', 'c1', 'a1']) {
			const rest = getComputedStyle(markEl(view, id)).textDecorationColor;
			markEl(view, id).classList.add('rv-active');
			expect(getComputedStyle(markEl(view, id)).textDecorationColor, id).not.toBe(rest);
			markEl(view, id).classList.remove('rv-active');
		}
		// amber / red a little stronger than green at rest
		const alpha = (id: string) => {
			const c = getComputedStyle(markEl(view, id)).textDecorationColor;
			const m = /\/\s*([\d.]+)\)$/.exec(c) ?? /rgba\([^)]*,\s*([\d.]+)\)$/.exec(c);
			return m ? Number(m[1]) : 1;
		};
		expect(alpha('c1')).toBeGreaterThan(alpha('g1'));
		expect(alpha('a1')).toBeGreaterThan(alpha('g1'));
		expect(alpha('a1')).toBeLessThan(1);
	});

	it('the open control lights its mark (full colour + tint)', async () => {
		const { view } = mount();
		await openOn(view, 'a1');
		const lit = view.dom.querySelector<HTMLElement>('.rv-active')!;
		expect(lit.textContent).toBe('9 cm');
		const bg = getComputedStyle(lit.querySelector('.rv-action') ?? lit).backgroundColor;
		expect(bg).not.toBe('rgba(0, 0, 0, 0)');
	});

	it('legend filters: setEmphasis brings the chosen class forward; others stay discreet; reset clears it', () => {
		const { view } = mount();
		noTransitions();
		const bg = (id: string) => getComputedStyle(markEl(view, id)).backgroundColor;
		const line = (id: string) => getComputedStyle(markEl(view, id)).textDecorationColor;
		const rest = { c1: line('c1'), g1: line('g1') };
		view.dispatch({ effects: setEmphasis.of(['check']) });
		expect(view.dom.getAttribute('data-rv-emph')).toBe('check');
		expect(bg('c1')).not.toBe('rgba(0, 0, 0, 0)');
		expect(line('c1')).not.toBe(rest.c1);
		expect(bg('g1')).toBe('rgba(0, 0, 0, 0)');
		expect(line('g1')).toBe(rest.g1);
		// several at once
		view.dispatch({ effects: setEmphasis.of(['check', 'normal']) });
		expect(bg('g1')).not.toBe('rgba(0, 0, 0, 0)');
		const o = view.dom.querySelector<HTMLElement>('[data-rv-widget="o1"]')!;
		expect(getComputedStyle(o).backgroundColor).toBe('rgba(0, 0, 0, 0)');
		view.dispatch({ effects: setEmphasis.of(['option']) });
		expect(getComputedStyle(o).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
		// "dictated" fades the AI highlights so the dictation stands out
		view.dispatch({ effects: setEmphasis.of(['dictated']) });
		expect(Number(getComputedStyle(markEl(view, 'c1')).opacity)).toBeLessThan(1);
		view.dispatch({ effects: setEmphasis.of([]) });
		expect(view.dom.hasAttribute('data-rv-emph')).toBe(false);
		expect(bg('c1')).toBe('rgba(0, 0, 0, 0)');
		expect(line('c1')).toBe(rest.c1);
		// the host can mount with filters on
		const { view: v2 } = mount({ emphasis: ['check'] });
		expect(v2.dom.getAttribute('data-rv-emph')).toBe('check');
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
		expect(control(view)).toBeNull();
	});
});

describe('inline control in wrapped prose', () => {
	// SYNTHETIC prose in a narrow wrapped editor.
	const FILL = 'The structure is unremarkable and the adjacent tissues are preserved without change. ';
	const DOC = `FINDINGS:\n${FILL}Target mark sits here. ${FILL.repeat(3)}`;

	function mountWrapped() {
		const text = 'Target mark';
		const start = DOC.indexOf(text);
		const it_ = item({ id: 'k', kind: 'check', cls: 'minor', anchor: { start, end: start + text.length, text }, evidence: { check_reason: 'uncertain' } });
		const state = EditorState.create({
			doc: DOC,
			extensions: [
				EditorView.lineWrapping,
				EditorView.theme({ '.cm-content': { fontSize: '16px', lineHeight: '1.6', fontFamily: 'sans-serif' } }),
				reviewExtensions({ onCommand: vi.fn(), getItem: () => it_, initial: fromItems(DOC, [it_]).items })
			]
		});
		const parent = document.createElement('div');
		parent.style.cssText = 'position:absolute;left:20px;top:200px;width:440px';
		document.body.append(parent);
		const view = new EditorView({ state, parent });
		views.push(view);
		return view;
	}

	it('keeps the line height (compact) and collapses back to the same layout', async () => {
		const view = mountWrapped();
		const lineH = () => [...view.contentDOM.querySelectorAll<HTMLElement>('.cm-line')].map((l) => l.getBoundingClientRect().height);
		const before = lineH();
		const c = await openOn(view, 'k');
		await pause(200); // past the width / opacity animation
		const mark = markEl(view, 'k');
		const end = lastRect(mark);
		expect(Math.abs(c.getBoundingClientRect().left - end.right)).toBeLessThan(8);
		expect(c.getBoundingClientRect().width).toBeLessThan(60);
		// the control may push the rest of the line on, but never makes a line taller
		const lineHeight = Number.parseFloat(getComputedStyle(view.contentDOM.querySelector('.cm-line')!).lineHeight);
		expect(c.getBoundingClientRect().height).toBeLessThanOrEqual(lineHeight);
		view.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
		await tick();
		expect(control(view)).toBeNull();
		expect(lineH()).toEqual(before);
	});
});
