import { describe, expect, it } from 'vitest';
import {
	applyAsrFixes,
	asrFields,
	flagRanges,
	commandInsert,
	committedEditChanges,
	isUnfinishedCorrection,
	jevContext,
	splitSpan,
	openStatement,
	separatorFor,
	substituteLast,
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
import { keytermQuery, keytermCaseKey, deletePrevious } from './decisionFirst';

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

describe('cleaned text for polish', () => {
	it('replaces the last occurrence of the raw final in the session transcript', () => {
		expect(substituteLast('a L3/4, colon, b. L3/4, colon, mild', 'L3/4, colon, mild', 'L3/4: mild')).toBe(
			'a L3/4, colon, b. L3/4: mild'
		);
	});
	it('leaves the transcript alone when the final is not in it (window moved on)', () => {
		expect(substituteLast('abc', 'zzz', 'y')).toBe('abc');
	});
	it('a text that starts with a line break attaches directly', () => {
		expect(separatorFor('No effusion.', '\nThe heart', false)).toBe('');
	});
});

describe('openStatement', () => {
	it('is the unfinished sentence after the last full stop', () => {
		expect(openStatement('Normal marrow signal. L4/5 there is a broad based disc bulge causing')).toBe(
			'L4/5 there is a broad based disc bulge causing'
		);
	});
	it('is empty when the text ends a sentence', () => {
		expect(openStatement('No effusion.')).toBe('');
		expect(openStatement('Is this new?')).toBe('');
		expect(openStatement('Conclusion:')).toBe('');
		expect(openStatement('No effusion.\n\n')).toBe('');
	});
	it('stops at a line break, not just a full stop', () => {
		expect(openStatement('No effusion.\n\nL3/4 mild desiccation with')).toBe('L3/4 mild desiccation with');
	});
	it('a trailing line or paragraph break closes the statement, even without a full stop', () => {
		expect(openStatement('no contact on the exiting L5 nerve root\n\n')).toBe('');
		expect(openStatement('no contact on the exiting L5 nerve root\n')).toBe('');
	});
	it('does not split on a decimal point', () => {
		expect(openStatement('The lesion measures 4.5')).toBe('The lesion measures 4.5');
	});
	it('is the whole text when nothing has ended yet', () => {
		expect(openStatement('There are five lumbar type')).toBe('There are five lumbar type');
		expect(openStatement('')).toBe('');
	});
});

describe('splitSpan', () => {
	it('takes the last two sentences as the span and earlier text as context', () => {
		const solid = 'The lungs are clear. No effusion. The heart is normal. There is a';
		const s = splitSpan(solid);
		expect(s.span).toBe('The heart is normal. There is a');
		expect(s.context).toBe('The lungs are clear. No effusion.');
		expect(solid.slice(s.spanFrom)).toBe(s.span);
	});
	it('never reaches back past a line break', () => {
		const solid = 'Findings above.\n\nL3/4 There is mild desiccation';
		const s = splitSpan(solid);
		expect(s.span).toBe('L3/4 There is mild desiccation');
		expect(s.context).toBe('Findings above.');
	});
	it('does not split on a decimal point', () => {
		expect(splitSpan('A 4.5 mm nodule. It is stable').span).toBe('A 4.5 mm nodule. It is stable');
	});
	it('is empty after a paragraph break, with the previous text as context', () => {
		const s = splitSpan('No effusion.\n\n');
		expect(s.span).toBe('');
		expect(s.spanFrom).toBe('No effusion.\n\n'.length);
		expect(s.context).toBe('No effusion.');
	});
	it('keeps at most 600 characters of context', () => {
		const long = 'Word word word. '.repeat(100) + 'A. B.';
		expect(splitSpan(long).context.length).toBeLessThanOrEqual(600);
	});
});

describe('committedEditChanges', () => {
	it('replaces an original found exactly once before the span', () => {
		const doc = 'The appendix measures 11 mm. No gas. The rest.';
		expect(committedEditChanges(doc, 36, [{ original: 'measures 11 mm', corrected: 'measures 12 mm' }])).toEqual([
			{ from: 13, to: 27, insert: 'measures 12 mm' }
		]);
	});
	it('skips an original that is missing, repeated, or inside the span', () => {
		const doc = 'No gas. No gas. Tail.';
		expect(committedEditChanges(doc, 16, [{ original: 'No gas.', corrected: 'x' }])).toEqual([]);
		expect(committedEditChanges(doc, 16, [{ original: 'absent', corrected: 'x' }])).toEqual([]);
		expect(committedEditChanges(doc, 5, [{ original: 'Tail.', corrected: 'x' }])).toEqual([]);
	});
});

describe('committedEditChanges, overlaps', () => {
	it('keeps the first of two overlapping edits and returns them sorted', () => {
		const doc = 'Left kidney 9 mm cyst. Spleen 11 cm. Tail.';
		expect(
			committedEditChanges(doc, 36, [
				{ original: 'Spleen 11 cm', corrected: 'Spleen 13 cm' },
				{ original: 'kidney 9 mm', corrected: 'kidney 10 mm' },
				{ original: '9 mm cyst', corrected: '9 mm lesion' }
			])
		).toEqual([
			{ from: 5, to: 16, insert: 'kidney 10 mm' },
			{ from: 23, to: 35, insert: 'Spleen 13 cm' }
		]);
	});
});

describe('jevContext', () => {
	// solid text, then two faded finals still queued for polish, then this final (faded)
	const doc = 'The main pulmonary artery is not dilated. Measuring 27 millimetres. The right ventricle meshes';
	const own = { from: doc.indexOf(' The right'), to: doc.length };
	it('includes earlier faded words, up to where this final starts', () => {
		expect(jevContext(doc, own, 'The right ventricle meshes', 41)).toBe(
			'The main pulmonary artery is not dilated. Measuring 27 millimetres.'
		);
	});
	it('falls back to the solid text when this final has been overwritten', () => {
		expect(jevContext(doc, { from: 10, to: 10 }, 'The right ventricle meshes', 41)).toBe(
			'The main pulmonary artery is not dilated.'
		);
		expect(jevContext(doc, null, 'The right ventricle meshes', 41)).toBe('The main pulmonary artery is not dilated.');
	});
	it('falls back when the tracked range no longer holds this final', () => {
		expect(jevContext(doc, { from: 0, to: 8 }, 'The right ventricle meshes', 41)).toBe(
			'The main pulmonary artery is not dilated.'
		);
	});
});

describe('isUnfinishedCorrection', () => {
	it('holds a correction whose corrected statement has not finished', () => {
		expect(isUnfinishedCorrection('Correction. The nodule is in the')).toBe(true);
		expect(isUnfinishedCorrection('Sorry. Three enlarged')).toBe(true);
		expect(isUnfinishedCorrection('Correction.')).toBe(true); // a bare cue: the correction follows
		expect(isUnfinishedCorrection('Actually, make that')).toBe(true);
	});
	it('does not hold a finished correction, even with an unfinished finding after it', () => {
		expect(isUnfinishedCorrection('Actually, make that 7 cm.')).toBe(false);
		expect(isUnfinishedCorrection("Sorry, that's the right kidney.")).toBe(false);
		expect(isUnfinishedCorrection('Correction. The lesion measures 18 mm. There is a 6 mm nodule in the left')).toBe(false);
		expect(isUnfinishedCorrection('Actually make that 7 cm.\n\n')).toBe(false);
	});
	it('ignores text with no correction cue', () => {
		expect(isUnfinishedCorrection('There is a small left pleural')).toBe(false);
		expect(isUnfinishedCorrection('No pneumothorax')).toBe(false);
	});
});

describe('word-sense fixes and flags in written text', () => {
	it('applies a fix to a whole word, keeping the capital', () => {
		expect(applyAsrFixes('Renal glands are normal. The renal glands too.', [{ heard: 'renal', replacement: 'adrenal' }])).toBe(
			'Adrenal glands are normal. The adrenal glands too.'
		);
	});
	it('never touches part of a longer word', () => {
		expect(applyAsrFixes('The adrenal glands are normal.', [{ heard: 'renal', replacement: 'adrenal' }])).toBe(
			'The adrenal glands are normal.'
		);
	});
	it('does nothing when the heard words are no longer there (the polish changed them)', () => {
		expect(applyAsrFixes('No paraspinal abnormality.', [{ heard: 'varospinal', replacement: 'paraspinal' }])).toBe(
			'No paraspinal abnormality.'
		);
	});
	it('finds the last whole-word occurrence of each flagged word', () => {
		expect(flagRanges('the meshes and the meshes', [{ word: 'meshes' }])).toEqual([{ from: 19, to: 25 }]);
		expect(flagRanges('the thyroid gland', [{ word: 'roid' }])).toEqual([]);
	});
});

describe('keytermQuery', () => {
	it('encodes each term as a repeated kt parameter', () => {
		expect(keytermQuery(['adrenal glands', "McConnell's sign"])).toBe("&kt=adrenal%20glands&kt=McConnell's%20sign");
	});
	it('is empty with no terms (the backend then uses the core list)', () => {
		expect(keytermQuery([])).toBe('');
		expect(keytermQuery(null)).toBe('');
	});
	it('caps at 50 terms', () => {
		const q = keytermQuery(Array.from({ length: 70 }, (_, i) => `t${i}`));
		expect(q.split('&kt=').length - 1).toBe(50);
	});
});

describe('keytermCaseKey', () => {
	it('changes when the scan, history or checklist changes', () => {
		const a = keytermCaseKey('CT chest', 'cough', ['LUNGS']);
		expect(keytermCaseKey('CT chest', 'cough', ['LUNGS'])).toBe(a);
		expect(keytermCaseKey('CT chest', 'cough', ['LUNGS', 'PLEURA'])).not.toBe(a);
		expect(keytermCaseKey('CT head', 'cough', ['LUNGS'])).not.toBe(a);
	});
});

describe('deletePrevious ("scratch that")', () => {
	// doc: "The liver is normal. There is a small hiatus hernia. scratch that"
	//       0                   20                               52 53
	const last = { from: 20, to: 52, before: '', intact: true, route: 'fast_append' as const };
	const pend = { from: 52, to: 65 };
	it("removes the previous utterance's text and the command's own faded text", () => {
		expect(deletePrevious(last, pend, false)).toEqual({
			edits: [{ from: 20, to: 52, insert: '' }],
			reason: null
		});
	});
	it('restores what a polish replaced', () => {
		const p = { ...last, route: 'polish' as const, before: ' There is no hernia.' };
		expect(deletePrevious(p, pend, false).edits).toEqual([{ from: 20, to: 52, insert: ' There is no hernia.' }]);
	});
	it('falls back to polish when the previous text was touched, is a command, or a polish is in flight', () => {
		expect(deletePrevious(null, pend, false).reason).toBe('delete_nothing_intact');
		expect(deletePrevious({ ...last, intact: false }, pend, false).reason).toBe('delete_nothing_intact');
		expect(deletePrevious({ ...last, route: 'command' }, pend, false).reason).toBe('delete_after_command');
		expect(deletePrevious(last, pend, true).reason).toBe('delete_polish_in_flight');
		expect(deletePrevious({ ...last, to: 60 }, pend, false).reason).toBe('delete_nothing_intact');
	});
});
