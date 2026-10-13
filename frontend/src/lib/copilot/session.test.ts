// The Copilot session store (Task A6). SYNTHETIC rounds, a fake api with hand-resolved promises, fake timers.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { StackUnit } from '$lib/hybrid-stack/types';
import { CopilotError, CopilotOff } from './api';
import { card, preview, result } from './cards/fixtures';
import { CONTEXT_DEBOUNCE_MS, createCopilotSession, EXAM_REOPEN_MS, MATCH_BACKOFF_MS, type CopilotApi } from './session';
import { cardRef } from './state';
import type { Card, MatchBody, MatchResult, OpenBody, OpenResult } from './types';

const unit = (id: number, text: string, o: Partial<StackUnit> = {}): StackUnit => ({
	id,
	text,
	group: 'Lungs',
	structure: null,
	attach_to: null,
	parts: null,
	covers: [],
	abnormal: true,
	pinned: false,
	heading: false,
	...o
});
const dictation = (us: StackUnit[]) => us.map((u) => u.text).join(' ');

type Call<B, R> = { body: B; resolve: (r: R) => void; reject: (e: unknown) => void };
function fakeApi() {
	const calls = { match: [] as Call<MatchBody, MatchResult>[], other: [] as Call<MatchBody, MatchResult>[], open: [] as Call<OpenBody, OpenResult>[] };
	const pending =
		<B, R>(list: Call<B, R>[]) =>
		(body: B) =>
			new Promise<R>((resolve, reject) => list.push({ body, resolve, reject }));
	const api: CopilotApi = { match: pending(calls.match), matchOther: pending(calls.other), open: pending(calls.open) };
	return { api, calls };
}
const flush = () => vi.advanceTimersByTimeAsync(0);
const matched = (cards: Card[]): MatchResult => ({ cards, ms: 5 });

const A = 'a 6 mm solid nodule';
const B = 'a 2 cm cyst';
const nodule = card({ finding_id: 'u1', finding: A });

let api: ReturnType<typeof fakeApi>;
let s: ReturnType<typeof createCopilotSession>;
beforeEach(() => {
	vi.useFakeTimers();
	api = fakeApi();
	s = createCopilotSession(api.api);
	s.setContext({ scanType: 'CT chest', history: 'cough' });
});
afterEach(() => {
	s.destroy();
	vi.useRealTimers();
});
const state = () => get(s.state);

/** Round 1 places u1 still growing (no stable finding: the call carries only the dictation, for exam cards);
 *  round 2 repeats it, so it is stable and matched. Resolves both with `cards`. */
async function matchA(cards: Card[] = [nodule]) {
	const us = [unit(1, A)];
	s.round(us, true, dictation(us));
	api.calls.match[0].resolve(matched([]));
	await flush();
	s.round(us, true, dictation(us));
	api.calls.match[1].resolve(matched(cards));
	await flush();
}

