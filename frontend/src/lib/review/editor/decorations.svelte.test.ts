import { afterEach, describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import type { ReviewItem } from '../types';
import { fromItems } from './field';
import { reviewExtensions, setDensity, setEmphasis, openPopover, LABELS } from './index';
import { markLabel } from './decorations';

// Tiny SYNTHETIC report: a dictated finding, a green normal, an amber check, an action item with an edit, a
// pre-applied insert, an AI synthesis clause, a recommendation, a removed (red) widget and an option.
const DICTATED = 'Simple cyst in the left kidney.';
const GREEN = 'The liver is normal.';
const AMBER = 'No hydronephrosis.';
const ACTION = 'The spleen measures 9 cm.';
const ADDED = 'No renal calculi.';
const SYNTH = 'Overall appearances are benign.';
const REC = 'Suggest follow-up ultrasound in 6 months.';
const REMOVED = 'The kidneys are normal.';
const OPTION = 'No free fluid.';
const report = `${DICTATED} ${GREEN} ${AMBER} ${ACTION} ${ADDED} ${SYNTH} ${REC}`;

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

function span(text: string, doc = report) {
	const start = doc.indexOf(text);
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
		id: 's1',
		kind: 'ai_generated',
		cls: 'info',
		lane: 'accuracy',
		detectors: ['provenance'],
		anchor: span(SYNTH)
	}),
	item({
		id: 'rec1',
		kind: 'recommendation',
		cls: 'minor',
		label: 'Follow-up recommendation',
		anchor: span(REC),
		edit: { mode: 'remove', find: REC }
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

function mount(opts: Partial<Parameters<typeof reviewExtensions>[0]> = {}, items = ITEMS, doc = report) {
	const onCommand = vi.fn();
	const byId = new Map(items.map((i) => [i.id, i]));
	const state = EditorState.create({
		doc,
		extensions: reviewExtensions({
			onCommand,
			getItem: (id) => byId.get(id),
			initial: fromItems(doc, items).items,
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
const styles: HTMLStyleElement[] = [];
afterEach(() => styles.splice(0).forEach((s) => s.remove()));
function noTransitions() {
	const st = document.createElement('style');
	st.textContent = '.cm-editor * { transition: none !important; }';
	document.head.append(st);
	styles.push(st);
}

const lastRect = (e: Element) => {
	const rs = [...e.getClientRects()];
	return rs[rs.length - 1];
};

const NONE = 'rgba(0, 0, 0, 0)';

describe('review decorations', () => {
	it('renders marks with their class, id and accessible name', () => {
		const { view } = mount();
		const g = markEl(view, 'g1');
		expect(g.classList.contains('rv-normal')).toBe(true);
		expect(g.textContent).toBe(GREEN);
		expect(g.getAttribute('aria-label')).toBe('Normals (AI-generated)');
		expect(markEl(view, 'c1').classList.contains('rv-check')).toBe(true);
		expect(markEl(view, 's1').classList.contains('rv-synth')).toBe(true);
		expect(markEl(view, 'rec1').classList.contains('rv-rec')).toBe(true);
		expect(markEl(view, 'a1').classList.contains('rv-action')).toBe(true);
		expect(markEl(view, 'p1').classList.contains('rv-preapplied')).toBe(true);
	});

	it('Quiet density by default, on the editor element; setDensity changes it', async () => {
		const { view } = mount();
		expect(view.dom.dataset.density).toBe('quiet');
		view.dispatch({ effects: setDensity.of('full') });
		expect(view.dom.dataset.density).toBe('full');
	});

	it('the AI-generated layer is on by default: faint tints by category, no underline; toggled off it is plain text', () => {
		const { view } = mount();
		noTransitions();
		const cs = (id: string) => getComputedStyle(markEl(view, id));
		// g1 "The liver is normal." → normal; c1 "No hydronephrosis." → pertinent negative; s1 → synthesis
		expect(markEl(view, 'g1').classList.contains('rv-form-normal')).toBe(true);
		expect(markEl(view, 'c1').classList.contains('rv-form-negative')).toBe(true);
		expect(markEl(view, 's1').classList.contains('rv-form-synthesis')).toBe(true);
		const tints = new Set<string>();
		for (const id of ['g1', 'c1', 's1']) {
			expect(cs(id).textDecorationLine, id).toBe('none');
			const bg = cs(id).backgroundColor;
			expect(bg, id).not.toBe(NONE);
			const alpha = Number(/rgba\([^)]*,\s*([\d.]+)\)/.exec(bg)?.[1] ?? 1);
			expect(alpha, `${id} ${bg}`).toBeLessThanOrEqual(0.2); // very light
			tints.add(bg);
		}
		expect(tints.size).toBe(3); // green, amber, violet
		view.dispatch({ effects: setEmphasis.of([]) });
		for (const id of ['g1']) {
			expect(cs(id).backgroundColor, id).toBe(NONE);
			expect(cs(id).textDecorationLine, id).toBe('none');
		}
		// amber (negative) and violet (synthesis) ignore the toggle: always shown
		expect(cs('c1').backgroundColor).not.toBe(NONE);
		expect(cs('s1').backgroundColor).not.toBe(NONE);
	});

	it('with the AI-generated toggle off, an amber statement is still tinted and a green normal is not', () => {
		const D = 'No hilar lymphadenopathy. The liver is normal.';
		const at = (t: string) => span(t, D);
		const items = [
			item({
				id: 'am',
				kind: 'assumed_normal',
				cls: 'info',
				lane: 'accuracy',
				anchor: at('No hilar lymphadenopathy.'),
				evidence: { form: 'negative', pointer: 'right hilar nodes 14 mm' }
			}),
			item({ id: 'gr', kind: 'assumed_normal', cls: 'info', anchor: at('The liver is normal.'), evidence: { form: 'normal' } })
		];
		const { view } = mount({ emphasis: [] }, items, D);
		noTransitions();
		expect(view.dom.hasAttribute('data-rv-emph')).toBe(false);
		expect(getComputedStyle(markEl(view, 'am')).backgroundColor).not.toBe(NONE);
		expect(getComputedStyle(markEl(view, 'gr')).backgroundColor).toBe(NONE);
		expect(markEl(view, 'am').getAttribute('aria-label')).toBe(
			'Pertinent negatives · “right hilar nodes 14 mm” (AI-generated)'
		);
	});

	it('a conflict check (cls action) is an action mark: Apply (its Remove) and Dismiss, not the AI layer', async () => {
		const D = 'Simple cyst in the left kidney. The left kidney is normal.';
		const items = [
			item({
				id: 'k1',
				kind: 'check',
				cls: 'action',
				lane: 'accuracy',
				label: 'Conflicts with your dictation',
				anchor: span('The left kidney is normal.', D),
				evidence: { check_reason: 'conflict', source: 'brief', brief_reason: 'brief_kept' },
				edit: { mode: 'remove', find: 'The left kidney is normal.' }
			})
		];
		const { view } = mount({}, items, D);
		const k = markEl(view, 'k1');
		expect(k.classList.contains('rv-action')).toBe(true);
		expect(k.classList.contains('rv-check')).toBe(false);
		expect([...k.classList].some((c) => c.startsWith('rv-form-'))).toBe(false);
		expect(k.getAttribute('aria-label')).toBe(
			'Needs action · Likely conflicts with your dictation; could not be removed automatically. · hover for actions'
		);
		const c = await openOn(view, 'k1');
		expect(actionsOf(c)).toEqual(['apply', 'dismiss', 'reveal']);
	});

	it('tints follow evidence.form when the backend sends it, else the text (No / Nil / Without / Absent → negative)', () => {
		const D = 'Without free fluid. Nil collection. Absent flow voids. The bowel is unremarkable. Likely benign.';
		const at = (t: string) => span(t, D);
		const items = [
			item({ id: 'n1', kind: 'assumed_normal', cls: 'info', anchor: at('Without free fluid.') }),
			item({ id: 'n2', kind: 'assumed_normal', cls: 'info', anchor: at('Nil collection.') }),
			item({ id: 'n3', kind: 'check', cls: 'minor', anchor: at('Absent flow voids.') }),
			// the backend's form wins over the text
			item({
				id: 'n4',
				kind: 'assumed_normal',
				cls: 'info',
				anchor: at('The bowel is unremarkable.'),
				evidence: { form: 'negative' }
			}),
			item({ id: 'n5', kind: 'ai_generated', cls: 'info', lane: 'accuracy', anchor: at('Likely benign.') })
		];
		const { view } = mount({}, items, D);
		const form = (id: string) => [...markEl(view, id).classList].find((c) => c.startsWith('rv-form-'));
		expect(['n1', 'n2', 'n3', 'n4', 'n5'].map(form)).toEqual([
			'rv-form-negative',
			'rv-form-negative',
			'rv-form-negative',
			'rv-form-negative',
			'rv-form-synthesis'
		]);
	});

	it('check (implicated) items carry only their category tint: no underline of their own', () => {
		const { view } = mount();
		noTransitions();
		const c = getComputedStyle(markEl(view, 'c1'));
		const n = getComputedStyle(markEl(view, 'g1'));
		expect(c.textDecorationLine).toBe('none');
		expect(c.borderBottomStyle).toBe(n.borderBottomStyle);
		expect(c.backgroundColor).not.toBe(NONE);
	});

	it('the AI-generated layer has no actions: no inline control on hover, click or caret, no gutter marker', async () => {
		const { view } = mount({ emphasis: ['ai', 'rec'] });
		for (const id of ['g1', 'c1', 's1']) {
			hoverOn(markEl(view, id));
			click(markEl(view, id));
		}
		await pause(300);
		expect(control(view)).toBeNull();
		view.focus();
		view.dispatch({ selection: { anchor: report.indexOf(AMBER) + 2 }, userEvent: 'select' });
		await tick();
		expect(control(view)).toBeNull();
		view.dispatch({ effects: openPopover.of('s1') });
		await tick();
		expect(control(view)).toBeNull();
	});

	it('a recommendation keeps its own dotted underline, whatever the AI-generated toggle', () => {
		const { view } = mount();
		noTransitions();
		const cs = () => getComputedStyle(markEl(view, 'rec1'));
		expect(cs().textDecorationLine).toContain('underline');
		expect(cs().textDecorationStyle).toBe('dotted');
		view.dispatch({ effects: setEmphasis.of([]) });
		expect(cs().textDecorationLine).toContain('underline');
	});

	it('hovering a flagged action item expands ✓ / ✕ / › at the END of the highlight, inside the text flow', async () => {
		const { view, onCommand } = mount();
		const mark = markEl(view, 'a1');
		hoverOn(mark);
		await pause(60);
		expect(control(view)).toBeNull(); // not instant
		await pause(250);
		const c = control(view)!;
		expect(c.getAttribute('data-rv-inline')).toBe('a1');
		expect(view.contentDOM.contains(c)).toBe(true);
		expect(view.dom.querySelector('.cm-tooltip')).toBeNull();
		expect(c.closest('.rv-mark')).toBeNull();
		const end = lastRect(mark);
		const r = c.getBoundingClientRect();
		expect(Math.abs(r.left - end.right)).toBeLessThan(8);
		expect(r.top).toBeLessThan(end.bottom);
		expect(r.bottom).toBeGreaterThan(end.top);
		expect(r.height).toBeLessThanOrEqual(end.height + 1);
		expect(iconsOf(c)).toEqual(['✓', '✕', '›']);
		for (const b of c.querySelectorAll('button')) expect(b.getAttribute('aria-label')).toBeTruthy();
		expect(getComputedStyle(c).animationName).toContain('rv-inline-in');
		expect(getComputedStyle(c).animationDuration).toBe('0.12s');
		click(actionBtn(c, 'dismiss'));
		expect(onCommand).toHaveBeenCalledWith('dismiss', 'a1', undefined);
	});

	it('a recommendation has no inline control (hover, click or caret)', async () => {
		const { view } = mount();
		hoverOn(markEl(view, 'rec1'));
		click(markEl(view, 'rec1'));
		await pause(300);
		expect(control(view)).toBeNull();
		view.focus();
		view.dispatch({ selection: { anchor: report.indexOf(REC) + 2 }, userEvent: 'select' });
		await tick();
		expect(control(view)).toBeNull();
	});

	it('an AI-generated clause overlapping an action item is not drawn: the action item wins', async () => {
		const clause = 'The spleen measures 9 cm.';
		const items = [
			ITEMS.find((i) => i.id === 'a1')!,
			item({ id: 'sx', kind: 'ai_generated', cls: 'info', lane: 'accuracy', anchor: span(clause) })
		];
		const { view } = mount({ emphasis: ['ai', 'rec'] }, items);
		expect(view.dom.querySelector('[data-rv-id="sx"]')).toBeNull();
		expect(actionsOf(await openOn(view, 'a1'))).toEqual(['apply', 'dismiss', 'reveal']);
	});

	it('controls by type: flagged action, pre-applied, removed widget', async () => {
		const { view } = mount();
		const cases: [string, string[], string[]][] = [
			['a1', ['apply', 'dismiss', 'reveal'], ['✓', '✕', '›']],
			['p1', ['undo'], ['↶']],
			['r1', ['restore'], ['↺']]
		];
		for (const [id, actions, icons] of cases) {
			const c = await openOn(view, id);
			expect(actionsOf(c), id).toEqual(actions);
			expect(iconsOf(c), id).toEqual(icons);
		}
	});

	it('control buttons run the commands through the command callback and collapse the control', async () => {
		const { view, onCommand } = mount();
		click(actionBtn(await openOn(view, 'r1'), 'restore'));
		expect(onCommand).toHaveBeenCalledWith('restore', 'r1', undefined);
		click(actionBtn(await openOn(view, 'p1'), 'undo'));
		expect(onCommand).toHaveBeenCalledWith('undo', 'p1', undefined);
		click(actionBtn(await openOn(view, 'a1'), 'apply'));
		expect(onCommand).toHaveBeenCalledWith('apply', 'a1', undefined);
		await tick();
		expect(control(view)).toBeNull();
	});

	it('after an action the range ticks and fades (no toast)', async () => {
		const { view } = mount();
		click(actionBtn(await openOn(view, 'a1'), 'dismiss'));
		await tick();
		expect(view.dom.querySelector('.rv-flash')?.textContent).toBe('9 cm');
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
		c.dispatchEvent(new MouseEvent('mouseleave', { relatedTarget: mark }));
		await pause(400);
		expect(control(view)).not.toBeNull();
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
		const c = await openOn(view, 'p1');
		const keep = actionBtn(c, 'undo');
		keep.focus();
		keep.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
		await tick();
		expect(control(view)).toBeNull();
	});

	it('keyboard: the caret moving into an action item opens its control; Tab focuses its buttons; arrows move', async () => {
		const { view } = mount();
		view.focus();
		view.dispatch({ selection: { anchor: report.indexOf('9 cm') + 1 }, userEvent: 'select' });
		await tick();
		expect(control(view)?.getAttribute('data-rv-inline')).toBe('a1');
		view.contentDOM.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
		);
		expect(document.activeElement?.getAttribute('data-rv-action')).toBe('apply');
		document.activeElement!.dispatchEvent(
			new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
		);
		expect(document.activeElement?.getAttribute('data-rv-action')).toBe('dismiss');
		await pause(300);
		expect(control(view)).not.toBeNull();
		view.focus();
		view.dispatch({ selection: { anchor: 0 }, userEvent: 'select' });
		await tick();
		expect(control(view)).toBeNull();
	});

	it('› on a flagged issue asks the host to show its rail card; pre-applied rows have no link', async () => {
		const onReveal = vi.fn();
		const { view, onCommand } = mount({ onReveal });
		click(actionBtn(await openOn(view, 'a1'), 'reveal'));
		expect(onReveal).toHaveBeenCalledWith('a1');
		expect(onCommand).not.toHaveBeenCalled();
		expect(actionsOf(await openOn(view, 'p1'))).not.toContain('reveal');
	});

	it('hovering an apply ✓ previews the fix inline: old struck, new as ghost text; leaving clears it', async () => {
		const { view } = mount();
		const apply = actionBtn(await openOn(view, 'a1'), 'apply');
		apply.dispatchEvent(new MouseEvent('mouseenter'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del')?.textContent).toBe('9 cm');
		expect(view.dom.querySelector('.rv-preview-ins')?.textContent).toBe('11 cm');
		expect(view.state.doc.toString()).toBe(report);
		apply.dispatchEvent(new MouseEvent('mouseleave'));
		await tick();
		expect(view.dom.querySelector('.rv-preview-del, .rv-preview-ins')).toBeNull();
	});

	it('removed widgets show their text but are not in the document; options are never ghost text in the report', () => {
		const { view } = mount();
		const r = view.dom.querySelector<HTMLElement>('[data-rv-widget="r1"]')!;
		expect(r.textContent).toContain(REMOVED);
		expect(r.getAttribute('aria-label')).toContain(LABELS.removed);
		expect(view.state.doc.toString()).not.toContain(REMOVED);
		expect(view.dom.querySelector('[data-rv-widget="o1"]')).toBeNull();
		expect(view.dom.querySelector('.cm-line')!.textContent).not.toContain(OPTION);
	});

	it('flagged items keep one consistent underline: soft dotted, no fill, discreet at rest (lit is stronger)', () => {
		const { view } = mount({ emphasis: ['ai'] });
		noTransitions();
		const ids = ['rec1', 'p1', 'a1'];
		const first = getComputedStyle(markEl(view, 'rec1'));
		for (const id of ids) {
			const cs = getComputedStyle(markEl(view, id));
			expect(cs.backgroundColor, id).toBe(NONE);
			expect(cs.textDecorationStyle, id).toBe('dotted');
			expect(cs.textDecorationThickness, id).toBe(first.textDecorationThickness);
		}
		for (const id of ['p1', 'a1']) {
			const rest = getComputedStyle(markEl(view, id)).textDecorationColor;
			markEl(view, id).classList.add('rv-active');
			expect(getComputedStyle(markEl(view, id)).textDecorationColor, id).not.toBe(rest);
			markEl(view, id).classList.remove('rv-active');
		}
	});

	it('the legend toggle sets data-rv-emph ("ai" by default); empty clears it', () => {
		const { view } = mount();
		expect(view.dom.getAttribute('data-rv-emph')).toBe('ai');
		view.dispatch({ effects: setEmphasis.of([]) });
		expect(view.dom.hasAttribute('data-rv-emph')).toBe(false);
	});

	it('draws gutter markers only for actionable items (not the AI-generated layer)', () => {
		const { view } = mount();
		const markers = [...view.dom.querySelectorAll<HTMLElement>('.rv-gutter-marker')];
		expect(markers.length).toBe(1); // one line: the highest cls wins
		expect(markers[0].classList.contains('rv-gutter-action')).toBe(true);
		const ai = [item({ id: 'x', kind: 'check', cls: 'minor', anchor: span(AMBER) })];
		const { view: v2 } = mount({}, ai);
		expect(v2.dom.querySelectorAll('.rv-gutter-marker').length).toBe(0);
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

describe('suggestions subsection', () => {
	// SYNTHETIC two-section report.
	const DOC = `FINDINGS:\nThe pancreas has a mass. No ascites.\n\nIMPRESSION:\nPancreatic mass.`;
	const sugg = (over: Partial<ReviewItem> & Pick<ReviewItem, 'id'>) =>
		item({
			kind: 'option',
			cls: 'minor',
			lane: 'additions',
			section: 'FINDINGS',
			edit: { mode: 'insert', after: 'The pancreas has a mass.', replace: 'No portal vein thrombosis.' },
			...over
		});

	it('renders a checkbox list directly under the section body, not in the document', async () => {
		const { view } = mount({}, [sugg({ id: 'o1' })], DOC);
		const box = view.dom.querySelector<HTMLElement>('[data-rv-suggestions]')!;
		expect(box).not.toBeNull();
		expect(box.textContent).toContain('Suggestions');
		const cb = box.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
		expect(cb.checked).toBe(false);
		expect(box.textContent).toContain('No portal vein thrombosis.');
		expect(view.state.doc.toString()).toBe(DOC); // copy / export unaffected
		// between the FINDINGS body and the IMPRESSION heading
		const lines = [...view.contentDOM.querySelectorAll<HTMLElement>('.cm-line')];
		const body = lines.find((l) => l.textContent?.includes('No ascites.'))!;
		const impression = lines.find((l) => l.textContent === 'IMPRESSION:')!;
		const b = box.getBoundingClientRect();
		expect(b.top).toBeGreaterThanOrEqual(body.getBoundingClientRect().bottom - 1);
		expect(b.bottom).toBeLessThanOrEqual(impression.getBoundingClientRect().top + 1);
		expect(view.dom.querySelector('.cm-line')!.parentElement!.textContent).not.toContain('◌');
	});

	it('ticking applies the insert (apply); unticking an applied one undoes it (undo)', async () => {
		const applied = DOC.replace('The pancreas has a mass.', 'The pancreas has a mass. No splenic vein thrombosis.');
		const items = [
			sugg({ id: 'o1' }),
			sugg({
				id: 'o2',
				status: 'applied',
				edit: { mode: 'insert', after: 'The pancreas has a mass.', replace: 'No splenic vein thrombosis.' }
			})
		];
		const { view, onCommand } = mount({}, items, applied);
		const boxes = view.dom.querySelectorAll<HTMLElement>('[data-rv-suggestions]');
		expect(boxes.length).toBe(1);
		const cb = (id: string) =>
			view.dom.querySelector<HTMLInputElement>(`[data-rv-suggestion="${id}"] input`)!;
		expect(cb('o1').checked).toBe(false);
		expect(cb('o2').checked).toBe(true);
		cb('o1').click();
		expect(onCommand).toHaveBeenCalledWith('apply', 'o1');
		cb('o2').click();
		expect(onCommand).toHaveBeenCalledWith('undo', 'o2');
	});

	it('hides suggestions that are stale, answered, suppressed or have no placeable edit', () => {
		const items = [
			sugg({ id: 'stale', status: 'stale' }),
			sugg({ id: 'gone', status: 'dismissed' }),
			sugg({ id: 'quiet', cls: 'suppress' }),
			sugg({ id: 'noedit', edit: null }),
			sugg({ id: 'nowhere', edit: { mode: 'insert', after: 'Not in this report.', replace: 'Text.' } })
		];
		const { view } = mount({}, items, DOC);
		expect(view.dom.querySelector('[data-rv-suggestions]')).toBeNull();
	});

	it('recommendations join the impression block ticked ("Recommendations"): untick removes, re-tick restores', async () => {
		const REC2 = 'Suggest surgical review.';
		const doc = DOC.replace('Pancreatic mass.', `Pancreatic mass. ${REC2}`);
		const rec = item({
			id: 'r1',
			kind: 'recommendation',
			cls: 'minor',
			lane: 'additions',
			section: 'IMPRESSION',
			anchor: span(REC2, doc),
			edit: { mode: 'remove', find: REC2, section: 'IMPRESSION' }
		});
		const sg = sugg({ id: 'o1', section: 'IMPRESSION', edit: { mode: 'insert', after: 'Pancreatic mass.', replace: 'No metastases.' } });
		const { view, onCommand } = mount({}, [rec, sg], doc);
		const box = view.dom.querySelector<HTMLElement>('[data-rv-suggestions]')!;
		expect(box.querySelector('.rv-suggestions-title')!.textContent).toBe('Recommendations');
		const rows = [...box.querySelectorAll<HTMLElement>('[data-rv-suggestion]')];
		expect(rows.map((r) => r.getAttribute('data-rv-kind'))).toEqual(['recommendation', 'suggestion']);
		const cb = rows[0].querySelector('input')!;
		expect(cb.checked).toBe(true);
		expect(rows[0].textContent).toContain(REC2);
		cb.click();
		expect(onCommand).toHaveBeenCalledWith('remove', 'r1');
		// once removed (applied) it is unticked; ticking restores it
		const removed = { ...rec, status: 'applied' as const };
		const after = doc.replace(` ${REC2}`, '');
		const { view: v2, onCommand: cmd2 } = mount({}, [removed], after);
		const cb2 = v2.dom.querySelector<HTMLInputElement>('[data-rv-suggestion="r1"] input')!;
		expect(cb2.checked).toBe(false);
		cb2.click();
		expect(cmd2).toHaveBeenCalledWith('undo', 'r1');
	});

	it('a recommendation without a placeable edit is ticked and disabled ("Edit in text")', () => {
		const REC2 = 'Suggest surgical review.';
		const doc = DOC.replace('Pancreatic mass.', `Pancreatic mass. ${REC2}`);
		const rec = item({ id: 'r1', kind: 'recommendation', cls: 'minor', lane: 'additions', section: 'IMPRESSION', anchor: span(REC2, doc), edit: null });
		const { view } = mount({}, [rec], doc);
		const row = view.dom.querySelector<HTMLElement>('[data-rv-suggestion="r1"]')!;
		expect(row.querySelector('input')!.checked).toBe(true);
		expect(row.querySelector('input')!.disabled).toBe(true);
		expect(row.title).toBe('Edit in text');
		expect(view.dom.querySelector('.rv-suggestions-title')!.textContent).toBe('Recommendations');
	});

	it('an additions insert is a suggestion too; each section gets its own list', () => {
		const items = [
			sugg({ id: 'o1' }),
			item({
				id: 'g1',
				kind: 'classification',
				cls: 'minor',
				lane: 'additions',
				section: 'IMPRESSION',
				edit: { mode: 'insert', after: 'Pancreatic mass.', replace: 'Borderline resectable.' }
			})
		];
		const { view } = mount({}, items, DOC);
		const boxes = [...view.dom.querySelectorAll<HTMLElement>('[data-rv-suggestions]')];
		expect(boxes.length).toBe(2);
		expect(boxes[1].textContent).toContain('Borderline resectable.');
	});
});

describe('impression checklist block', () => {
	// SYNTHETIC report with a sign-off after the impression.
	const REC2 = 'Suggest surgical review.';
	const DOC = `FINDINGS:\nThe pancreas has a mass.\n\nIMPRESSION:\nPancreatic mass. ${REC2}\n\nDr A Person\nConsultant Radiologist\nGMC 0000000 FRCR`;
	const rec = item({
		id: 'r1',
		kind: 'recommendation',
		cls: 'minor',
		lane: 'additions',
		section: 'IMPRESSION',
		anchor: span(REC2, DOC),
		edit: { mode: 'remove', find: REC2, section: 'IMPRESSION' }
	});
	const findingSugg = item({
		id: 'o1',
		kind: 'option',
		cls: 'minor',
		lane: 'additions',
		section: 'FINDINGS',
		edit: { mode: 'insert', after: 'The pancreas has a mass.', replace: 'No ascites.' }
	});
	const lineOf = (view: EditorView, text: string) =>
		[...view.contentDOM.querySelectorAll<HTMLElement>('.cm-line')].find((l) => l.textContent === text)!;

	it('is headed "Recommendations" (other sections keep "Suggestions")', () => {
		const { view } = mount({}, [rec, findingSugg], DOC);
		const titles = [...view.dom.querySelectorAll('.rv-suggestions-title')].map((t) => t.textContent);
		expect(titles).toEqual(['Suggestions', 'Recommendations']);
		expect(view.dom.querySelector('[data-rv-impression]')!.getAttribute('aria-label')).toBe('Recommendations');
	});

	it('sits directly after the impression body, before the signature, name, GMC and FRCR lines', () => {
		const { view } = mount({}, [rec], DOC);
		const box = view.dom.querySelector<HTMLElement>('[data-rv-impression]')!.getBoundingClientRect();
		const body = lineOf(view, `Pancreatic mass. ${REC2}`).getBoundingClientRect();
		const sig = lineOf(view, 'Dr A Person').getBoundingClientRect();
		expect(box.top).toBeGreaterThanOrEqual(body.bottom - 1);
		expect(box.bottom).toBeLessThanOrEqual(sig.top + 1);
		for (const t of ['Consultant Radiologist', 'GMC 0000000 FRCR'])
			expect(lineOf(view, t).getBoundingClientRect().top).toBeGreaterThan(box.bottom);
		expect(view.state.doc.toString()).toBe(DOC); // never document text
	});

	it('a sign-off directly under the impression (no blank line) still stays below the block', () => {
		const doc = DOC.replace(`${REC2}\n\nDr A Person`, `${REC2}\nDr A Person`);
		const r = { ...rec, anchor: span(REC2, doc) };
		const { view } = mount({}, [r], doc);
		const box = view.dom.querySelector<HTMLElement>('[data-rv-impression]')!.getBoundingClientRect();
		expect(box.bottom).toBeLessThanOrEqual(lineOf(view, 'Dr A Person').getBoundingClientRect().top + 1);
	});

	it('has a blank line’s gap above it', () => {
		const { view } = mount({}, [rec], DOC);
		const block = view.dom.querySelector<HTMLElement>('.rv-suggestions-block')!;
		const box = block.querySelector<HTMLElement>('[data-rv-suggestions]')!.getBoundingClientRect();
		const body = lineOf(view, `Pancreatic mass. ${REC2}`).getBoundingClientRect();
		expect(box.top - body.bottom).toBeGreaterThanOrEqual(body.height * 0.8);
	});

	it('checkboxes in the app theme: a rounded custom box in the border colour; purple-600 with a white tick when checked; focus ring', async () => {
		const unticked = { ...rec, status: 'applied' as const };
		const { view } = mount({}, [unticked, findingSugg], DOC.replace(` ${REC2}`, ''));
		noTransitions();
		const [off] = [...view.dom.querySelectorAll<HTMLInputElement>('input.rv-check-box')];
		const cs = getComputedStyle(off);
		expect(cs.appearance).toBe('none');
		expect(Number.parseFloat(cs.borderTopLeftRadius)).toBeGreaterThan(0);
		expect(cs.borderTopColor).toBe('rgb(214, 216, 219)'); // --rv-border (light)
		expect(cs.backgroundImage).toBe('none');
		const { view: v2 } = mount({}, [rec], DOC);
		const on = v2.dom.querySelector<HTMLInputElement>('input.rv-check-box')!;
		expect(on.checked).toBe(true);
		const con = getComputedStyle(on);
		expect(con.backgroundColor).toBe('rgb(147, 51, 234)'); // purple-600
		expect(con.backgroundImage).toContain('svg');
		expect(con.backgroundImage).toContain('white');
		// hover and keyboard focus states are styled (the theme's own rules)
		const rules = [...document.styleSheets].flatMap((sh) => [...sh.cssRules].map((r) => r.cssText));
		expect(rules.some((r) => /rv-check-box:hover/.test(r) && /border-color/.test(r))).toBe(true);
		expect(rules.some((r) => /rv-check-box:focus-visible/.test(r) && /box-shadow/.test(r))).toBe(true);
	});
});

describe('inline control in wrapped prose', () => {
	const FILL = 'The structure is unremarkable and the adjacent tissues are preserved without change. ';
	const DOC = `FINDINGS:\n${FILL}Target mark sits here. ${FILL.repeat(3)}`;

	it('keeps the line height (compact) and collapses back to the same layout', async () => {
		const text = 'Target mark';
		const start = DOC.indexOf(text);
		const it_ = item({ id: 'k', kind: 'measurement', cls: 'action', anchor: { start, end: start + text.length, text }, edit: { mode: 'replace', find: text, replace: 'Target' } });
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
		const lineH = () =>
			[...view.contentDOM.querySelectorAll<HTMLElement>('.cm-line')].map((l) => l.getBoundingClientRect().height);
		const before = lineH();
		const c = await openOn(view, 'k');
		await pause(200);
		expect(Math.abs(c.getBoundingClientRect().left - lastRect(markEl(view, 'k')).right)).toBeLessThan(8);
		expect(c.getBoundingClientRect().width).toBeLessThan(80); // three icons at most
		const lineHeight = Number.parseFloat(getComputedStyle(view.contentDOM.querySelector('.cm-line')!).lineHeight);
		expect(c.getBoundingClientRect().height).toBeLessThanOrEqual(lineHeight);
		view.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
		await tick();
		expect(control(view)).toBeNull();
		expect(lineH()).toEqual(before);
	});
});

describe('amber AI-layer label', () => {
	it('names the dictated finding an amber statement bears on', () => {
		const m = {
			id: 'x', kind: 'assumed_normal', cls: 'info', lane: 'accuracy', mark: 'rv-normal',
			form: 'negative', pointer: 'right hilar nodes 14 mm', from: 0, to: 5, text: 'No X.'
		} as const;
		expect(markLabel(m as never)).toBe('Pertinent negatives · “right hilar nodes 14 mm” (AI-generated)');
	});
	it('leaves a green normal unchanged', () => {
		const m = { id: 'y', kind: 'assumed_normal', cls: 'info', lane: 'accuracy', mark: 'rv-normal',
			form: 'normal', from: 0, to: 5, text: 'Liver.' } as const;
		expect(markLabel(m as never)).toBe('Normals (AI-generated)');
	});
});
