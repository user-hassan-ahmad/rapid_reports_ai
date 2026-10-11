import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});
const GROUPS = ['Technique', 'Liver', 'Kidneys', 'Spleen', 'Other findings', 'General', 'Conclusion'];
const PILLS = ['Liver', 'Kidneys', 'Spleen'];
const base = () => ({ groups: GROUPS, pillRegions: PILLS, onMove: vi.fn(), onEditLine: vi.fn(), onChipAccept: vi.fn(), onConfirm: vi.fn() });

describe('HybridStackView v2', () => {
	it('abnormal regions in the scratchpad, normals in the tray (solid when dictated, dashed when assumed)', async () => {
		const props = base();
		render(HybridStackView, {
			...props,
			units: [
				u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'], structure: 'liver' }),
				u(1, 'The kidneys are normal.', 'Kidneys', { covers: ['Kidneys'] })
			],
			chips: [{ region: 'Liver', text: 'No biliary dilatation.', state: 'included' }, { region: 'Liver', text: 'No portal vein thrombus.', state: 'optional' }],
			onChipRemove: vi.fn()
		});
		await expect.element(page.getByRole('heading', { name: 'Liver' })).toBeInTheDocument();
		await expect.element(page.getByRole('heading', { name: 'Kidneys' })).not.toBeInTheDocument();
		await expect.element(page.getByText('Remainder of liver: assumed normal')).toBeInTheDocument();
		await expect.element(page.getByText('Kidneys', { exact: true })).toHaveAttribute('data-state', 'dictated');
		await expect.element(page.getByText('Spleen', { exact: true })).toHaveAttribute('data-state', 'assumed');
		await expect.element(page.getByText(/stated, not dictated: No biliary dilatation\./)).toBeInTheDocument();
		await page.getByText('+ No portal vein thrombus.').click();
		expect(props.onChipAccept).toHaveBeenCalledWith('No portal vein thrombus.');
	});

	it('shows the live strip and lets a line be edited and committed with Enter', async () => {
		const props = base();
		render(HybridStackView, {
			...props,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			pending: ['The spleen is normal.'],
			ghost: 'kidneys are'
		});
		await expect.element(page.getByText('The spleen is normal.')).toBeInTheDocument();
		await expect.element(page.getByText('kidneys are')).toBeInTheDocument();
		await page.getByText('An 8 mm liver cyst.').click();
		await page.getByLabelText('Edit line').fill('A 9 mm liver cyst.');
		await userEvent.keyboard('{Enter}');
		expect(props.onEditLine).toHaveBeenCalledWith(0, null, 'A 9 mm liver cyst.');
	});

	it('dictation goes into the open line at the caret', async () => {
		const props = base();
		const r = render(HybridStackView, { ...props, units: [u(0, 'A liver cyst.', 'Liver', { abnormal: true })] });
		await page.getByText('A liver cyst.').click();
		const input = page.getByLabelText('Edit line').element() as HTMLInputElement;
		input.setSelectionRange(2, 2);
		r.rerender({ ...props, units: [u(0, 'A liver cyst.', 'Liver', { abnormal: true })], incoming: { seq: 1, text: '9 mm' } });
		await expect.element(page.getByLabelText('Edit line')).toHaveValue('A 9 mm liver cyst.');
	});

	it('the gate lists the assumed normals and confirms with a click', async () => {
		const props = base();
		render(HybridStackView, {
			...props,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')],
			conclusion: { kind: 'dictated' }
		});
		await expect.element(page.getByText(/normal, not dictated: Kidneys, Spleen, remainder of liver/)).toBeInTheDocument();
		await page.getByRole('button', { name: 'Confirm' }).click();
		expect(props.onConfirm).toHaveBeenCalled();
	});

	it('Confirm waits for a conclusion; with none, the field asks for one and offers a draft', async () => {
		const onDraftRefresh = vi.fn();
		render(HybridStackView, { ...base(), onDraftRefresh, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })], conclusion: { kind: 'none', failed: true } });
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeDisabled();
		await expect.element(page.getByPlaceholder('Type or dictate a conclusion')).toBeInTheDocument();
		await expect.element(page.getByText(/could not be made/)).toBeInTheDocument();
		await page.getByText('Draft one').click();
		expect(onDraftRefresh).toHaveBeenCalled();
	});

	it('shows an editable AI draft and the refresh prompt when findings changed', async () => {
		const onDraftRefresh = vi.fn();
		render(HybridStackView, {
			...base(),
			onDraftRefresh,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			conclusion: { kind: 'draft', text: 'Simple hepatic cyst.', stale: true, edited: false }
		});
		await expect.element(page.getByText('AI draft')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Conclusion draft')).toHaveValue('Simple hepatic cyst.');
		await page.getByText('Findings changed — refresh?').click();
		expect(onDraftRefresh).toHaveBeenCalled();
	});
});
