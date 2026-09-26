import { describe, expect, it } from 'vitest';
import {
	asrFields,
	commandInsert,
	separatorFor,
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
	it('starts an empty scratchpad with nothing', () => expect(joinSeparator('')).toBe(''));
	it('continues the text with a space after a finished sentence', () =>
		expect(joinSeparator('No effusion.')).toBe(' '));
	it('continues an unfinished sentence with a space', () => expect(joinSeparator('there is a')).toBe(' '));
	it('adds nothing after a newline (a command started the new line)', () =>
		expect(joinSeparator('No effusion.\n')).toBe(''));
	it('adds nothing after trailing whitespace', () => expect(joinSeparator('No effusion. ')).toBe(''));
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
	it('matches the same line said again, extended', () => {
		expect(isRedictation(tokenSet('There is no free fluid.'), tokenSet('There is no free fluid in the pelvis.'))).toBe(true);
	});
	it('does not match the other side (a word of the earlier line is missing)', () => {
		expect(isRedictation(tokenSet('no left pleural effusion'), tokenSet('no right pleural effusion'))).toBe(false);
	});
	it('does not match on containment of a short line', () => {
		expect(isRedictation(tokenSet('no fracture'), tokenSet('no fracture of the left femur is seen today'))).toBe(false);
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

describe('Deepgram confidence in the export', () => {
	it('carries the numbers through, and nothing else', () => {
		const r = { ...rec('a', 'polish', 250), asr_conf: 0.91, asr_min_conf: 0.61, asr_word_confs: [0.99, 0.61] };
		const out = buildSessionExport([r], [], { scanType: '', startedAt: 0, exportedAt: 1 });
		expect(out.decisions[0].asr_min_conf).toBe(0.61);
		expect(out.decisions[0].asr_word_confs).toEqual([0.99, 0.61]);
	});
	it('picks only the confidence fields off a websocket message', () => {
		expect(asrFields({ transcript: 'x', is_final: true, asr_conf: 0.9, asr_min_conf: 0.6, asr_word_confs: [0.6] })).toEqual({
			asr_conf: 0.9, asr_min_conf: 0.6, asr_word_confs: [0.6]
		});
		expect(asrFields({ transcript: 'x' })).toEqual({ asr_conf: null, asr_min_conf: null, asr_word_confs: null });
	});
});

describe('commandInsert', () => {
	it('adds a full stop to an unpunctuated line', () => expect(commandInsert('no effusion', '.')).toBe('.'));
	it('never doubles a full stop', () => expect(commandInsert('No effusion.', '.')).toBe(''));
	it('never starts an empty scratchpad with a command', () => expect(commandInsert('', '\n\n')).toBe(''));
	it('passes newlines through', () => expect(commandInsert('No effusion.', '\n')).toBe('\n'));
});

describe('separatorFor', () => {
	it('opens a paragraph for a disc level or heading', () => {
		expect(separatorFor('Normal marrow signal.', 'L3/4 mild desiccation', true)).toBe('\n\n');
		expect(separatorFor('Normal marrow signal.\n', 'L3/4', true)).toBe('\n');
		expect(separatorFor('Normal marrow signal.\n\n', 'L3/4', true)).toBe('');
		expect(separatorFor('', 'Conclusion:', true)).toBe('');
	});
	it('attaches leading punctuation to the text before it', () => {
		expect(separatorFor('L5/S1', ': left paracentral extrusion', false)).toBe('');
		expect(separatorFor('mild bulge', ', no stenosis', false)).toBe('');
	});
	it('otherwise continues the text', () => {
		expect(separatorFor('No effusion.', 'The heart is normal.', false)).toBe(' ');
	});
});
