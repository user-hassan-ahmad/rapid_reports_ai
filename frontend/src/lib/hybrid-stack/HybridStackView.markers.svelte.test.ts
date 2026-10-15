// Finding markers in the scratchpad margin (spec: finding markers 2026-10-15). SYNTHETIC.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});
const GROUPS = ['Technique', 'Lungs', 'Kidneys', 'General', 'Conclusion'];
const base = () => ({ groups: GROUPS, pillRegions: ['Lungs', 'Kidneys'], onMove: vi.fn(), onEditLine: vi.fn(), onConfirm: vi.fn() });
const units = [u(1, 'A 7 mm solid nodule.', 'Lungs', { abnormal: true, covers: ['Lungs'] }), u(4, 'A simple renal cyst.', 'Kidneys', { abnormal: true, covers: ['Kidneys'] }), u(7, 'The liver is normal.', 'Kidneys')];

describe('scratchpad finding markers', () => {
	it('a line whose unit matches a finding id shows its number; other lines show none', async () => {
		render(HybridStackView, { ...base(), units, findingMarks: { u1: 1, 'u4.1': 2 } });
		await expect.element(page.getByLabelText('Finding 1: A 7 mm solid nodule.')).toHaveTextContent('1');
		await expect.element(page.getByLabelText('Finding 2: A simple renal cyst.')).toHaveTextContent('2'); // a part id marks its unit's line
		expect(document.querySelectorAll('[data-finding-mark]').length).toBe(2);
	});

	it('the active finding highlights its line (and only that one)', async () => {
		render(HybridStackView, { ...base(), units, findingMarks: { u1: 1, u4: 2 }, activeFinding: 'u4' });
		const lines = [...document.querySelectorAll('[data-finding-line]')] as HTMLElement[];
		expect(lines.length).toBe(2);
		expect(lines.filter((l) => l.dataset.findingActive === 'true').map((l) => l.textContent)).toEqual([expect.stringContaining('simple renal cyst')]);
	});

	it('hovering the marker reports the finding; leaving reports null', async () => {
		const onFindingHover = vi.fn();
		render(HybridStackView, { ...base(), units, findingMarks: { u1: 1 }, onFindingHover });
		const m = document.querySelector('[data-finding-mark="u1"]') as HTMLElement;
		await userEvent.hover(m);
		expect(onFindingHover).toHaveBeenCalledWith('u1');
		await userEvent.unhover(m);
		expect(onFindingHover).toHaveBeenLastCalledWith(null);
	});

	it('no marks (Copilot off): no marker, no highlight', async () => {
		render(HybridStackView, { ...base(), units });
		await expect.element(page.getByText('A 7 mm solid nodule.')).toBeInTheDocument();
		expect(document.querySelector('[data-finding-mark]')).toBeNull();
		expect(document.querySelector('[data-finding-active="true"]')).toBeNull();
	});

	it('the marker sits at the right edge of its line, fully inside the scroller, clear of the text', async () => {
		render(HybridStackView, { ...base(), units, findingMarks: { u1: 1 } });
		const root = document.querySelector('[data-testid="hybrid-stack"]') as HTMLElement;
		const scroller = root.parentElement as HTMLElement;
		Object.assign(scroller.style, { overflow: 'auto', width: '480px', padding: '0 16px 0 16px' });
		const m = (document.querySelector('[data-finding-mark="u1"]') as HTMLElement).getBoundingClientRect();
		const box = scroller.getBoundingClientRect();
		expect(m.left).toBeGreaterThanOrEqual(box.left);
		expect(m.right).toBeLessThanOrEqual(box.right);
		// Tailwind is not loaded in this browser test, so the geometry above is the unstyled flow; the placement is pinned
		// structurally: the marker is the line's last flex child (right edge, beside the text column, never inside it where
		// the edit and delete controls live), carrying `shrink-0` so it keeps its room.
		const li = document.querySelector('[data-finding-line]') as HTMLElement;
		const holder = li.lastElementChild as HTMLElement;
		expect(holder.contains(document.querySelector('[data-finding-mark="u1"]'))).toBe(true);
		expect(holder.classList.contains('shrink-0')).toBe(true);
		expect(li.classList.contains('flex')).toBe(true);
		expect((li.firstElementChild as HTMLElement).contains(holder)).toBe(false);
	});

	it('one marker per finding even when a unit renders as several rows', async () => {
		const dup = [u(1, 'A 7 mm solid nodule.', 'Lungs', { abnormal: true, covers: ['Lungs'] }), u(1, 'Nodule, second row.', 'Kidneys', { abnormal: true, covers: ['Kidneys'] })];
		render(HybridStackView, { ...base(), units: dup, findingMarks: { u1: 1 } });
		expect(document.querySelectorAll('[data-finding-mark="u1"]').length).toBe(1);
	});

	it('keyboard: the marker takes focus; focusing it or its line reports the finding, leaving reports null', async () => {
		const onFindingHover = vi.fn();
		render(HybridStackView, { ...base(), units, findingMarks: { u1: 1 }, onFindingHover });
		const m = document.querySelector('[data-finding-mark="u1"]') as HTMLElement;
		expect(m.tagName).toBe('BUTTON');
		m.focus();
		expect(onFindingHover).toHaveBeenLastCalledWith('u1');
		m.blur();
		expect(onFindingHover).toHaveBeenLastCalledWith(null);
	});
});
