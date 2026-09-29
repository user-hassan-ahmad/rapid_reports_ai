export type Candidate = 'jev' | 'qwen';

export interface LabConfig {
	coverageDebug: boolean; // sets coverage_debug on /review
	pillThresholds: PillThresholds;
	frontDoor: FrontDoor; // 'timer' = Deepgram silence timers (production);
	// 'decision' = decision-first live: Jev bundle per final, fast-append + band router (step 5)
	polish: PolishStrategy; // decision-first only: 'race' fires a lean scoped polish together with Jev
}

export type PolishStrategy = 'full' | 'race';

export type FrontDoor = 'timer' | 'decision';

export interface PillThresholds {
	hi: number; // >= hi → covered
	lo: number; // >= lo and < hi → partial
}
export type PillState = 'covered' | 'partial' | 'absent';

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
