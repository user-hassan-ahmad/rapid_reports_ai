// /dev/copilot (Task A5). SYNTHETIC fixtures only; no backend. Set VITE_COPILOT_SHOTS=<dir> to save one screenshot
// per section and per rail width (the browser-check substitute until the A7 Chrome checkpoint).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';

const env = vi.hoisted(() => ({}) as Record<string, string | undefined>);
vi.mock('$env/dynamic/public', () => ({ env }));
const api = vi.hoisted(() => ({ postMatch: vi.fn(), postMatchOther: vi.fn(), postOpen: vi.fn(), postPreview: vi.fn() }));
vi.mock('$lib/copilot/api', async (orig) => ({ ...(await orig<object>()), ...api }));

const { load } = await import('./+page');
const { default: DevCopilot } = await import('./+page.svelte');
const { sections } = await import('./gallery');

const SHOTS = import.meta.env.VITE_COPILOT_SHOTS as string | undefined;
const shot = async (el: HTMLElement, name: string) => {
	if (!SHOTS) return;
	await page.viewport(470, 1000); // just wide enough for a 420 px column (a wider viewport is scaled down in the runner)
	await page.screenshot({ element: el, path: `${SHOTS}/${name}.png` });
};

afterEach(() => {
	delete env.PUBLIC_ENABLE_DEV_ROUTES;
});

describe('/dev/copilot', () => {
	it('404s unless PUBLIC_ENABLE_DEV_ROUTES is "true"', () => {
		expect(() => load()).toThrow(expect.objectContaining({ status: 404 }));
		env.PUBLIC_ENABLE_DEV_ROUTES = 'false';
		expect(() => load()).toThrow(expect.objectContaining({ status: 404 }));
		env.PUBLIC_ENABLE_DEV_ROUTES = 'true';
		expect(() => load()).not.toThrow();
	});

	it('renders one section per state, with no Apply, Calculate on pack cards only, and no API call', async () => {
		const errors: unknown[] = [];
		const onErr = (e: ErrorEvent) => errors.push(e.message);
		window.addEventListener('error', onErr);
		render(DevCopilot);
		for (const s of sections) await expect.element(page.getByTestId(`dv-${s.id}`)).toBeInTheDocument();
		const t = (id: string) => document.querySelector(`[data-testid="dv-${id}"]`)!.textContent!.replace(/\s+/g, ' ');
		expect(t('quiet')).toMatch(/CAD-RADS 2\.0\s*·\s*CAD-RADS 0/);
		expect(t('exam-set')).toContain('set by the exam');
		expect(t('needs-modality')).toContain('BTA U grading needs ultrasound to grade');
		expect(t('match-failed')).toContain("Couldn't check guidelines");
		expect(t('empty')).toContain('No guideline applies yet');
		expect(t('siblings')).toContain('BTS 2015');
		const names = [...document.querySelectorAll('button, [role="button"]')].map((b) => (b.textContent ?? '').trim());
		expect(names.some((n) => /^apply\b/i.test(n))).toBe(false); // Apply stays off
		// Calculate (Slice B2) only on pack cards, never on a read-only card (needs-modality, reference, TNM)
		for (const id of ['needs-modality', 'reference', 'tnm']) expect(document.querySelector(`[data-testid="dv-${id}"]`)!.textContent).not.toMatch(/Calculate/);
		for (const s of sections) await shot(document.querySelector(`[data-testid="dv-${s.id}"]`)!, `section-${s.id}`);
		if (SHOTS) {
			await page.getByRole('radio', { name: 'Light' }).click();
			for (const s of sections) await shot(document.querySelector(`[data-testid="dv-${s.id}"]`)!, `light-section-${s.id}`);
			await page.getByRole('radio', { name: 'Dark' }).click();
		}
		window.removeEventListener('error', onErr);
		expect(errors).toEqual([]);
		expect(Object.values(api).every((f) => !f.mock.calls.length)).toBe(true);
	});

	it('Other guidelines adds an "other" card under its finding; keyboard opens and closes a card', async () => {
		render(DevCopilot);
		const other = page.getByTestId('dv-other');
		await other.getByRole('button', { name: 'Other guidelines' }).click();
		await expect.element(other.getByText('A society nodule guide')).toBeInTheDocument();
		await expect.element(other.getByText('Other guidelines checked')).toBeInTheDocument();
		const head = page.getByTestId('dv-collapsed').getByRole('button', { name: /Fleischner 2017/ });
		(head.element() as HTMLElement).focus();
		await expect.element(page.getByTestId('dv-collapsed').getByText('RECOMMENDATION', { exact: true })).not.toBeInTheDocument();
		await userEvent.keyboard('{Enter}');
		await expect.element(page.getByTestId('dv-collapsed').getByText('RECOMMENDATION', { exact: true })).toBeInTheDocument();
		await userEvent.keyboard('{Enter}');
		await expect.element(page.getByTestId('dv-collapsed').getByText('RECOMMENDATION', { exact: true })).not.toBeInTheDocument();
	});

	it('renders the whole case in CopilotRail, wide and narrow', async () => {
		render(DevCopilot);
		await page.getByRole('radio', { name: 'Rail, wide' }).click();
		const rail = page.getByTestId('copilot-rail');
		await expect.element(rail.getByRole('tab', { name: 'Guidelines' })).toBeInTheDocument();
		await expect.element(rail.getByRole('button', { name: /CAD-RADS 2\.0.*CAD-RADS 0/ })).toBeInTheDocument();
		await shot(rail.element() as HTMLElement, 'rail-wide');
		await page.getByRole('radio', { name: 'Rail, narrow' }).click();
		const strip = page.getByRole('button', { name: 'Copilot: 7 guidelines' });
		await expect.element(strip).toBeInTheDocument();
		await shot(page.getByTestId('copilot-rail').element() as HTMLElement, 'rail-narrow-strip');
		await strip.click();
		const dialog = page.getByRole('dialog', { name: 'Copilot' });
		await expect.element(dialog).toBeInTheDocument();
		await shot(dialog.element() as HTMLElement, 'rail-narrow-open');
	});
});
