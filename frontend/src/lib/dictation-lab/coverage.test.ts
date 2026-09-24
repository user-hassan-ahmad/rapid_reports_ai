import { describe, expect, it } from 'vitest';
import { buildCoverageFixtureLine, coverageAgreement, pillState } from './coverage';

const T = { hi: 0.8, lo: 0.4 };

describe('pillState', () => {
	it('maps scores to three states', () => {
		expect(pillState(0.95, T)).toBe('covered');
		expect(pillState(0.8, T)).toBe('covered');
		expect(pillState(0.5, T)).toBe('partial');
		expect(pillState(0.4, T)).toBe('partial');
		expect(pillState(0.1, T)).toBe('absent');
		expect(pillState(undefined, T)).toBe('absent');
	});
});

describe('coverageAgreement', () => {
	it('compares jev at 0.5 with qwen membership per section', () => {
		const a = coverageAgreement(['L', 'P', 'M'], { L: 0.9, P: 0.2, M: 0.6 }, ['L', 'M']);
		expect(a).toEqual({ L: 'agree', P: 'agree', M: 'agree' });
		const b = coverageAgreement(['L', 'P'], { L: 0.9, P: 0.7 }, ['L']);
		expect(b.P).toBe('jev-only');
		const c = coverageAgreement(['L'], { L: 0.2 }, ['L']);
		expect(c.L).toBe('qwen-only');
	});
});

describe('buildCoverageFixtureLine', () => {
	it('emits one JSON line in fixture key order', () => {
		const line = buildCoverageFixtureLine(
			{ scratchpad: '- liver normal', checklist: ['LIVER', 'SPLEEN'], scanType: 'CT AP' },
			{ id: 'lab-01', expected_covered: ['LIVER'], rule: 'direct-subject', hard: false, note: 'n' }
		);
		expect(line.includes('\n')).toBe(false);
		expect(Object.keys(JSON.parse(line))).toEqual([
			'id', 'scan_type', 'checklist', 'scratchpad', 'expected_covered', 'rule', 'hard', 'note'
		]);
	});
});
