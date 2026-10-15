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
});
