import { describe, expect, it } from 'vitest';
import type { ReviewItem } from '../types';
import { chipActions, chipType, type ChipTarget } from './chip';

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

describe('chip type', () => {
	it('by mark class or widget kind', () => {
		expect(chipType({ on: 'mark', mark: 'rv-check', kind: 'check' })).toBe('check');
		expect(chipType({ on: 'mark', mark: 'rv-normal', kind: 'assumed_normal' })).toBe('normal');
		expect(chipType(action, item({ kind: 'contradicted' }))).toBe('action');
		expect(chipType({ on: 'widget', kind: 'option' })).toBe('option');
		expect(chipType({ on: 'widget', kind: 'excluded' })).toBeNull();
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
