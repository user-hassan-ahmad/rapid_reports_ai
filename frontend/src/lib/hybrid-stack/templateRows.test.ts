import { describe, expect, it } from 'vitest';
import { chooseTemplate, templateKey, unmetTemplate, withChosen, withRequired } from './templateRows';
import type { StackItem } from './types';

const t = (id: string, extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'template', region: 'Liver', question: 'Septation?', why: '', sentences: ['The cyst is septated.', 'No septation.'],
	answered: false, yes: 'The cyst is septated.', no: 'No septation.', ...extra
});

describe('template rows', () => {
	it('Yes and No keep only the template sentence chosen', () => {
		expect(chooseTemplate(t('a'), 'yes').sentences).toEqual(['The cyst is septated.']);
		expect(chooseTemplate(t('a'), 'no').sentences).toEqual(['No septation.']);
	});
	it('the view shows an answered template row with its chosen sentence; other rows are untouched', () => {
		const finding: StackItem = { ...t('f'), kind: 'finding' };
		const out = withChosen([t('a'), finding], { a: chooseTemplate(t('a'), 'no'), f: { ...finding, sentences: ['x.'] } });
		expect(out[0].sentences).toEqual(['No septation.']);
		expect(out[1]).toBe(finding);
	});
	it('required statements are offered first, without repeats', () => {
		expect(withRequired({ Liver: ['The liver is normal.', 'No septation.'], Spleen: ['Normal spleen.'] }, { Liver: ['No septation'], Kidneys: ['No calculus.'] }))
			.toEqual({ Liver: ['No septation', 'The liver is normal.'], Kidneys: ['No calculus.'], Spleen: ['Normal spleen.'] });
	});
	it('answers to template rows a full review no longer returns are unmet; other rows are not', () => {
		const answered = { a: t('a'), b: t('b'), f: { ...t('f'), kind: 'finding' as const } };
		expect(unmetTemplate(answered, { items: [t('a')], capped: [] })).toEqual(['b']);
		expect(unmetTemplate(answered, { items: [], capped: [t('b')] })).toEqual(['a']);
	});
	it('the gate key changes with a chosen sentence and with the required statements', () => {
		const k = templateKey({ a: chooseTemplate(t('a'), 'yes') }, {});
		expect(templateKey({ a: chooseTemplate(t('a'), 'no') }, {})).not.toBe(k);
		expect(templateKey({ a: chooseTemplate(t('a'), 'yes') }, { Liver: ['No free fluid.'] })).not.toBe(k);
		expect(templateKey({ a: chooseTemplate(t('a'), 'yes'), f: { ...t('f'), kind: 'finding' } }, {})).toBe(k);
	});
});
