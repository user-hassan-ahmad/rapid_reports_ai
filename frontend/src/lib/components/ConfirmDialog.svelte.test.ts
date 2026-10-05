// The in-app confirmation (not window.confirm) and its promise gate, used by History "Open" over unsaved work.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import { get } from 'svelte/store';
import ConfirmDialog from './ConfirmDialog.svelte';
import { confirmIfUnsaved, createConfirmGate, hasUnsavedWork } from '$lib/utils/confirmGate';

afterEach(() => vi.restoreAllMocks());

describe('ConfirmDialog', () => {
	it('shows title and message as an alertdialog; Cancel and Confirm call their handlers', async () => {
		const onConfirm = vi.fn();
		const onCancel = vi.fn();
		render(ConfirmDialog, {
			open: true,
			title: 'Replace the open report?',
			message: 'You have unsaved changes.',
			confirmLabel: 'Open anyway',
			onConfirm,
			onCancel
		});
		await expect.element(page.getByRole('alertdialog', { name: 'Replace the open report?' })).toBeInTheDocument();
		await expect.element(page.getByText('You have unsaved changes.')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Cancel' }).click();
		expect(onCancel).toHaveBeenCalledTimes(1);
		await page.getByRole('button', { name: 'Open anyway' }).click();
		expect(onConfirm).toHaveBeenCalledTimes(1);
	});

	it('Escape cancels; Cancel has focus first (the safe choice)', async () => {
		const onCancel = vi.fn();
		render(ConfirmDialog, { open: true, title: 'T', message: 'M', onConfirm: vi.fn(), onCancel });
		await expect.element(page.getByRole('button', { name: 'Cancel' })).toHaveFocus();
		await userEvent.keyboard('{Escape}');
		expect(onCancel).toHaveBeenCalledTimes(1);
	});

	it('renders nothing when closed', async () => {
		render(ConfirmDialog, { open: false, title: 'T', message: 'M', onConfirm: vi.fn(), onCancel: vi.fn() });
		expect(page.getByRole('alertdialog').elements()).toHaveLength(0);
	});
});

describe('createConfirmGate', () => {
	it('ask() opens the gate and resolves with the answer, then closes it', async () => {
		const gate = createConfirmGate();
		expect(get(gate.pending)).toBe(false);
		const yes = gate.ask();
		expect(get(gate.pending)).toBe(true);
		gate.answer(true);
		await expect(yes).resolves.toBe(true);
		expect(get(gate.pending)).toBe(false);
		const no = gate.ask();
		gate.answer(false);
		await expect(no).resolves.toBe(false);
	});

	it('a second ask cancels the first', async () => {
		const gate = createConfirmGate();
		const first = gate.ask();
		const second = gate.ask();
		await expect(first).resolves.toBe(false);
		gate.answer(true);
		await expect(second).resolves.toBe(true);
	});
});

describe('hasUnsavedWork (the tabs\' rule)', () => {
	const base = { recording: false, findings: '', findingsAtReport: '', editorDirty: false };
	it('a dictation in progress: recording, or findings no report was generated from', () => {
		expect(hasUnsavedWork(base)).toBe(false);
		expect(hasUnsavedWork({ ...base, recording: true })).toBe(true);
		expect(hasUnsavedWork({ ...base, findings: 'spleen 9 cm' })).toBe(true);
		expect(hasUnsavedWork({ ...base, findings: 'spleen 9 cm', findingsAtReport: 'spleen 9 cm' })).toBe(false);
	});
	it('unsaved editor changes', () => {
		expect(hasUnsavedWork({ ...base, editorDirty: true })).toBe(true);
	});
});

describe('confirmIfUnsaved', () => {
	it('goes ahead without asking when nothing is unsaved; else returns the answer', async () => {
		const ask = vi.fn(async () => false);
		await expect(confirmIfUnsaved({ hasUnsavedWork: () => false }, ask)).resolves.toBe(true);
		await expect(confirmIfUnsaved(null, ask)).resolves.toBe(true);
		expect(ask).not.toHaveBeenCalled();
		await expect(confirmIfUnsaved({ hasUnsavedWork: () => true }, ask)).resolves.toBe(false);
		expect(ask).toHaveBeenCalledTimes(1);
	});
});
