// The faint connector between a finding's marker in the scratchpad and its rail group (pure geometry). SYNTHETIC.
import { describe, expect, it } from 'vitest';
import { connectorPath } from './connector';

const vp = { width: 1200, height: 800 };
const rect = (left: number, top: number, w = 20, h = 20) => ({ left, top, right: left + w, bottom: top + h, width: w, height: h });

describe('connectorPath', () => {
	it('a gentle cubic curve from the rail group edge to the scratchpad marker when both are visible', () => {
		const marker = rect(100, 300);
		const group = rect(800, 100, 380, 30);
		const d = connectorPath(group, marker, vp)!;
		expect(d).toMatch(/^M [\d.]+ [\d.]+ C /);
		const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
		expect([nums[0], nums[1]]).toEqual([800, 115]); // the group's left edge, vertical middle of its header
		expect([nums[6], nums[7]]).toEqual([120, 310]); // the marker's right edge, vertical middle
	});
	it('nothing when either end is outside the viewport', () => {
		expect(connectorPath(rect(800, 900), rect(100, 300), vp)).toBeNull();
		expect(connectorPath(rect(800, 100), rect(100, -60), vp)).toBeNull();
		expect(connectorPath(rect(1300, 100), rect(100, 300), vp)).toBeNull();
		expect(connectorPath(rect(800, 100), rect(-50, 300), vp)).toBeNull();
	});
});
