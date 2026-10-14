// The confirm gate (spec §7.12 item 5): which guideline cards block Confirm, and what clears them. SYNTHETIC fixtures.
import { describe, expect, it } from 'vitest';
import { card, draft, outcome, preview, result } from './cards/fixtures';
import { closedView, type CardView } from './cards/view';
import { significant, unresolved, verdictKey, type ConclusionCategory } from './gate';
import type { CopilotState } from './session';
import { cardRef } from './state';
import type { Card, Preview } from './types';

const finding = { id: 'u1', unitId: 1, text: 'Solid pulmonary nodule', region: 'LUNGS' };
const workup = (headline = 'Consider PET-CT') => preview({ proposal: outcome({ headline, action: 'PET-CT', category: 'workup' }) });
const fine = preview({ proposal: outcome({ headline: 'No follow-up', action: 'No further imaging', category: 'none' }) });
const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015', finding: finding.text });
const view = (p: Preview | null, over: Partial<CardView> = {}): CardView => ({ ...closedView, result: p ? result(bts, p) : null, ...over });
function st(cards: Card[], views: Record<string, CardView>): CopilotState {
	return { on: true, groups: [{ finding, cards }], views, matching: false, matchFailed: false, otherState: 'idle', seen: {}, concl: {} };
}
const one = (p: Preview | null, over: Partial<CardView> = {}, c: Card = bts) => st([c], { [cardRef(c)]: view(p, over) });
const KEY = cardRef(bts);

describe('significant', () => {
	it('true for a workup, refer or surveillance verdict, an outcome-changing question, or a scope doubt', () => {
		expect(significant(workup())).toBe(true);
		expect(significant(preview({ proposal: outcome({ category: 'refer' }) }))).toBe(true);
		expect(significant(preview({ proposal: null, most_likely: { headline: 'CT surveillance', category: 'surveillance' } }))).toBe(true);
		expect(significant(preview({ proposal: null, draft: [draft({ input: 'g', label: 'Growth', state: 'asked', needed: true })] }))).toBe(true);
		expect(significant(preview({ ...fine, scope_doubt: ['cancer'] }))).toBe(true);
	});

	it('false for a none verdict, questions that cannot change it, degraded, failed or loading, does_not_apply, tier 2, off-modality', () => {
		expect(significant(fine)).toBe(false);
		expect(significant(preview({ ...fine, draft: [draft({ input: 'a', label: 'Age', state: 'asked', needed: false })] }))).toBe(false);
		expect(significant(preview({ ...workup(), degraded: true }))).toBe(false);
		expect(significant(null)).toBe(false);
		expect(significant(undefined)).toBe(false);
		expect(significant(preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ category: 'workup' }) }))).toBe(false);
		expect(significant(workup(), card({ reference: true }))).toBe(false);
		expect(significant(workup(), card({ needs_modality: 'US' }))).toBe(false);
		// through the state: a loading or failed card has no verdict, so it is not unresolved
		expect(unresolved(one(workup(), { loading: true }), {}, {})).toEqual([]);
		expect(unresolved(one(workup(), { error: 'timeout' }), {}, {})).toEqual([]);
		expect(unresolved(one(null), {}, {})).toEqual([]);
		expect(unresolved(one(workup(), {}, card({ ...bts, reference: true })), {}, {})).toEqual([]);
	});
});

