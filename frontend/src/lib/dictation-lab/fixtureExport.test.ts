import { describe, expect, it } from 'vitest';
import { buildFixtureLine, suggestId } from './fixtureExport';
import type { ProcessTrace } from './types';

const trace: ProcessTrace = {
	seq: 3,
	at: 0,
	utterance: 'scratch that',
	committed: '',
	activeBefore: '- a\n- b',
	activeAfter: '- a',
	scanType: 'CT chest',
	latency_ms: 10,
	triage: null
};

describe('buildFixtureLine', () => {
	it('produces one valid JSON line with the required keys', () => {
		const line = buildFixtureLine(trace, {
			id: 'delete-lab-01',
			expected_action: 'delete_previous_utterance',
			expected_is_correction: true,
			expected_needs_committed_edit: false,
			hard: false,
			note: 'from lab'
		});
		expect(line.includes('\n')).toBe(false);
		const obj = JSON.parse(line);
		expect(obj).toEqual({
			id: 'delete-lab-01',
			committed: '',
			active: '- a\n- b',
			utterance: 'scratch that',
			scan_type: 'CT chest',
			expected_action: 'delete_previous_utterance',
			expected_is_correction: true,
			expected_needs_committed_edit: false,
			hard: false,
			note: 'from lab'
		});
	});
	it('suggestId derives a prefix from the action and a sequence', () => {
		expect(suggestId('formatting_command', 7)).toBe('format-lab-07');
		expect(suggestId('append_new_finding', 12)).toBe('append-lab-12');
	});
});