describe('session: matching', () => {
	it('a growing last unit makes no call for it until it is stable', async () => {
		s.round([unit(1, 'a 6 mm')], true, 'a 6 mm');
		expect(api.calls.match).toHaveLength(1);
		expect(api.calls.match[0].body.findings).toEqual([]); // exam-only first call
		api.calls.match[0].resolve(matched([]));
		await flush();
		s.round([unit(1, 'a 6 mm solid')], true, 'a 6 mm solid');
		s.round([unit(1, A)], true, A);
		expect(api.calls.match).toHaveLength(1);
		s.round([unit(1, A)], true, A);
		expect(api.calls.match).toHaveLength(2);
		expect(api.calls.match[1].body.findings).toEqual([{ id: 'u1', text: A }]);
	});

	it('a stopped recording makes the last finding stable at once (Q4)', () => {
		s.round([unit(1, A)], false, A);
		expect(api.calls.match[0].body.findings).toEqual([{ id: 'u1', text: A }]);
	});

	it('a second identical round makes no call', async () => {
		await matchA();
		s.round([unit(1, A)], true, A);
		s.round([unit(1, A)], false, A);
		await flush();
		expect(api.calls.match).toHaveLength(2);
		expect(state().groups[0].cards).toEqual([nodule]);
	});

	it('a new finding calls once, carrying all stable findings', async () => {
		await matchA();
		const us = [unit(1, A), unit(2, B, { group: 'Kidneys' })];
		s.round(us, true, dictation(us)); // u2 still growing, u1 already sent
		expect(api.calls.match).toHaveLength(2);
		s.round(us, true, dictation(us));
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body.findings.map((f) => f.text)).toEqual([A, B]);
	});

	it('an edit to a finding drops its cards and later matches the new text', async () => {
		await matchA();
		expect(state().groups).toHaveLength(1);
		s.round([unit(1, 'a 9 mm solid nodule')], false, 'a 9 mm solid nodule');
		expect(state().groups).toEqual([]);
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body.findings).toEqual([{ id: 'u1', text: 'a 9 mm solid nodule' }]);
	});

	it('a context change resets the cards, views and sent cache, and matches again', async () => {
		await matchA();
		s.open(cardRef(nodule));
		expect(Object.keys(state().views)).toHaveLength(1);
		s.setContext({ scanType: 'CT chest', history: 'weight los' });
		s.setContext({ scanType: 'CT chest', history: 'weight loss' }); // keystrokes: debounced, one reset
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS - 10);
		expect(state().groups).toHaveLength(1);
		expect(api.calls.match).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(20);
		expect(state().groups).toEqual([]);
		expect(state().views).toEqual({});
		expect(api.calls.match).toHaveLength(3);
		expect(api.calls.match[2].body).toMatchObject({ clinical_history: 'weight loss', findings: [{ id: 'u1', text: A }] });
		s.setContext({ scanType: 'CT chest', history: 'weight loss' }); // unchanged: nothing
		expect(api.calls.match).toHaveLength(3);
	});

	it('a stale response is dropped', async () => {
		s.round([unit(1, A)], false, A);
		s.setContext({ scanType: 'CT abdomen', history: '' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		expect(api.calls.match).toHaveLength(2);
		api.calls.match[0].resolve(matched([card({ key: 'stale-pack', finding: A })]));
		await flush();
		expect(state().groups).toEqual([]);
		api.calls.match[1].resolve(matched([nodule]));
		await flush();
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key]);
	});

	it('one /match in flight at a time; plans made during it queue one follow-up', async () => {
		s.round([unit(1, A)], false, A);
		const us2 = [unit(1, A), unit(2, B)];
		s.round(us2, false, dictation(us2));
		const us3 = [...us2, unit(3, 'a 1 cm lymph node')];
		s.round(us3, false, dictation(us3));
		expect(api.calls.match).toHaveLength(1);
		expect(state().matching).toBe(true);
		api.calls.match[0].resolve(matched([nodule]));
		await flush();
		expect(api.calls.match).toHaveLength(2);
		expect(api.calls.match[1].body.findings.map((f) => f.id)).toEqual(['u1', 'u2', 'u3']);
		expect(api.calls.match[1].body.dictation).toBe(dictation(us3));
	});

	it('a /match failure leaves no cards, sets matchFailed and caches nothing; retryMatch calls again', async () => {
		s.round([unit(1, A)], false, A);
		api.calls.match[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state()).toMatchObject({ matchFailed: true, matching: false, groups: [] });
		s.round([unit(1, A), unit(2, B)], false, `${A} ${B}`); // backing off: no call per round
		expect(api.calls.match).toHaveLength(1);
		s.retryMatch(); // Retry bypasses the backoff
		expect(api.calls.match).toHaveLength(2);
		expect(state().matchFailed).toBe(false);
		api.calls.match[1].resolve(matched([nodule]));
		await flush();
		expect(state().groups).toHaveLength(1);
		expect(s.log().failed).toEqual({ match: 1 });
	});

	it('after a failed /match, rounds resume calling once the backoff has passed', async () => {
		s.round([unit(1, A)], false, A);
		api.calls.match[0].reject(new CopilotError('network'));
		await flush();
		s.round([unit(1, A)], false, A);
		expect(api.calls.match).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(MATCH_BACKOFF_MS);
		s.round([unit(1, A)], false, A);
		expect(api.calls.match).toHaveLength(2);
	});

	it('a context typed back to its old value cancels the pending reset', async () => {
		await matchA();
		s.setContext({ scanType: 'CT chest', history: 'coughs' });
		s.setContext({ scanType: 'CT chest', history: 'cough' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS * 2);
		expect(state().groups).toHaveLength(1);
		expect(api.calls.match).toHaveLength(2);
	});

	it('a CopilotOff (404) turns the session off and later calls are never made', async () => {
		s.round([unit(1, A)], false, A);
		api.calls.match[0].reject(new CopilotOff());
		await flush();
		expect(state().on).toBe(false);
		s.round([unit(1, A), unit(2, B)], false, `${A} ${B}`);
		s.setContext({ scanType: 'MRI', history: '' });
		s.open(cardRef(nodule));
		s.other();
		s.retryMatch();
		expect(api.calls.match).toHaveLength(1);
		expect(api.calls.open).toHaveLength(0);
		expect(api.calls.other).toHaveLength(0);
	});

	it('a CopilotOff from /open turns it off too', async () => {
		await matchA();
		s.open(cardRef(nodule));
		api.calls.open[0].reject(new CopilotOff());
		await flush();
		expect(state()).toMatchObject({ on: false, groups: [] });
	});
});

