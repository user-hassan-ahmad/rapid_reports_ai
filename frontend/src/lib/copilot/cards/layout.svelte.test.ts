// Task 6: layout in a narrow rail. Real layout is measured with getBoundingClientRect at a fixed 280 px container.
// SYNTHETIC fixtures.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import PackCard from './PackCard.svelte';
import ValueRow from './ValueRow.svelte';
import CopilotRail from './CopilotRail.svelte';
import './cards.css';
import '$lib/rail/rail.css';
import { assumption, card, preview, reference, result } from './fixtures';
import type { ValueRow as Row } from './format';

const LONG = 'Consider 3-month CT, PET-CT, or biopsy depending on the size and the risk';
const host = (w = 280) => {
	const h = document.createElement('div');
	h.className = 'rv-rail cp-cards';
	h.dataset.theme = 'dark';
	h.style.cssText = `width:${w}px;min-width:${w}px;max-width:${w}px;height:auto;max-height:none;overflow:visible`;
	document.body.appendChild(h);
	return h;
};
const rect = (e: Element) => e.getBoundingClientRect();
const hit = (a: DOMRect, b: DOMRect) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;

function renderCard(open: boolean) {
	const c = card({ name: 'Fleischner Society 2017' });
	const h = host();
	render(PackCard, {
		target: h,
		props: {
			card: c,
			view: { open, loading: false, error: null, result: result(c, preview({ state: 'check_first' })) },
			assumptions: ['Prior growth: No', 'Smoking: No'],
			action: LONG,
			category: 'workup',
			onOpen: vi.fn(),
			onClose: vi.fn(),
			onRetry: vi.fn()
		}
	});
	return h;
}

describe('card head at 280px', () => {
	for (const open of [false, true]) {
		it(`pills stay inside the card at 280px (${open ? 'open' : 'collapsed'})`, async () => {
			const h = renderCard(open);
			await expect.element(page.getByText('Fleischner Society 2017')).toBeInTheDocument();
			const cardEl = h.querySelector('.gl-card')!;
			const pills = [...h.querySelectorAll('.cp-head-marks > *')];
			expect(pills.length).toBeGreaterThanOrEqual(2);
			for (const p of pills) expect(rect(p).right).toBeLessThanOrEqual(rect(cardEl).right);
			for (let i = 0; i < pills.length; i++)
				for (let j = i + 1; j < pills.length; j++) expect(hit(rect(pills[i]), rect(pills[j]))).toBe(false);
			const name = h.querySelector('.gl-title')!;
			for (const p of pills) expect(hit(rect(name), rect(p))).toBe(false);
		});
	}

	it('a shortened verdict keeps its full text', async () => {
		const h = renderCard(false);
		await expect.element(page.getByText('Fleischner Society 2017')).toBeInTheDocument();
		const pill = h.querySelector('.cp-pill') as HTMLElement;
		const t = pill.querySelector('.cp-pill-text') as HTMLElement;
		expect(t.scrollWidth).toBeGreaterThan(t.clientWidth); // cut off at 280 px
		pill.dispatchEvent(new PointerEvent('pointerenter'));
		await expect.poll(() => pill.getAttribute('title')).toBe(LONG);
	});
});

describe('value row at 280px', () => {
	it('value tags wrap under the value', async () => {
		const h = host();
		const row: Row = {
			input: 'x',
			label: 'A rather long value label that wraps',
			value: '7 mm',
			quote: '',
			byExam: false,
			state: 'assumed',
			decisive: true,
			why: []
		} as Row;
		render(ValueRow, { target: h, props: { row, uid: 't', onEdit: vi.fn() } });
		await expect.element(page.getByText('7 mm')).toBeInTheDocument();
		const li = h.querySelector('li.cp-val')!;
		const tags = [...li.querySelectorAll('.cp-chip')];
		expect(tags.length).toBeGreaterThanOrEqual(2);
		for (const t of tags) expect(rect(t).right).toBeLessThanOrEqual(rect(li).right);
		const val = li.querySelector('.cp-val-value b')!;
		for (const t of tags) expect(rect(t).top).toBeGreaterThanOrEqual(rect(val).bottom - 1); // under the value
		const label = li.querySelector('.cp-val-label')!;
		for (const t of tags) expect(hit(rect(label), rect(t))).toBe(false);
	});
});

describe('rail scrolls inside', () => {
	it('is bounded with internal scroll and does not grow the page', async () => {
		const f = { id: 'u1', unitId: 1, text: 'Solid pulmonary nodule', region: 'LUNGS' };
		const cards = Array.from({ length: 20 }, (_, i) => card({ key: `k${i}`, name: `Guideline number ${i}`, finding: f.text }));
		const before = document.documentElement.scrollHeight;
		render(CopilotRail, {
			layout: 'wide',
			groups: [{ finding: f, cards }],
			views: {},
			matching: false,
			matchFailed: false,
			otherState: 'idle' as const,
			onOpen: vi.fn(),
			onClose: vi.fn(),
			onRetry: vi.fn(),
			onRetryMatch: vi.fn(),
			onOther: vi.fn()
		});
		await expect.element(page.getByText('Guideline number 0')).toBeInTheDocument();
		const rail = document.querySelector('[data-testid="copilot-rail"]') as HTMLElement;
		const cs = getComputedStyle(rail);
		expect(parseFloat(cs.maxHeight)).toBeCloseTo(window.innerHeight - 64, 0); // calc(100vh - 4rem)
		expect(['auto', 'scroll']).toContain(cs.overflowY);
		expect(rect(rail).height).toBeLessThanOrEqual(window.innerHeight - 64 + 1);
		const body = rail.querySelector('.rv-body') as HTMLElement;
		expect(body.scrollHeight).toBeGreaterThan(body.clientHeight);
		expect(document.documentElement.scrollHeight).toBeLessThanOrEqual(Math.max(before, window.innerHeight));
	});
});

describe('long blocks scroll', () => {
	it('an open reference block has a max-height and scrolls', async () => {
		const c = card();
		const h = host();
		const long = { ...reference, summary: Array.from({ length: 40 }, (_, i) => ({ id: `s${i}`, text: `Line ${i} of a long summary that goes on.`, citation: { title: 'G', page: i } })) };
		render(PackCard, {
			target: h,
			props: {
				card: c,
				view: { open: true, loading: false, error: null, result: result(c, preview(), { reference: long }) },
				onOpen: vi.fn(),
				onClose: vi.fn(),
				onRetry: vi.fn()
			}
		});
		await page.getByRole('button', { name: 'Reference' }).click();
		const body = h.querySelector('.cp-ref-body') as HTMLElement;
		expect(body).not.toBeNull();
		const cs = getComputedStyle(body);
		expect(parseFloat(cs.maxHeight)).toBe(256); // 16rem
		expect(cs.overflowY).toBe('auto');
		expect(body.scrollHeight).toBeGreaterThan(body.clientHeight);
	});
});
