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
	coverageDebug: boolean; // sets coverage_debug on /review
	pillThresholds: PillThresholds;
	frontDoor: FrontDoor; // 'timer' = Deepgram silence timers (production); 'jev' = boundary classifier
}

export type FrontDoor = 'timer' | 'jev';
export type Boundary = 'complete' | 'continues' | 'command';
export type Placement = 'extend_previous_line' | 'new_line' | 'new_paragraph';

export interface PillThresholds {
	hi: number; // >= hi → covered
	lo: number; // >= lo and < hi → partial
}
export type PillState = 'covered' | 'partial' | 'absent';

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

/** Mirrors backend CoverageCandidateTrace / CoverageTrace. */
export interface CoverageCandidateTrace {
	scores: Record<string, number> | null;
	covered: string[] | null;
	raw: string[] | null;
	latency_ms: number | null;
	input_tokens: number | null;
	cost_usd: number | null;
	error: string | null;
}
export interface CoverageTrace {
	selected: Candidate;
	jev: CoverageCandidateTrace | null;
	qwen: CoverageCandidateTrace | null;
}
/** One line of tests/fixtures/coverage_cases.jsonl. */
export interface CoverageFixtureCase {
	id: string;
	scan_type: string;
	checklist: string[];
	scratchpad: string;
	expected_covered: string[];
	rule: string;
	hard: boolean;
	note: string;
}

/** One finalised Deepgram chunk classified by the front door. */
export interface ChunkTrace {
	seq: number;
	at: number;
	chunk: string;
	buffered: string;
	resolved: Boundary;
	boundary: Boundary | null;
	confidence: number | null;
	asr_risk: number | null;
	latency_ms: number;
	error: string | null;
	sent: string | null; // the merged statement handed to polish, when one was
	viaBackstop: boolean;
	placement: Placement | null; // Jev's placement for a sent statement
	placement_confidence: number | null;
	silence_s: number | null; // > 0 on a silence re-check row
	standalone: number | null;
	via: 'jev' | 'punctuation' | 'silence' | 'hard_limit';
}
/** Mirrors backend UtteranceResponse. */
export interface UtteranceResponse {
	resolved: Boundary;
	boundary: Boundary | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	asr_risk: number | null;
	latency_ms: number | null;
	error: string | null;
	placement?: Placement;
	placement_raw?: string | null;
	placement_confidence?: number | null;
	standalone?: number | null;
}
