// The numbered finding marker on a rail group (replaces the repeated finding text in the header). SYNTHETIC.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import CopilotCards from './CopilotCards.svelte';
import { card } from './fixtures';
import type { Group } from '../state';

const f1 = { id: 'u1', unitId: 1, text: '9 mm solid nodule in the right upper lobe, previously 6 mm on the last study', region: 'LUNGS' };
const f2 = { id: 'u4.1', unitId: 4, text: 'Simple renal cyst', region: 'KIDNEYS' };
const exam = card({ key: 'cad-rads-2', name: 'CAD-RADS 2.0', finding_id: 'exam', finding: 'Coronary CT' });
const a = card({ key: 'bts', name: 'BTS 2015', finding_id: 'u1', finding: f1.text });
const b = card({ key: 'bosniak', name: 'Bosniak', finding_id: 'u4.1', finding: f2.text });
const groups: Group[] = [{ finding: null, cards: [exam] }, { finding: f1, cards: [a] }, { finding: f2, cards: [b] }];
const base = (over: Record<string, unknown> = {}) => ({
	groups, views: {}, matching: false, matchFailed: false, otherState: 'idle' as const,
	onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn(), onRetryMatch: vi.fn(), onOther: vi.fn(), ...over
});

describe('rail finding markers', () => {
	it('a finding group shows its number, named for screen readers; the exam group has none; no visible finding text', async () => {
		render(CopilotCards, base());
		await expect.element(page.getByLabelText(`Finding 1: ${f1.text}`)).toHaveTextContent('1');
		await expect.element(page.getByLabelText(`Finding 2: ${f2.text}`)).toHaveTextContent('2');
		expect(document.querySelectorAll('[data-finding-mark-rail]').length).toBe(2);
		expect(document.querySelector('.cp-group-head')!.textContent).not.toContain('previously 6 mm');
		expect(document.querySelector('[data-finding-mark-rail="u1"]')!.getAttribute('title')).toBe(f1.text);
	});

	it('hovering or focusing a group reports its finding; leaving reports null', async () => {
		const onFindingHover = vi.fn();
		render(CopilotCards, base({ onFindingHover }));
		const g = document.querySelector('[data-finding-card="u1"]') as HTMLElement;
		await userEvent.hover(g);
		expect(onFindingHover).toHaveBeenLastCalledWith('u1');
		await userEvent.unhover(g);
		expect(onFindingHover).toHaveBeenLastCalledWith(null);
	});

	it('the active finding outlines its group', async () => {
		render(CopilotCards, base({ activeFinding: 'u4.1' }));
		expect(document.querySelector('[data-finding-card="u4.1"]')!.classList.contains('cp-active')).toBe(true);
		expect(document.querySelector('[data-finding-card="u1"]')!.classList.contains('cp-active')).toBe(false);
	});

	it('moving focus between controls inside one group does not report a leave', async () => {
		const onFindingHover = vi.fn();
		render(CopilotCards, base({ onFindingHover }));
		const g = document.querySelector('[data-finding-card="u1"]') as HTMLElement;
		const inner = g.querySelector('.cp-card') as HTMLElement; // any element inside the group
		onFindingHover.mockClear();
		g.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: inner }));
		expect(onFindingHover).not.toHaveBeenCalled();
		g.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
		expect(onFindingHover).toHaveBeenLastCalledWith(null);
	});
});
