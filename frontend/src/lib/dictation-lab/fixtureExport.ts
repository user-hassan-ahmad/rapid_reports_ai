import type { FixtureCase, ProcessTrace, TriageAction } from './types';

const PREFIX: Record<TriageAction, string> = {
	append_new_finding: 'append',
	correct_previous_finding: 'correct',
	restate_existing_finding: 'restate',
	delete_previous_utterance: 'delete',
	formatting_command: 'format',
	ignore_noise: 'noise'
};

export function suggestId(action: TriageAction, n: number): string {
	return `${PREFIX[action]}-lab-${String(n).padStart(2, '0')}`;
}

export type FixtureLabels = Pick<
	FixtureCase,
	'id' | 'expected_action' | 'expected_is_correction' | 'expected_needs_committed_edit' | 'hard' | 'note'
>;

/** One JSONL line for tests/fixtures/triage_utterances.jsonl. Key order matches the seed file. */
export function buildFixtureLine(trace: ProcessTrace, labels: FixtureLabels): string {
	const c: FixtureCase = {
		id: labels.id,
		committed: trace.committed,
		active: trace.activeBefore,
		utterance: trace.utterance,
		scan_type: trace.scanType,
		expected_action: labels.expected_action,
		expected_is_correction: labels.expected_is_correction,
		expected_needs_committed_edit: labels.expected_needs_committed_edit,
		hard: labels.hard,
		note: labels.note
	};
	return JSON.stringify(c);
}
