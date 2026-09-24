import type { CoverageFixtureCase, PillState, PillThresholds } from './types';

export function pillState(score: number | undefined, t: PillThresholds): PillState {
	if (score == null) return 'absent';
	if (score >= t.hi) return 'covered';
	if (score >= t.lo) return 'partial';
	return 'absent';
}

export type SectionAgreement = 'agree' | 'jev-only' | 'qwen-only';

/** Jev at the binary threshold versus Qwen membership, per section. */
export function coverageAgreement(
	sections: string[],
	jevScores: Record<string, number>,
	qwenCovered: string[],
	threshold = 0.5
): Record<string, SectionAgreement> {
	const q = new Set(qwenCovered);
	const out: Record<string, SectionAgreement> = {};
	for (const s of sections) {
		const j = (jevScores[s] ?? 0) >= threshold;
		const qq = q.has(s);
		out[s] = j === qq ? 'agree' : j ? 'jev-only' : 'qwen-only';
	}
	return out;
}

export type CoverageLabels = Pick<CoverageFixtureCase, 'id' | 'expected_covered' | 'rule' | 'hard' | 'note'>;

export function buildCoverageFixtureLine(
	state: { scratchpad: string; checklist: string[]; scanType: string },
	labels: CoverageLabels
): string {
	const c: CoverageFixtureCase = {
		id: labels.id,
		scan_type: state.scanType,
		checklist: state.checklist,
		scratchpad: state.scratchpad,
		expected_covered: labels.expected_covered,
		rule: labels.rule,
		hard: labels.hard,
		note: labels.note
	};
	return JSON.stringify(c);
}
