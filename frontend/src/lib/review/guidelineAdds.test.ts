import { describe, expect, it } from 'vitest';
import type { GuidelineEntry } from '$lib/guidelines/types';
import type { ReviewItem } from './types';
import { isAddable, itemForCard, itemForClassification } from './guidelineAdds';

// SYNTHETIC items only.
function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id' | 'kind'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'additions',
		cls: 'minor',
		detectors: [],
		label: '',
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		edit: { mode: 'insert', replace: 'Text.', section: 'FINDINGS' },
		...over
	};
}
const CARD: GuidelineEntry = { finding_number: 2, finding: 'Adrenal nodule' };
const CLS = { system: 'ACR', grade: 'Benign' };

describe('guidelineAdds', () => {
	it('addable: open, not suppressed, additions insert with text', () => {
		expect(isAddable(item({ id: 'a', kind: 'grade' }))).toBe(true);
		expect(isAddable(item({ id: 'b', kind: 'grade', status: 'applied' }))).toBe(false);
		expect(isAddable(item({ id: 'c', kind: 'grade', cls: 'suppress' }))).toBe(false);
		expect(isAddable(item({ id: 'd', kind: 'grade', lane: 'accuracy' }))).toBe(false);
		expect(isAddable(item({ id: 'e', kind: 'grade', edit: { mode: 'replace', find: 'x', replace: 'y' } }))).toBe(false);
	});

	it('card: by citation.card, follow-up before grade; finding text when unnumbered', () => {
		const items = [
			item({ id: 'g', kind: 'grade', citation: { card: 2 } }),
			item({ id: 'f', kind: 'follow_up', citation: { card: 2 } }),
			item({ id: 'x', kind: 'follow_up', citation: { card: 3 } })
		];
		expect(itemForCard(items, CARD)?.id).toBe('f');
		expect(itemForCard([item({ id: 'n', kind: 'grade', evidence: { finding: 'adrenal  nodule' } })], { finding: 'Adrenal nodule' })?.id).toBe('n');
		expect(itemForCard(items, { finding_number: 9, finding: 'Other' })).toBeNull();
	});

	it('classification: same system and grade, and the same card when numbered', () => {
		const ok = item({ id: 'g', kind: 'grade', citation: { card: 2 }, evidence: { system: 'ACR', grade: 'benign' } });
		const other = item({ id: 'h', kind: 'grade', citation: { card: 5 }, evidence: { system: 'ACR', grade: 'Benign' } });
		expect(itemForClassification([other, ok], CARD, CLS)?.id).toBe('g');
		expect(itemForClassification([other], CARD, CLS)).toBeNull();
		expect(itemForClassification([ok], CARD, { system: 'ACR', grade: 'Indeterminate' })).toBeNull();
	});
});
