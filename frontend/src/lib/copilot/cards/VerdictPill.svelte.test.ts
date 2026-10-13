// VerdictPill (redesign fix round 1): a native title only when the text is cut off. SYNTHETIC verdicts.
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import VerdictPill from './VerdictPill.svelte';
import type { Verdict } from './format';

const v = (pill: string): Verdict => ({ category: 'none', pill, headline: '', action: pill, classification: '', caveats: [], citations: [] });
const pill = () => document.querySelector('.cp-pill') as HTMLElement;

describe('VerdictPill', () => {
	it('fits: no native title (it would repeat what is on screen), even on hover', async () => {
		render(VerdictPill, { verdict: v('No further imaging') });
		await expect.element(page.getByText('No further imaging')).toBeInTheDocument();
		pill().dispatchEvent(new PointerEvent('pointerenter'));
		await Promise.resolve();
		expect(pill().hasAttribute('title')).toBe(false);
	});

	it('cut off: the title carries the full text once hovered or focused', async () => {
		const host = document.createElement('div');
		host.style.width = '120px';
		document.body.appendChild(host);
		const long = 'Low-risk patient: optional CT at 12 months, then discharge';
		render(VerdictPill, { target: host, props: { verdict: v(long) } });
		await expect.element(page.getByText(long)).toBeInTheDocument();
		(document.querySelector('.cp-pill') as HTMLElement).style.maxWidth = '100px';
		pill().dispatchEvent(new PointerEvent('pointerenter'));
		await expect.poll(() => pill().getAttribute('title')).toBe(long);
	});

	it('takes the text token, not the -line token, for its words', async () => {
		render(VerdictPill, { verdict: v('Ok') });
		await expect.element(page.getByText('Ok')).toBeInTheDocument();
		expect(pill().style.getPropertyValue('--cp-cat-text')).toBe('var(--rv-green-text)');
		expect(pill().style.getPropertyValue('--cp-cat')).toBe('var(--rv-green-line)');
	});
});
