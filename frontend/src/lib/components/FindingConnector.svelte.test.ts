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
			await expect.poll(() => document.querySelector('[data-testid="finding-connector"] path')?.getAttribute('d') ?? '').toMatch(/^M 200 100 C /);
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
});
