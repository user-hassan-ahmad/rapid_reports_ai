/** Mirrors backend dictation_triage.TriageAction. */
export type TriageAction =
	| 'append_new_finding'
	| 'correct_previous_finding'
	| 'restate_existing_finding'
	| 'delete_previous_utterance'
	| 'formatting_command'
	| 'ignore_noise';

export const TRIAGE_ACTIONS: TriageAction[] = [
	'append_new_finding',
	'correct_previous_finding',
	'restate_existing_finding',
	'delete_previous_utterance',
	'formatting_command',
	'ignore_noise'
];

export type Candidate = 'jev' | 'qwen';
export type Strategy = 'shadow' | 'route:jev' | 'route:qwen';

export interface LabConfig {
	strategy: Strategy;
	threshold: number; // 0.5–1.0
	showBoth: boolean; // sets triage_debug
}

/** Fields merged into the /api/canvas/process body. Mirrors CanvasProcessRequest. */
export interface LabRequestFields {
	triage_debug: boolean;
	triage_route: { candidate: Candidate; threshold: number } | null;
}

/** Mirrors backend TriageCandidateTrace. */
export interface TriageCandidateTrace {
	action: TriageAction | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	is_correction: number | null;
	needs_committed_edit: number | null;
	latency_ms: number | null;
	input_tokens: number | null;
	cost_usd: number | null;
	error: string | null;
}

/** Mirrors backend TriageTrace. */
export interface TriageTrace {
	mode: 'debug' | 'route';
	derived: 'append' | 'correct' | 'delete' | 'noop' | 'committed_edit' | null;
	routed: 'deterministic' | 'model' | null;
	routed_by: Candidate | null;
	live_latency_ms: number | null;
	jev: TriageCandidateTrace | null;
	qwen: TriageCandidateTrace | null;
}

/** One completed /process call, as reported by DictationScratchpad.onProcessTrace. */
export interface ProcessTrace {
	seq: number;
	at: number; // Date.now()
	utterance: string;
	committed: string;
	activeBefore: string;
	activeAfter: string;
	scanType: string;
	latency_ms: number;
	triage: TriageTrace | null;
}

/** One line of tests/fixtures/triage_utterances.jsonl. */
export interface FixtureCase {
	id: string;
	committed: string;
	active: string;
	utterance: string;
	scan_type: string;
	expected_action: TriageAction;
	expected_is_correction: boolean;
	expected_needs_committed_edit: boolean;
	hard: boolean;
	note: string;
}
