// The faint connector between a finding's marker in the scratchpad and its rail group (pure geometry). SYNTHETIC.
import { describe, expect, it } from 'vitest';
import { connectorPath, endpointVisible } from './connector';

const vp = { width: 1200, height: 800 };
const rect = (left: number, top: number, w = 20, h = 20) => ({ left, top, right: left + w, bottom: top + h, width: w, height: h });

describe('connectorPath', () => {
	const marker = rect(100, 300); // the scratchpad marker, right edge x = 120, middle y = 310
	const card = rect(800, 100, 380, 30); // the guideline card header, left edge x = 800, middle y = 115
	it('a gentle cubic curve from the marker right edge to the card left edge when both are visible', () => {
		const d = connectorPath(card, marker, vp)!;
		expect(d).toMatch(/^M [\d.]+ [\d.]+ C /);
		const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
		expect([nums[0], nums[1]]).toEqual([120, 310]);
		expect([nums[6], nums[7]]).toEqual([800, 115]);
	});
	it('stays between the two panes: every x lies from the marker right edge to the card left edge', () => {
		const nums = connectorPath(card, marker, vp)!.match(/-?\d+(\.\d+)?/g)!.map(Number);
		const xs = [nums[0], nums[2], nums[4], nums[6]];
		for (const x of xs) {
			expect(x).toBeGreaterThanOrEqual(marker.right);
			expect(x).toBeLessThanOrEqual(card.left);
		}
	});
	it('nothing when either end is outside the viewport, or the card is not to the right of the marker', () => {
		expect(connectorPath(rect(800, 900), marker, vp)).toBeNull();
		expect(connectorPath(card, rect(100, -60), vp)).toBeNull();
		expect(connectorPath(rect(1300, 100), marker, vp)).toBeNull();
		expect(connectorPath(card, rect(-50, 300), vp)).toBeNull();
		expect(connectorPath(rect(50, 100), marker, vp)).toBeNull();
	});
});

describe('visible means visible in its own pane', () => {
	const pane = rect(0, 100, 600, 400); // the scratchpad pane: y 100..500
	it('an endpoint counts only when it lies inside the viewport and inside its scroller', () => {
		expect(endpointVisible(rect(100, 300), pane, vp)).toBe(true);
		expect(endpointVisible(rect(100, 300), null, vp)).toBe(true);
		expect(endpointVisible(rect(100, 50), pane, vp)).toBe(false); // scrolled above the pane, still on screen
		expect(endpointVisible(rect(100, 490), pane, vp)).toBe(false); // half clipped at the pane's bottom
		expect(endpointVisible(rect(100, 300), pane, { width: 50, height: 800 })).toBe(false);
	});
	it('a marker scrolled above its pane draws nothing; a card clipped by the rail list draws nothing', () => {
		const marker = rect(100, 300);
		const card = rect(800, 150, 380, 30);
		expect(connectorPath(card, marker, vp, { marker: pane, card: rect(700, 100, 480, 400) })).not.toBeNull();
		expect(connectorPath(card, rect(100, 20), vp, { marker: pane })).toBeNull();
		expect(connectorPath(card, marker, vp, { card: rect(700, 200, 480, 300) })).toBeNull();
	});
});