describe('session: opening cards', () => {
	const exam = card({ key: 'cad-rads-2', name: 'CAD-RADS 2.0', finding_id: 'exam', finding: 'whole dictation' });

	it('exam cards auto-open with finding = findingsText, and /match dictation equals /open findings', async () => {
		s.round([unit(1, A)], false, 'LUNGS: a 6 mm solid nodule.');
		api.calls.match[0].resolve(matched([exam, nodule]));
		await flush();
		expect(api.calls.open).toHaveLength(1); // the finding card waits for a click (Q3)
		const body = api.calls.open[0].body;
		expect(body.card).toEqual(exam);
		expect(body.finding).toBe('LUNGS: a 6 mm solid nodule.');
		expect(body.findings).toBe(api.calls.match[0].body.dictation);
		expect(state().views[cardRef(exam)]).toMatchObject({ open: false, loading: true });
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		expect(state().views[cardRef(exam)].result?.preview?.state).toBe('applies');
		expect(s.log().quiet).toEqual(['cad-rads-2']);
	});

	it('exam cards re-open, debounced, when recording stops and the findings text changed', async () => {
		s.round([unit(1, A)], false, 'one');
		api.calls.match[0].resolve(matched([exam]));
		await flush();
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		s.round([unit(1, A)], true, 'one two'); // recording: no re-open
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(1);
		s.round([unit(1, A)], false, 'one two three');
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS - 10);
		expect(api.calls.open).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(20);
		expect(api.calls.open).toHaveLength(2);
		expect(api.calls.open[1].body.finding).toBe('one two three');
		api.calls.open[1].resolve(result(exam, preview()));
		await flush();
		s.round([unit(1, A)], false, 'one two three'); // unchanged text: no re-open
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(2);
	});

	it('open: the body uses the finding text; a reopen with a result sends nothing; close keeps the result', async () => {
		await matchA();
		const ref = cardRef(nodule);
		s.open(ref);
		expect(api.calls.open[0].body).toEqual({ card: nodule, finding: A, findings: A, clinical_history: 'cough', answered: {}, patient: {} });
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		s.close(ref);
		expect(state().views[ref]).toMatchObject({ open: false });
		expect(state().views[ref].result).not.toBeNull();
		s.open(ref);
		expect(api.calls.open).toHaveLength(1);
		expect(s.log().opened).toEqual([nodule.key]);
	});

	it('a failed open shows the error on that card only; retry opens it again', async () => {
		await matchA();
		const ref = cardRef(nodule);
		s.open(ref);
		api.calls.open[0].reject(new CopilotError('timeout'));
		await flush();
		expect(state().views[ref]).toMatchObject({ loading: false, error: 'timeout' });
		expect(state().on).toBe(true);
		s.retry(ref);
		expect(api.calls.open).toHaveLength(2);
		expect(state().views[ref]).toMatchObject({ loading: true, error: null });
	});

	it('siblings open in parallel, one call per column, the card echoed with its key swapped', async () => {
		const sib = card({ finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'], needs_modality: '' });
		await matchA([sib]);
		s.open(cardRef(sib));
		expect(api.calls.open).toHaveLength(2);
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual([sib.key, 'bts-pulmonary-nodule']);
		expect(api.calls.open[1].body.card).toEqual({ ...sib, key: 'bts-pulmonary-nodule', name: 'bts-pulmonary-nodule' });
		api.calls.open[1].resolve(result(card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' }), preview()));
		await flush();
		const cols = state().views[cardRef(sib)].columns!;
		expect(cols['bts-pulmonary-nodule'].result?.entry?.name).toBe('BTS 2015');
		expect(cols[sib.key].loading).toBe(true);
	});

	it('a column retry splits its ref on the LAST "#" and re-opens that column only', async () => {
		const hashText = 'nodule #2 in the right lung';
		const sib = card({ finding_id: 'u1', finding: hashText, siblings: ['bts-pulmonary-nodule'] });
		s.round([unit(1, hashText)], false, hashText);
		api.calls.match[0].resolve(matched([sib]));
		await flush();
		s.open(cardRef(sib));
		api.calls.open[1].reject(new CopilotError('network'));
		await flush();
		expect(state().views[cardRef(sib)].columns!['bts-pulmonary-nodule'].error).toBe('network');
		s.retry(`${cardRef(sib)}#bts-pulmonary-nodule`);
		expect(api.calls.open).toHaveLength(3);
		expect(api.calls.open[2].body.card.key).toBe('bts-pulmonary-nodule');
	});

	it('needs-modality cards never open: not on arrival, not on click, not on retry', async () => {
		const examUs = card({ key: 'bta-thyroid-u-grading', finding_id: 'exam', needs_modality: 'US' });
		const findUs = card({ key: 'bta-x', finding_id: 'u1', finding: A, needs_modality: 'US' });
		await matchA([examUs, findUs]);
		s.open(cardRef(examUs));
		s.open(cardRef(findUs));
		s.retry(cardRef(findUs));
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS * 2);
		expect(api.calls.open).toHaveLength(0);
	});

	it('other: merges /match/other cards without duplicates, each tagged fromOther', async () => {
		await matchA();
		const extra = card({ key: 'web-guide', name: 'A society guide', finding_id: 'u1', finding: A, known: false });
		s.other();
		expect(state().otherState).toBe('loading');
		expect(api.calls.other[0].body.findings).toEqual([{ id: 'u1', text: A }]);
		api.calls.other[0].resolve(matched([nodule, extra, extra]));
		await flush();
		expect(state().otherState).toBe('done');
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key, 'web-guide']);
		expect(state().views[cardRef(extra)].fromOther).toBe(true);
		expect(state().views[cardRef(nodule)]?.fromOther).toBeUndefined();
		// a later /match keeps the other card
		s.round([unit(1, A), unit(2, B)], false, `${A} ${B}`);
		api.calls.match[2].resolve(matched([nodule]));
		await flush();
		expect(state().groups[0].cards.map((c) => c.key)).toEqual([nodule.key, 'web-guide']);
	});

	it('other failure sets failed; destroy aborts in-flight calls and drops their answers', async () => {
		await matchA();
		s.other();
		api.calls.other[0].reject(new CopilotError('http', 500));
		await flush();
		expect(state().otherState).toBe('failed');
		s.open(cardRef(nodule));
		const before = state();
		s.destroy();
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		expect(get(s.state)).toEqual(before);
	});

	it('an exam card with siblings: open reuses the auto-opened primary and fetches only the sibling', async () => {
		const examSib = card({ key: 'cad-rads-2', finding_id: 'exam', finding: 'x', siblings: ['other-cta-pack'] });
		s.round([unit(1, A)], false, A);
		api.calls.match[0].resolve(matched([examSib]));
		await flush();
		expect(api.calls.open).toHaveLength(1); // auto-open of the primary
		s.open(cardRef(examSib)); // still loading: not asked again
		expect(api.calls.open.map((c) => c.body.card.key)).toEqual(['cad-rads-2', 'other-cta-pack']);
	});

	it('a sibling card retry re-fetches only the failed columns', async () => {
		const sib = card({ finding_id: 'u1', finding: A, siblings: ['bts-pulmonary-nodule'] });
		await matchA([sib]);
		s.open(cardRef(sib));
		api.calls.open[0].resolve(result(sib, preview()));
		api.calls.open[1].reject(new CopilotError('timeout'));
		await flush();
		s.retry(cardRef(sib));
		expect(api.calls.open).toHaveLength(3);
		expect(api.calls.open[2].body.card.key).toBe('bts-pulmonary-nodule');
	});

	it('an /open answer from before a reset never lands on a later request of the same card', async () => {
		await matchA();
		s.open(cardRef(nodule));
		s.setContext({ scanType: 'CT chest', history: 'other' });
		await vi.advanceTimersByTimeAsync(CONTEXT_DEBOUNCE_MS);
		api.calls.match[2].resolve(matched([nodule]));
		await flush();
		s.open(cardRef(nodule));
		expect(api.calls.open).toHaveLength(2);
		api.calls.open[0].resolve(result(nodule, preview({ proposal: null, possible: ['old'] })));
		await flush();
		expect(state().views[cardRef(nodule)]).toMatchObject({ loading: true, result: null });
		api.calls.open[1].resolve(result(nodule, preview()));
		await flush();
		expect(state().views[cardRef(nodule)].result?.preview?.possible).toEqual([]);
	});

	it('a card first found by Other loses its "other" tag when /match later returns it', async () => {
		await matchA();
		const extra = card({ key: 'web-guide', finding_id: 'u1', finding: A });
		s.other();
		api.calls.other[0].resolve(matched([extra]));
		await flush();
		expect(state().views[cardRef(extra)].fromOther).toBe(true);
		s.round([unit(1, A), unit(2, B)], false, `${A} ${B}`);
		api.calls.match[2].resolve(matched([nodule, extra]));
		await flush();
		expect(state().views[cardRef(extra)].fromOther).toBe(false);
	});

	it('an exam re-open keeps the last result while it loads', async () => {
		s.round([unit(1, A)], false, 'one');
		api.calls.match[0].resolve(matched([exam]));
		await flush();
		api.calls.open[0].resolve(result(exam, preview()));
		await flush();
		s.round([unit(1, A)], false, 'one two');
		await vi.advanceTimersByTimeAsync(EXAM_REOPEN_MS);
		expect(state().views[cardRef(exam)].loading).toBe(true);
		expect(state().views[cardRef(exam)].result).not.toBeNull();
	});

	it('log carries keys, counts and ms only: no finding text', async () => {
		await matchA();
		s.open(cardRef(nodule));
		api.calls.open[0].resolve(result(nodule, preview()));
		await flush();
		const l = s.log();
		expect(l.matched).toEqual([nodule.key]);
		expect(JSON.stringify(l)).not.toContain('nodule ');
		expect(JSON.stringify(l)).not.toContain(A);
	});
});
