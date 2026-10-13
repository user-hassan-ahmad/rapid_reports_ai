import { describe, expect, it } from 'vitest';
import {
	changeFor,
	changesOnContinue,
	changesOnSkip,
	editWording,
	evidenceLine,
	isSentence,
	wordingProblem,
	flatCards,
	validValueName,
	HABIT_WHERE_HINT
} from './cards';
import type { DecisionCard } from './types';

const value = (name: string, selected: string | null = null): DecisionCard => ({
	id: `value:${name.toLowerCase()}`, kind: 'value', step: 'rules', title: name, evidence: [], ledger_kind: 'value', key: name,
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected, rank: 1
});
const PRIOR = 'the dictation names a previous imaging study for comparison';
const concept: DecisionCard = {
	id: 'concept:comparison', kind: 'concept', step: 'rules', title: 'Comparison with previous imaging', evidence: [],
	ledger_kind: 'concept', key: 'comparison', wording: { default: 'No previous imaging.', when_met: 'Compared with {date}.', condition: PRIOR },
	choices: [
		{ id: 'keep', label: 'Keep', choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with {date}.', condition: PRIOR, dictated: false } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '', condition: '', dictated: false } }
	],
	selected: null, rank: 2
};
const GIVEN = 'the dictation states a contrast agent was given';
const NOT_GIVEN = 'the dictation states no contrast agent was given';
const usual: DecisionCard = {
	id: 'concept:contrast', kind: 'concept', step: 'rules', title: 'Is contrast usually given for this scan?', evidence: [],
	ledger_kind: 'concept', key: 'contrast', usual: { given: 'Post contrast.', not_given: 'Non-contrast.' },
	choices: [
		{ id: 'usual:given', label: 'Usually given', choice: { use: true, default: 'Post contrast.', when_met: 'Non-contrast.', condition: NOT_GIVEN, dictated: false } },
		{ id: 'usual:not_given', label: 'Usually not given', choice: { use: true, default: 'Non-contrast.', when_met: 'Post contrast.', condition: GIVEN, dictated: false } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '', condition: '', dictated: false } }
	],
	selected: null, rank: 2
};
const group = (cards: DecisionCard[]): DecisionCard => ({
	id: 'group:one_report', kind: 'group', step: 'rules', title: 'Seen in one report: ' + cards.map((c) => c.title).join(', '),
	evidence: [], ledger_kind: '', key: '', choices: [], selected: null, rank: 1, collapsed: true, cards
});

