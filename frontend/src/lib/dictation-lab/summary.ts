import type { Candidate, ProcessTrace, TriageAction, TriageTrace } from './types';

/** Mirrors backend dictation_triage_labels.AGREEMENT_MAP. */
const AGREEMENT: Record<TriageAction, string[]> = {
	append_new_finding: ['append'],
	correct_previous_finding: ['correct', 'committed_edit'],
	restate_existing_finding: ['noop', 'correct'],
	delete_previous_utterance: ['delete'],
	formatting_command: ['noop', 'append'],
	ignore_noise: ['noop']
};

export function candidateAgrees(t: TriageTrace, c: Candidate): boolean | null {
	const slot = t[c];
	if (!slot || !slot.action || !t.derived) return null;
	return AGREEMENT[slot.action].includes(t.derived);
}

export type AgreementClass = 'none' | 'deterministic' | 'both' | 'one' | 'neither';

export function agreementClass(p: ProcessTrace): AgreementClass {
	const t = p.triage;
	if (!t) return 'none';
	if (t.routed === 'deterministic') return 'deterministic';
	const votes = (['jev', 'qwen'] as Candidate[])
		.map((c) => candidateAgrees(t, c))
		.filter((v): v is boolean => v !== null);
	if (votes.length === 0) return 'none';
	const yes = votes.filter(Boolean).length;
	if (yes === votes.length) return 'both';
	return yes === 0 ? 'neither' : 'one';
}

export interface LabSummary {
	total: number;
	deterministic: number;
	model: number;
	meanLatencyDeterministicMs: number | null;
	meanLatencyModelMs: number | null;
	agreement: Record<Candidate, { n: number; agreed: number }>;
}

function mean(xs: number[]): number | null {
	return xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null;
}

export function summariseTraces(traces: ProcessTrace[]): LabSummary {
	const det = traces.filter((p) => p.triage?.routed === 'deterministic');
	const model = traces.filter((p) => p.triage?.routed !== 'deterministic');
	const agreement = { jev: { n: 0, agreed: 0 }, qwen: { n: 0, agreed: 0 } };
	for (const p of traces) {
		if (!p.triage) continue;
		for (const c of ['jev', 'qwen'] as Candidate[]) {
			const a = candidateAgrees(p.triage, c);
			if (a === null) continue;
			agreement[c].n += 1;
			if (a) agreement[c].agreed += 1;
		}
	}
	return {
		total: traces.length,
		deterministic: det.length,
		model: model.length,
		meanLatencyDeterministicMs: mean(det.map((p) => p.latency_ms)),
		meanLatencyModelMs: mean(model.map((p) => p.latency_ms)),
		agreement
	};
}
