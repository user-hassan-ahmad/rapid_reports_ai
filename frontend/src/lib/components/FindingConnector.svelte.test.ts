// The connector overlay: one faint curve from the rail group to the scratchpad marker, only while a finding is active. SYNTHETIC.
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import FindingConnector from './FindingConnector.svelte';

function ends() {
	const pad = document.createElement('span');
	pad.setAttribute('data-finding-mark', 'u1');
	Object.assign(pad.style, { position: 'fixed', left: '20px', top: '200px', width: '16px', height: '16px' });
	const rail = document.createElement('div');
	rail.setAttribute('data-finding-card', 'u1');
	Object.assign(rail.style, { position: 'fixed', left: '200px', top: '80px', width: '150px', height: '40px' });
	document.body.append(pad, rail);
	return () => { pad.remove(); rail.remove(); };
}

describe('FindingConnector', () => {
	it('draws a thin aria-hidden curve while a finding is active, none otherwise', async () => {
		const cleanup = ends();
		try {
			const r = render(FindingConnector, { active: null, minWidth: 0 });
			expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
			await r.rerender({ active: 'u1', minWidth: 0 });
			await expect.poll(() => document.querySelector('[data-testid="finding-connector"] path')?.getAttribute('d') ?? '').toMatch(/^M 36 208 C /);
			const svg = document.querySelector('[data-testid="finding-connector"]')!;
			expect(svg.getAttribute('aria-hidden')).toBe('true');
			expect(getComputedStyle(svg).pointerEvents).toBe('none');
			await r.rerender({ active: null, minWidth: 0 });
			await expect.poll(() => document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
		} finally { cleanup(); }
	});
	it('draws nothing in the narrow overlay layout', async () => {
		const cleanup = ends();
		try {
			render(FindingConnector, { active: 'u1', minWidth: 100000 });
			await new Promise((res) => setTimeout(res, 100));
			expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
		} finally { cleanup(); }
	});
	it('draws nothing when the marker is not in the viewport', async () => {
		const cleanup = ends();
		(document.querySelector('[data-finding-mark="u1"]') as HTMLElement).style.top = '-500px';
		try {
			render(FindingConnector, { active: 'u1', minWidth: 0 });
			await new Promise((res) => setTimeout(res, 100));
			expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
		} finally { cleanup(); }
	});
	it('draws nothing while the marker is scrolled out of its own pane', async () => {
		const cleanup = ends();
		const pad = document.querySelector('[data-finding-mark="u1"]') as HTMLElement;
		const pane = document.createElement('div');
		Object.assign(pane.style, { position: 'fixed', left: '0', top: '250px', width: '120px', height: '100px', overflow: 'auto' });
		pad.style.position = 'absolute';
		pad.style.top = '-10px'; // inside the viewport but above the pane's top edge
		pad.style.left = '10px';
		pane.append(pad);
		document.body.append(pane);
		try {
			render(FindingConnector, { active: 'u1', minWidth: 0 });
			await new Promise((res) => setTimeout(res, 100));
			expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
		} finally { cleanup(); pane.remove(); }
	});
	it('card header inside a clipping wrapper inside a scroller, scrolled out of the scroller but still on screen: no curve', async () => {
		const cleanup = ends();
		const rail = document.querySelector('[data-finding-card="u1"]') as HTMLElement;
		const scroller = document.createElement('div');
		Object.assign(scroller.style, { position: 'fixed', left: '150px', top: '300px', width: '250px', height: '100px', overflow: 'auto' });
		const clip = document.createElement('div'); // like .gl-card: overflow hidden for the rounded corners
		Object.assign(clip.style, { overflow: 'hidden', height: '300px' });
		Object.assign(rail.style, { position: 'static', width: '150px', height: '40px', marginLeft: '50px' });
		clip.append(rail);
		scroller.append(clip);
		document.body.append(scroller);
		scroller.scrollTop = 0; // the card is at the top of the clip; push it above the scroller's visible part
		clip.style.paddingTop = '0px';
		scroller.scrollTop = 150;
		try {
			render(FindingConnector, { active: 'u1', minWidth: 0 });
			await new Promise((res) => setTimeout(res, 100));
			expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
			scroller.scrollTop = 0;
			await expect.poll(() => document.querySelector('[data-testid="finding-connector"] path')?.getAttribute('d') ?? '').toMatch(/^M /);
		} finally { cleanup(); scroller.remove(); }
	});

	it('re-attaches when the two containers mount after the overlay', async () => {
		render(FindingConnector, { active: 'u1', minWidth: 0 });
		await new Promise((res) => setTimeout(res, 50));
		expect(document.querySelector('[data-testid="finding-connector"] path')).toBeNull();
		const stack = document.createElement('div');
		stack.setAttribute('data-testid', 'hybrid-stack');
		const cards = document.createElement('div');
		cards.setAttribute('data-testid', 'copilot-cards');
		document.body.append(stack, cards);
		const pad = document.createElement('span');
		pad.setAttribute('data-finding-mark', 'u1');
		Object.assign(pad.style, { position: 'fixed', left: '20px', top: '200px', width: '16px', height: '16px' });
		const card = document.createElement('div');
		card.setAttribute('data-finding-card', 'u1');
		Object.assign(card.style, { position: 'fixed', left: '200px', top: '80px', width: '150px', height: '40px' });
		stack.append(pad);
		cards.append(card);
		try {
			await expect.poll(() => document.querySelector('[data-testid="finding-connector"] path')?.getAttribute('d') ?? '').toMatch(/^M 36 208 C /);
		} finally { stack.remove(); cards.remove(); }
	});
});
