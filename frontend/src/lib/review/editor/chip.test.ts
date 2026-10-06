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
	it('simple icons only: ✓ / ✕, ↺ restore, ↶ undo; never a "?"', () => {
		const check: ChipTarget = { on: 'mark', mark: 'rv-check', kind: 'check' };
		expect(commands(check)).toEqual(['keep', 'remove']);
		expect(icons(check)).toEqual(['✓', '✕']);
		const normal: ChipTarget = { on: 'mark', mark: 'rv-normal', kind: 'assumed_normal' };
		expect(commands(normal)).toEqual(['keep', 'remove']);
		expect(commands({ on: 'widget', kind: 'option' })).toEqual(['apply', 'dismiss']);
		expect(icons({ on: 'widget', kind: 'option' })).toEqual(['✓', '✕']);
		expect(commands({ on: 'widget', kind: 'removed' })).toEqual(['restore']);
		expect(icons({ on: 'widget', kind: 'removed' })).toEqual(['↺']);
		expect(commands({ on: 'mark', mark: 'rv-preapplied', kind: 'omission' })).toEqual(['undo']);
		expect(icons({ on: 'mark', mark: 'rv-preapplied', kind: 'omission' })).toEqual(['↶']);
		expect(commands({ on: 'widget', kind: 'excluded' })).toEqual(['undo']);
		for (const t of [check, normal, action, { on: 'widget', kind: 'option' } as ChipTarget])
			expect(icons(t, item({ edit: { mode: 'replace', find: 'a', replace: 'b' } }))).not.toContain('?');
	});

	it('an action item: ✓ apply only with an edit (previewed), ✕ dismiss, and › to its rail card', () => {
		const withEdit = item({ edit: { mode: 'replace', find: 'a', replace: 'b' } });
		expect(commands(action, withEdit)).toEqual(['apply', 'dismiss', 'reveal']);
		expect(chipActions(action, withEdit)[0].preview).toBe(true);
		expect(commands(action, item({}))).toEqual(['dismiss', 'reveal']);
	});

	it('checks, normals, suggestions and minor items have no rail link', () => {
		const minor: ChipTarget = { on: 'mark', mark: 'rv-minor', kind: 'wording' };
		const m = item({ cls: 'minor', edit: { mode: 'replace', find: 'a', replace: 'b' } });
		expect(commands(minor, m)).toEqual(['apply', 'dismiss']);
		for (const t of [
			{ on: 'mark', mark: 'rv-check', kind: 'check' },
			{ on: 'mark', mark: 'rv-normal', kind: 'assumed_normal' },
			{ on: 'widget', kind: 'option' },
			{ on: 'mark', mark: 'rv-preapplied', kind: 'removed' }
		] as ChipTarget[])
			expect(commands(t)).not.toContain('reveal');
	});
});
