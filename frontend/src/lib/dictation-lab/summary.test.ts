import { describe, expect, it } from 'vitest';
import { agreementClass, summariseTraces } from './summary';
import type { ProcessTrace, TriageCandidateTrace, TriageTrace } from './types';

const cand = (
	action: TriageCandidateTrace['action'],
	conf: number | null = 0.9
): TriageCandidateTrace => ({
	action,
	confidence: conf,
	probabilities: null,
	is_correction: null,
	needs_committed_edit: null,
	latency_ms: 300,
	input_tokens: null,
	cost_usd: null,
	error: null
});
const tr = (t: Partial<TriageTrace> | null, latency = 1000): ProcessTrace => ({
	seq: 1,
	at: 0,
	utterance: 'x',
	committed: '',
	activeBefore: '',
	activeAfter: '',
	scanType: '',
	latency_ms: latency,
	triage: t
		? {
				mode: 'debug',
				derived: null,
				routed: 'model',
				routed_by: null,
				live_latency_ms: null,
				jev: null,
				qwen: null,
				...t
			}
		: null
});

describe('agreementClass', () => {
	it('classifies', () => {
		expect(agreementClass(tr(null))).toBe('none');
		expect(agreementClass(tr({ routed: 'deterministic' }))).toBe('deterministic');
		expect(
			agreementClass(
				tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('append_new_finding', null) })
			)
		).toBe('both');
		expect(
			agreementClass(tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('ignore_noise', null) }))
		).toBe('one');
		expect(
			agreementClass(tr({ derived: 'append', jev: cand('ignore_noise'), qwen: cand('ignore_noise', null) }))
		).toBe('neither');
		expect(agreementClass(tr({ derived: 'correct', jev: cand('correct_previous_finding'), qwen: null }))).toBe(
			'both'
		);
	});
});

describe('summariseTraces', () => {
	it('counts handlers, mean latencies and per-candidate agreement', () => {
		const s = summariseTraces([
			tr({ routed: 'deterministic', routed_by: 'jev', jev: cand('ignore_noise') }, 120),
			tr({ derived: 'append', jev: cand('append_new_finding'), qwen: cand('ignore_noise', null) }, 1100),
			tr({ derived: 'noop', jev: cand('ignore_noise'), qwen: cand('ignore_noise', null) }, 900),
			tr(null, 1000)
		]);
		expect(s.total).toBe(4);
		expect(s.deterministic).toBe(1);
		expect(s.model).toBe(3);
		expect(s.meanLatencyDeterministicMs).toBe(120);
		expect(s.meanLatencyModelMs).toBe(1000);
		expect(s.agreement.jev).toEqual({ n: 2, agreed: 2 });
		expect(s.agreement.qwen).toEqual({ n: 2, agreed: 1 });
	});
});
