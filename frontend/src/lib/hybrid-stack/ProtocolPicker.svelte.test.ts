import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import ProtocolPicker from './ProtocolPicker.svelte';

const KNEE = { id: 'TMKN', display_name: 'MRI Knee', protocol_line: 'No contrast', laterality: 'required',
	variants: [{ phases: [], line: 'No contrast', default: true }] };
const CTAP = { id: 'TCAP', display_name: 'CT Abdomen and Pelvis with contrast', protocol_line: 'IV contrast · portal venous', laterality: 'none',
	variants: [{ phases: ['portal_venous'], line: 'IV contrast · portal venous', default: true },
		{ phases: ['arterial', 'portal_venous'], line: 'IV contrast · arterial, portal venous', default: false }] };

function stubFetch(options: unknown[], hint = false) {
	vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ options, not_listed_hint: hint, promoted: null }), { status: 200 })));
}
afterEach(() => vi.unstubAllGlobals());

describe('ProtocolPicker', () => {
	it('shows each option with its protocol line in italics and picks the default phases', async () => {
		stubFetch([CTAP]);
		const onPick = vi.fn();
		render(ProtocolPicker, { token: 't', value: null, onPick, onNotListed: vi.fn() });
		await userEvent.type(page.getByRole('combobox'), 'ctap');
		await expect.element(page.getByText('IV contrast · portal venous', { exact: true }).first()).toBeInTheDocument();
		await page.getByText('CT Abdomen and Pelvis with contrast').click();
		await page.getByRole('button', { name: 'Use this protocol' }).click();
		expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'TCAP', phases: ['portal_venous'], laterality: null }));
	});

	it('needs a side before a lateral protocol can be used', async () => {
		stubFetch([KNEE]);
		const onPick = vi.fn();
		render(ProtocolPicker, { token: 't', value: null, onPick, onNotListed: vi.fn() });
		await userEvent.type(page.getByRole('combobox'), 'mri kn');
		await page.getByText('MRI Knee').click();
		await expect.element(page.getByRole('button', { name: 'Use this protocol' })).toBeDisabled();
		await page.getByRole('radio', { name: 'Left' }).click();
		await page.getByRole('button', { name: 'Use this protocol' }).click();
		expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'TMKN', laterality: 'left' }));
	});

	it('offers "Not listed" with the typed text', async () => {
		stubFetch([], true);
		const onNotListed = vi.fn();
		render(ProtocolPicker, { token: 't', value: null, onPick: vi.fn(), onNotListed });
		await userEvent.type(page.getByRole('combobox'), 'us abdo');
		await page.getByRole('button', { name: /Not listed/ }).click();
		expect(onNotListed).toHaveBeenCalledWith('us abdo');
	});
});