describe('template-rules cards', () => {
	it('words evidence as reports, never percentages', () => {
		expect(evidenceLine({ reports: [4, 1, 2], quote: 'ECV 28%' })).toBe("reports 1, 2, 4: 'ECV 28%'");
		expect(evidenceLine({ reports: [3], quote: null })).toBe('report 3: not stated');
	});

	it('words the study setup as the setup, never as a report number', () => {
		expect(evidenceLine({ reports: [], source: 'setup', quote: 'CT abdomen with contrast' })).toBe(
			"From the study setup: 'CT abdomen with contrast'"
		);
		expect(evidenceLine({ reports: [], source: 'setup', quote: null })).toBe('From the study setup');
	});

	it('records a tapped choice, and edited wording only when written', () => {
		expect(changeFor(value('ECV'), { choiceId: 'relevant' }, 'creation')).toEqual({ kind: 'value', key: 'ECV', choice: { need: 'relevant' }, source: 'creation' });
		expect(changeFor(concept, { choiceId: 'edit' }, 'creation')).toBeNull();
		expect(changeFor(concept, { choiceId: 'edit', edited: { default: ' None. ', when_met: '' } }, 'creation')).toEqual({
			kind: 'concept', key: 'comparison', choice: { use: true, default: 'None.', when_met: '', condition: PRIOR, dictated: false }, source: 'creation'
		});
	});

	it('the dictated choice is recorded as it is', () => {
		const disagree: DecisionCard = {
			...concept, id: 'disagree:comparison', kind: 'disagree', wording: undefined,
			choices: [{ id: 'dictated', label: 'Use whichever is dictated', choice: { use: false, default: '', when_met: '', condition: '', dictated: true } }]
		};
		expect(changeFor(disagree, { choiceId: 'dictated' }, 'creation')?.choice).toEqual({ use: false, default: '', when_met: '', condition: '', dictated: true });
	});

	it('editing a usual-state card starts from the chosen state and keeps its condition', () => {
		expect(editWording(usual, null)).toEqual({ default: 'Post contrast.', when_met: 'Non-contrast.', condition: NOT_GIVEN });
		const draft = editWording(usual, 'usual:not_given');
		expect(draft).toEqual({ default: 'Non-contrast.', when_met: 'Post contrast.', condition: GIVEN });
		expect(changeFor(usual, { choiceId: 'edit', edited: { ...draft, default: 'Unenhanced CT.' } }, 'creation')?.choice).toEqual({
			use: true, default: 'Unenhanced CT.', when_met: 'Post contrast.', condition: GIVEN, dictated: false
		});
		expect(editWording(concept, null)).toEqual(concept.wording);
	});

	it('mirrors the server sentence rule', () => {
		for (const ok of ['Compared with {date}.', '{n} phases were acquired.', '3 phases were acquired.', 'eGFR was 60:', 'No prior.'])
			expect(isSentence(ok)).toBe(true);
		for (const bad of ['compared with {date}.', 'Compared with {date}', 'Compared with', 'with {date}:x', ''])
			expect(isSentence(bad)).toBe(false);
	});

	it('an invalid concept wording records nothing and says why', () => {
		const edit = (when_met: string) => ({ choiceId: 'edit', edited: { default: 'No previous imaging.', when_met } });
		expect(changeFor(concept, edit('compared with {date}'), 'creation')).toBeNull();
		expect(wordingProblem(concept, edit('compared with {date}').edited)).toBe('Write it as a full sentence.');
		expect(wordingProblem(concept, edit('Compared with "the" study.').edited)).toBe('Leave out double quotes.');
		expect(wordingProblem(concept, edit('Compared with {date}.').edited)).toBeNull();
		expect(changeFor(concept, edit('Compared with {date}.'), 'creation')).not.toBeNull();
	});

	it('a normal sentence has no quotes and nothing to fill in', () => {
		const normal: DecisionCard = { id: 'normal:x', kind: 'normal', step: 'style', title: 'Liver: liver', evidence: [], ledger_kind: 'normal',
			key: 'Liver :: liver', selected: null, rank: 4, wording: { text: 'The liver is normal.' },
			choices: [{ id: 'edit', label: 'Edit wording', choice: null }] };
		expect(wordingProblem(normal, { text: 'The {organ} is normal.' })).toBe('Leave out values to fill in.');
		expect(changeFor(normal, { choiceId: 'edit', edited: { text: 'The "liver" is normal.' } }, 'creation')).toBeNull();
		expect(changeFor(normal, { choiceId: 'edit', edited: { text: 'The liver is unremarkable.' } }, 'creation')).not.toBeNull();
	});

	it('Continue sends answers, kept defaults and added values; unanswered open cards send nothing', () => {
		const lvef = value('LVEF', 'every');
		const out = changesOnContinue([value('ECV'), concept], [lvef], { 'value:ecv': { choiceId: 'not_needed' } }, ['Heart rate'], 'creation');
		expect(out).toEqual([
			{ kind: 'value', key: 'ECV', choice: { need: 'not_needed' }, source: 'creation' },
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' },
			{ kind: 'value', key: 'Heart rate', choice: { need: 'every' }, source: 'creation' }
		]);
	});

	it('cards inside a collapsed group are answered one by one', () => {
		const more = [group([value('HR'), value('BSA')])];
		expect(flatCards(more).map((c) => c.id)).toEqual(['value:hr', 'value:bsa']);
		expect(changesOnContinue(more, [], { 'value:bsa': { choiceId: 'relevant' } }, [], 'first_use_review')).toEqual([
			{ kind: 'value', key: 'BSA', choice: { need: 'relevant' }, source: 'first_use_review' }
		]);
	});

	it('Skip records the defaults as defaults', () => {
		expect(changesOnSkip([{ kind: 'value', key: 'LVEF', choice: { need: 'every' } }])).toEqual([
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }
		]);
	});

	it('accepts only short plain value names', () => {
		expect(validValueName('Heart rate')).toBe(true);
		expect(validValueName('a "b"')).toBe(false);
		expect(validValueName('one two three four five six seven eight nine')).toBe(false);
		expect(validValueName('  ')).toBe(false);
	});
});

describe('habit cards', () => {
	const HKEY = 'Upper :: an alpha abnormality is reported';
	const T = { question: 'Extension beyond alpha?', yes: 'The abnormality extends beyond alpha.', no: 'No extension beyond alpha.' };
	const habit = (): DecisionCard => ({
		id: 'habit:x', kind: 'habit', step: 'rules', title: 'Upper: when an alpha abnormality is reported', evidence: [],
		ledger_kind: 'habit', key: HKEY, habit: { condition: 'an alpha abnormality is reported', ...T },
		choices: [
			{ id: 'ask', label: 'Ask every time', choice: { mode: 'ask', ...T } },
			{ id: 'edit', label: 'Edit wording', choice: null }
		],
		selected: null, rank: 2
	});
	it('the edit form starts from the habit; an edit is a question asked under the reworded condition', () => {
		expect(editWording(habit(), null)).toEqual({ condition: 'an alpha abnormality is reported', ...T });
		const edited = { condition: 'an alpha abnormality in the upper part is reported', ...T };
		expect(changeFor(habit(), { choiceId: 'edit', edited }, 'creation')).toEqual({
			kind: 'habit', key: 'Upper :: an alpha abnormality in the upper part is reported',
			choice: { mode: 'ask', ...T }, source: 'creation'
		});
		expect(changeFor(habit(), { choiceId: 'edit', edited: { ...edited, no: '' } }, 'creation')).toBeNull();
	});
	it('names what the server would refuse, and hints at naming where', () => {
		expect(wordingProblem(habit(), { condition: 'an alpha abnormality is reported', ...T, question: 'Extension' })).toBe('End the question with "?".');
		expect(wordingProblem(habit(), { condition: 'an alpha "x" is reported', ...T })).toBe('Leave out double quotes.');
		expect(wordingProblem(habit(), { condition: 'an alpha abnormality is reported', ...T, yes: 'It is {x} mm.' })).toBe('Leave out values to fill in.');
		expect(HABIT_WHERE_HINT).toBe("Name where: e.g. 'in the <structure>'");
	});
});
