// Round 1 (side check, 2026-10-13): Confirm and the walk wait while the model check runs on the text on screen.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});
const props = (extra: Record<string, unknown> = {}) => ({
	groups: ['Menisci', 'Other findings', 'General', 'Conclusion'], pillRegions: ['Menisci'], onMove: vi.fn(), onEditLine: vi.fn(), onConfirm: vi.fn(),
	units: [u(0, 'Horizontal tear in the lateral meniscus.', 'Menisci', { abnormal: true })],
	conclusion: { kind: 'draft', text: 'Lateral meniscal tear.', edited: false } as const, namedNormals: true, ...extra
});

describe('Confirm waits for the model check', () => {
	it('shows "Checking…" and holds Confirm while the check runs; Confirm opens when it ends', async () => {
		const p = props({ checking: true });
		const { rerender } = render(HybridStackView, p);
		const btn = page.getByRole('button', { name: 'Checking…' });
		await expect.element(btn).toBeDisabled();
		await rerender({ ...p, checking: false });
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		expect(p.onConfirm).toHaveBeenCalledOnce();
	});

	it('holds the walk while the check runs, even with a blocking flag already shown', async () => {
		const c = { key: 'side', kind: 'laterality_conflict', blocking: true, tier: 2 as const, message: 'Left or right?',
			quote: 'lateral meniscus', other: null, suggestion: '', unitId: 0 };
		const p = props({ checks: [c], checking: true });
		const { rerender } = render(HybridStackView, p);
		await expect.element(page.getByRole('button', { name: 'Checking…' })).toBeDisabled();
		await expect.element(page.getByRole('button', { name: /to check/ })).toBeDisabled();
		await rerender({ ...p, checking: false });
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await expect.element(page.getByTestId('walkthrough')).toBeInTheDocument();
		expect(p.onConfirm).not.toHaveBeenCalled();
	});
});
