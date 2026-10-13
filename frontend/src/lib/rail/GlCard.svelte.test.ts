import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import { createRawSnippet } from 'svelte';
import GlCard from './GlCard.svelte';

// SYNTHETIC card content only.
const body = createRawSnippet(() => ({ render: () => '<p>Card body</p>' }));
const controls = createRawSnippet(() => ({ render: () => '<button type="button">Ask →</button>' }));
const card = () => document.querySelector<HTMLElement>('.gl-card')!;
const head = () => card().querySelector<HTMLElement>('.gl-head')!;

describe('GlCard', () => {
	it('toggles the body on click; the hint shows only while collapsed', async () => {
		render(GlCard, { title: 'Synthetic nodule', hint: 'CT · 6 months', body });
		expect(card().querySelector('.gl-body')).toBeNull();
		expect(card().querySelector('.gl-action-hint')?.textContent).toBe('→ CT · 6 months');
		head().click();
		await expect.element(page.getByText('Card body')).toBeInTheDocument();
		expect(card().querySelector('.gl-action-hint')).toBeNull();
		expect(head().classList.contains('gl-head--open')).toBe(true);
		head().click();
		await expect.element(page.getByText('Card body')).not.toBeInTheDocument();
	});

	it('toggles on Enter and Space', async () => {
		render(GlCard, { title: 'Synthetic nodule', body });
		head().focus();
		await userEvent.keyboard('{Enter}');
		await expect.element(page.getByText('Card body')).toBeInTheDocument();
		await userEvent.keyboard(' ');
		await expect.element(page.getByText('Card body')).not.toBeInTheDocument();
	});

	it('renders the title, badge, accent and controls', async () => {
		render(GlCard, {
			title: 'Synthetic nodule',
			badge: { text: 'SYS 2', variant: 'v' },
			accent: '#f59e0b',
			controls
		});
		await expect.element(page.getByRole('button', { name: 'Ask →', exact: true })).toBeInTheDocument();
		expect(card().querySelector('.gl-title')?.textContent).toBe('Synthetic nodule');
		const badge = card().querySelector('.gl-grade-badge')!;
		expect(badge.textContent).toBe('SYS 2');
		expect(badge.classList.contains('ch-v')).toBe(true);
		expect(card().style.getPropertyValue('--gl-accent')).toBe('#f59e0b');
		expect(card().querySelector('.gl-controls button')).not.toBeNull();
	});

	it('dim fades the card and describes its head (never aria-disabled, which would disable its buttons); it still opens', async () => {
		render(GlCard, { title: 'Synthetic nodule', dim: true, body });
		expect(card().hasAttribute('aria-disabled')).toBe(false);
		expect(card().classList.contains('gl-card--dim')).toBe(true);
		expect(document.getElementById(head().getAttribute('aria-describedby')!)!.textContent).toBe('Does not apply');
		head().click();
		await expect.element(page.getByText('Card body')).toBeInTheDocument();
	});

	it('is not aria-disabled by default', async () => {
		render(GlCard, { title: 'Synthetic nodule' });
		expect(card().hasAttribute('aria-disabled')).toBe(false);
	});

	it('honours a bound open from the host', async () => {
		render(GlCard, { title: 'Synthetic nodule', open: true, body });
		await expect.element(page.getByText('Card body')).toBeInTheDocument();
	});
});
