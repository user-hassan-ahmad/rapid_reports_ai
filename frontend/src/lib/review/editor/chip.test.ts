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
		expect(chipType({ on: 'widget', kind: 'excluded' })).toBe('excluded');
	});
});

const commands = (t: ChipTarget, it?: ReviewItem) => chipActions(t, it).map((a) => a.command);
const icons = (t: ChipTarget, it?: ReviewItem) => chipActions(t, it).map((a) => a.icon);

describe('inline control actions by type', () => {
	it('the AI-generated layer (normal, check, synthesis) and info items are colour only: no control', () => {
		for (const mark of ['rv-check', 'rv-normal', 'rv-synth', 'rv-info'] as const)
			expect(commands({ on: 'mark', mark, kind: 'x' }), mark).toEqual([]);
	});

	it('a recommendation: ✓ keep / ✕ remove, no rail link', () => {
		const rec: ChipTarget = { on: 'mark', mark: 'rv-rec', kind: 'recommendation' };
		const it_ = item({ kind: 'recommendation', cls: 'minor', edit: { mode: 'remove', find: 'Follow up.' } });
		expect(commands(rec, it_)).toEqual(['keep', 'remove']);
		expect(icons(rec, it_)).toEqual(['✓', '✕']);
	});

	it('simple icons: ↺ restore, ↶ undo; options ✓ / ✕; never a "?"', () => {
		expect(commands({ on: 'widget', kind: 'option' })).toEqual(['apply', 'dismiss']);
		expect(icons({ on: 'widget', kind: 'removed' })).toEqual(['↺']);
		expect(commands({ on: 'mark', mark: 'rv-preapplied', kind: 'omission' })).toEqual(['undo']);
		expect(icons({ on: 'mark', mark: 'rv-preapplied', kind: 'omission' })).toEqual(['↶']);
		expect(commands({ on: 'widget', kind: 'excluded' })).toEqual(['undo']);
		expect(icons(action, item({ edit: { mode: 'replace', find: 'a', replace: 'b' } }))).not.toContain('?');
	});

	it('an action item: ✓ apply only with an edit (previewed), ✕ dismiss, and › to its rail card', () => {
		const withEdit = item({ edit: { mode: 'replace', find: 'a', replace: 'b' } });
		expect(commands(action, withEdit)).toEqual(['apply', 'dismiss', 'reveal']);
		expect(chipActions(action, withEdit)[0].preview).toBe(true);
		expect(commands(action, item({}))).toEqual(['dismiss', 'reveal']);
	});
});

describe('recommendation without a placeable edit', () => {
	it('keeps ✓ only (no ✕)', () => {
		const rec: ChipTarget = { on: 'mark', mark: 'rv-rec', kind: 'recommendation' };
		expect(commands(rec, item({ kind: 'recommendation', cls: 'minor', edit: null }))).toEqual(['keep']);
	});
});
