import { describe, expect, it } from 'vitest';
import type { ReviewItem } from '../types';
import { chipActions, chipRationale, chipType, condense, type ChipTarget } from './chip';

// SYNTHETIC items only.
function item(over: Partial<ReviewItem>): ReviewItem {
	return {
		id: 'x',
		key: 'x',
		report_id: 'r',
		run_id: 'run',
		lane: 'accuracy',
		detectors: [],
		kind: 'note',
		cls: 'action',
		label: '',
		reason: '',
		status: 'open',
		history: [],
		engine_version: 't',
		...over
	};
}
const action: ChipTarget = { on: 'mark', mark: 'rv-action', kind: 'x' };

describe('chip rationale (built by code from the item)', () => {
	it('condenses to six words', () => {
		expect(condense('one two three four five six seven.')).toBe('one two three four five six…');
		expect(condense('  short   phrase. ')).toBe('short phrase');
	});

	it('check: given the dictated pointer, condensed', () => {
		const t: ChipTarget = { on: 'mark', mark: 'rv-check', kind: 'check', pointer: 'a b c d e f g h' };
		expect(chipRationale(t)).toBe('given “a b c d e f…”');
		expect(chipRationale({ ...t, reason: 'number' })).toBe('measurement not dictated');
		expect(chipType(t)).toBe('check');
	});

	it('action kinds: contradiction, unsupported, certainty, number', () => {
		expect(chipRationale(action, item({ kind: 'contradicted', source_line: 'no free fluid seen' }))).toBe(
			'contradicts “no free fluid seen”'
		);
		expect(chipRationale(action, item({ kind: 'unsupported' }))).toBe('not in your dictation');
		expect(
			chipRationale(action, item({ kind: 'overstated', evidence: { dictated: 'possible', report: 'definite' } }))
		).toBe('“possible” → “definite”');
		expect(chipRationale(action, item({ kind: 'measurement', evidence: { check_reason: 'number' } }))).toBe(
			'measurement not dictated'
		);
		expect(chipRationale(action, item({ kind: 'other', label: 'Measurement differs' }))).toBe('Measurement differs');
	});

	it('normal, removed, option, pre-applied', () => {
		expect(chipRationale({ on: 'mark', mark: 'rv-normal', kind: 'assumed_normal' })).toBe('assumed normal');
		expect(chipRationale({ on: 'widget', kind: 'removed', reason: 'contradicted' })).toBe('contradicts your dictation');
		expect(chipRationale({ on: 'widget', kind: 'removed', reason: 'number' })).toBe('measurement not dictated');
		expect(chipRationale({ on: 'widget', kind: 'option' })).toBe('suggested');
		expect(chipRationale({ on: 'mark', mark: 'rv-preapplied', kind: 'omission' })).toBe('added from your dictation');
	});
});

describe('chip actions by type', () => {
	it('action: apply only with an edit; reveal always last', () => {
		const withEdit = item({ edit: { mode: 'replace', find: 'a', replace: 'b' } });
		expect(chipActions(action, withEdit).map((a) => a.command)).toEqual(['apply', 'dismiss', 'reveal']);
		expect(chipActions(action, withEdit)[0].preview).toBe(true);
		expect(chipActions(action, item({})).map((a) => a.command)).toEqual(['dismiss', 'reveal']);
	});

	it('a pre-applied removal restores; excluded has no chip', () => {
		const t: ChipTarget = { on: 'mark', mark: 'rv-preapplied', kind: 'removed' };
		expect(chipActions(t).map((a) => a.command)).toEqual(['restore', 'reveal']);
		expect(chipType({ on: 'widget', kind: 'excluded' })).toBeNull();
	});
});