describe('unresolved', () => {
	it('a significant card with no conclusion check is unresolved, named, keyed by its card ref', () => {
		expect(unresolved(one(workup()), {}, {})).toEqual([{ key: KEY, card: KEY, name: 'BTS 2015' }]);
	});

	it('clears when the conclusion recommends at least as much (none 0 < surveillance 1 < workup 2 < refer 3)', () => {
		const s = one(workup());
		const at = (c: ConclusionCategory | null) => unresolved(s, {}, { [KEY]: c });
		expect(at('workup')).toEqual([]);
		expect(at('refer')).toEqual([]); // more caution is fine
		expect(at('surveillance')).toEqual([{ key: KEY, card: KEY, name: 'BTS 2015', reason: 'Conclusion gives follow-up imaging; BTS 2015 says further tests' }]);
		expect(at('none')[0].reason).toBe('Conclusion gives no recommendation; BTS 2015 says further tests');
		expect(at(null)).toEqual([{ key: KEY, card: KEY, name: 'BTS 2015' }]); // the check failed: nothing cleared, no reason
		const refer = one(preview({ proposal: outcome({ category: 'refer' }) }));
		expect(unresolved(refer, {}, { [KEY]: 'workup' })[0].reason).toBe('Conclusion gives further tests; BTS 2015 says referral');
		const surv = one(preview({ proposal: outcome({ category: 'surveillance' }) }));
		expect(unresolved(surv, {}, { [KEY]: 'surveillance' })).toEqual([]);
	});

	it('a card with no verdict category (an open question or a scope doubt) clears on any recommendation but none', () => {
		const s = one(preview({ proposal: null, draft: [draft({ input: 'g', label: 'Growth', state: 'asked', needed: true })] }));
		expect(unresolved(s, {}, { [KEY]: 'surveillance' })).toEqual([]);
		expect(unresolved(s, {}, { [KEY]: 'none' })).toHaveLength(1);
		expect(unresolved(s, {}, { [KEY]: 'none' })[0].reason).toBeUndefined();
	});

	it('gate: seen clears until the verdict changes', () => {
		const p = workup();
		expect(unresolved(one(p), { [KEY]: verdictKey(p) }, {})).toEqual([]);
		expect(unresolved(one(workup('Consider tissue sampling')), { [KEY]: verdictKey(p) }, {})).toHaveLength(1); // a changed verdict re-opens it
	});

	it('gate: failed card never blocks', () => {
		// a failed preview (request error, or an /open error in the body) has no verdict
		expect(unresolved(one(workup(), { error: 'timeout' }), {}, { [KEY]: null })).toEqual([]);
		const failedBody = st([bts], { [KEY]: { ...closedView, result: { ...result(bts, null), error: 'unavailable' } } });
		expect(unresolved(failedBody, {}, {})).toEqual([]);
		// the conclusion check failed on a significant card: it stays, but Seen always clears it
		const p = workup();
		expect(unresolved(one(p), {}, { [KEY]: null })).toHaveLength(1);
		expect(unresolved(one(p), { [KEY]: verdictKey(p) }, { [KEY]: null })).toEqual([]);
	});

	it('sibling columns are judged one by one, keyed `<cardRef>#<pack key>`, named by their column title', () => {
		const fl = card({ key: 'fleischner-pulmonary-nodule', name: 'Fleischner 2017', finding: finding.text, siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const ref = cardRef(fl);
		const cols = {
			'fleischner-pulmonary-nodule': { loading: false, error: null, result: result(fl, fine) },
			'bts-pulmonary-nodule': { loading: false, error: null, result: result(bts, workup()) }
		};
		const s = st([fl], { [ref]: { ...closedView, columns: cols } });
		expect(unresolved(s, {}, {})).toEqual([{ key: `${ref}#bts-pulmonary-nodule`, card: ref, name: 'BTS 2015' }]);
	});

	it('only cards that carry "Seen" can block: never a quiet exam line, a TNM, reference or off-modality card', () => {
		const tnm = card({ key: 'tnm-lung', name: 'TNM lung', finding: finding.text });
		expect(unresolved(one(workup(), {}, tnm), {}, {})).toEqual([]);
		const exam = card({ key: 'exam-pack', name: 'Exam pack', finding_id: 'exam', finding: 'whole dictation' });
		const s = { ...st([], {}), groups: [{ finding: null, cards: [exam] }], views: { [cardRef(exam)]: view(preview({ proposal: outcome({ category: 'workup', normal: false }) })) } };
		// a quiet exam line (a reached outcome while the backend sends no `normal`) carries no Seen: never blocks
		expect(unresolved({ ...s, views: { [cardRef(exam)]: view(workup()) } }, {}, {})).toEqual([]);
		expect(unresolved(s, {}, {}).map((u) => u.name)).toEqual(['Exam pack']);
	});
});

describe('scope doubt leads the card (ruling)', () => {
	it('significant stays true, so Confirm blocks until the value is set', () => {
		const p = preview({
			proposal: null,
			draft_outcome: outcome({ headline: 'Consider 3-month CT', action: 'CT at 3 months', category: 'workup' }),
			draft: [draft({ input: 'prior_growth', label: 'Earlier imaging shows this nodule has grown', state: 'prefilled', value: 'Yes' })],
			scope_doubt: ['prior_growth']
		});
		expect(significant(p)).toBe(true);
		expect(unresolved(one(p), {}, {})).toHaveLength(1);
	});
});
