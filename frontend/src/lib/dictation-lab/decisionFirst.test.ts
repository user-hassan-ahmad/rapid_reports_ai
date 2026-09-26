import { describe, expect, it } from 'vitest';
import {
	buildSessionExport,
	changedRange,
	hash8,
	isRedictation,
	joinSeparator,
	summariseDecisions,
	tokenSet,
	type DecisionRecord,
	type OutcomeEvent
} from './decisionFirst';

describe('joinSeparator', () => {
	it('starts an empty scratchpad with nothing', () => expect(joinSeparator('', true)).toBe(''));
	it('joins the open line with a space', () => expect(joinSeparator('there is a', true)).toBe(' '));
	it('starts a new line when the last one is closed', () => expect(joinSeparator('No effusion.', false)).toBe('\n'));
	it('never doubles a newline already there', () => expect(joinSeparator('No effusion.\n', false)).toBe(''));
	it('does not glue onto a line that ended in a newline even if marked open', () =>
		expect(joinSeparator('Lungs\n', true)).toBe(''));
});

describe('changedRange', () => {
	it('finds the replaced span between two docs', () => {
		expect(changedRange('A.\nB.', 'A.\nB. C.')).toEqual({ from: 5, to: 8, before: '' });
		expect(changedRange('left kidney', 'right kidney')).toEqual({ from: 0, to: 4, before: 'lef' });
	});
	it('is empty when nothing changed', () => expect(changedRange('x', 'x')).toEqual({ from: 1, to: 1, before: '' }));
});

describe('re-dictation', () => {
	it('matches the same line said again, with small changes', () => {
		expect(isRedictation(tokenSet('no pleural effusion'), tokenSet('No left pleural effusion.'))).toBe(true);
	});
	it('does not match a different finding', () => {
		expect(isRedictation(tokenSet('no pleural effusion'), tokenSet('the liver is normal'))).toBe(false);
	});
	it('ignores one-word utterances', () => {
		expect(isRedictation(tokenSet('normal'), tokenSet('normal'))).toBe(false);
	});
});

describe('hash8', () => {
	it('is 8 hex chars and stable', () => {
		expect(hash8('abc')).toMatch(/^[0-9a-f]{8}$/);
		expect(hash8('abc')).toBe(hash8('abc'));
		expect(hash8('abc')).not.toBe(hash8('abd'));
	});
});

function rec(id: string, route: DecisionRecord['route'], latency: number | null, polish = route === 'polish'): DecisionRecord {
	return {
		id, seq: 0, at: 0, route, reason: 'r', qset: '2026-09-26.2', action: null, confidence: null,
		probabilities: null, is_correction: null, standalone: null, latency_ms: latency, roundtrip_ms: null,
		polish_called: polish, utterance_len: 10, utterance_hash: 'deadbeef', applied_len: 0,
		closes_line: false, line_closed_by: null, error: null
	};
}
const ev = (decision_id: string, kind: OutcomeEvent['kind'], route: OutcomeEvent['route']): OutcomeEvent => ({
	decision_id, kind, route, ms_since: 1000, at: 0
});

describe('summariseDecisions', () => {
	const decisions = [
		rec('a', 'fast_append', 240), rec('b', 'fast_append', 260), rec('c', 'polish', 300),
		rec('d', 'command', 250), rec('e', 'skip', null)
	];
	const outcomes = [ev('a', 'undo', 'fast_append'), ev('a', 'undo', 'fast_append'), ev('c', 'edit', 'polish')];
	const s = summariseDecisions(decisions, outcomes);
	it('counts polish calls against a polish-everything baseline', () => {
		expect(s.utterances).toBe(5);
		expect(s.polishCalls).toBe(1);
		expect(s.avoided).toBe(4);
	});
	it('counts each outcome once per decision, by route', () => {
		expect(s.byRoute.fast_append).toEqual({ n: 2, undo: 1, edit: 0, redictate: 0 });
		expect(s.byRoute.polish).toEqual({ n: 1, undo: 0, edit: 1, redictate: 0 });
		expect(s.byRoute.command).toEqual({ n: 1, undo: 0, edit: 0, redictate: 0 });
	});
	it('reports bundle latency over decisions that asked Jev', () => {
		expect(s.bundleP50).toBe(255);
		expect(s.bundleN).toBe(4);
	});
});

describe('buildSessionExport', () => {
	it('carries decisions and the outcome log, and no text fields', () => {
		const out = buildSessionExport([rec('a', 'fast_append', 240)], [ev('a', 'undo', 'fast_append')], {
			scanType: 'CT chest', startedAt: 1, exportedAt: 2
		});
		expect(out.schema).toBe('rr-lab-session/1');
		expect(out.decisions).toHaveLength(1);
		expect(out.outcomes).toHaveLength(1);
		expect(out.qsets).toEqual(['2026-09-26.2']);
		const json = JSON.stringify(out);
		expect(json).not.toMatch(/"(text|utterance|activeBefore|activeAfter)"/);
	});
});
