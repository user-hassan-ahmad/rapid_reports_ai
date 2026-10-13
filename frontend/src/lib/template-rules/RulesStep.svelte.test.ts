import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import RulesStep from './RulesStep.svelte';
import type { DecisionCard, Evidence } from './types';

const value = (
	name: string,
	selected: string | null = null,
	evidence: Evidence[] = [{ reports: [1, 3], quote: `${name} 28%` }, { reports: [2], quote: null }]
): DecisionCard => ({
	id: `value:${name.toLowerCase()}`, kind: 'value', step: 'rules', title: name, evidence, ledger_kind: 'value', key: name,
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'relevant', label: 'Only when relevant', choice: { need: 'relevant' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected, rank: 1
});
const PRIOR = 'the dictation names a previous imaging study for comparison';
const concept = (): DecisionCard => ({
	id: 'concept:comparison', kind: 'concept', step: 'rules', title: 'Comparison with previous imaging',
	evidence: [{ reports: [1, 3], quote: 'No previous imaging.' }], ledger_kind: 'concept', key: 'comparison',
	wording: { default: 'No previous imaging.', when_met: '', condition: PRIOR },
	choices: [
		{ id: 'keep', label: 'Keep', choice: { use: true, default: 'No previous imaging.', when_met: '', condition: PRIOR, dictated: false } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '', condition: '', dictated: false } }
	],
	selected: null, rank: 2
});
const GIVEN = 'the dictation states a contrast agent was given';
const NOT_GIVEN = 'the dictation states no contrast agent was given';
const usual = (): DecisionCard => ({
	id: 'concept:contrast', kind: 'concept', step: 'rules', title: 'Is contrast usually given for this scan?',
	evidence: [{ reports: [], source: 'setup', quote: 'CT abdomen' }, { reports: [1], quote: 'Post contrast.' }, { reports: [2], quote: 'Non-contrast.' }],
	ledger_kind: 'concept', key: 'contrast', usual: { given: 'Post contrast.', not_given: 'Non-contrast.' },
	choices: [
		{ id: 'usual:given', label: 'Usually given', choice: { use: true, default: 'Post contrast.', when_met: 'Non-contrast.', condition: NOT_GIVEN, dictated: false } },
		{ id: 'usual:not_given', label: 'Usually not given', choice: { use: true, default: 'Non-contrast.', when_met: 'Post contrast.', condition: GIVEN, dictated: false } },
		{ id: 'edit', label: 'Edit wording', choice: null },
		{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '', condition: '', dictated: false } }
	],
	selected: null, rank: 2
});
const group = (cards: DecisionCard[]): DecisionCard => ({
	id: 'group:one_report', kind: 'group', step: 'rules', title: 'Seen in one report: ' + cards.map((c) => c.title).join(', '),
	evidence: [], ledger_kind: '', key: '', choices: [], selected: null, rank: 1, collapsed: true, cards
});

describe('RulesStep', () => {
	it('shows evidence as reports, a three-way value chip, nothing pre-ticked for a partial value', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('ECV')], kept: [value('LVEF', 'every', [{ reports: [1, 2, 3], quote: 'LVEF 55%' }])], onContinue });
		await expect.element(page.getByText("reports 1, 3: 'ECV 28%'")).toBeInTheDocument();
		await expect.element(page.getByText('report 2: not stated')).toBeInTheDocument();
		const relevant = page.getByRole('button', { name: 'ECV: Only when relevant' });
		await expect.element(relevant).toHaveAttribute('aria-pressed', 'false');
		await relevant.click();
		await expect.element(relevant).toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([
			{ kind: 'value', key: 'ECV', choice: { need: 'relevant' }, source: 'creation' },
			{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }
		]);
	});

	it('has no confirm-all control', async () => {
		render(RulesStep, { cards: [value('ECV'), value('HR')], onContinue: vi.fn() });
		await expect.element(page.getByRole('button', { name: /confirm all|accept all/i })).not.toBeInTheDocument();
	});

	it('folds agreed items into a collapsed Kept as-is list; Change brings one back as a card', async () => {
		render(RulesStep, { cards: [], kept: [value('LVEF', 'every')], onContinue: vi.fn() });
		await expect.element(page.getByText('LVEF: Every report')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Kept as-is (1)' }).click();
		await expect.element(page.getByText('LVEF: Every report')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Change LVEF' }).click();
		await expect.element(page.getByRole('button', { name: 'LVEF: Every report' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('keeps cards over the budget under a collapsed More decisions', async () => {
		render(RulesStep, { cards: [value('A')], more: [value('B'), value('C')], onContinue: vi.fn() });
		await expect.element(page.getByRole('button', { name: 'B: Every report' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'More decisions (2)' }).click();
		await expect.element(page.getByRole('button', { name: 'B: Every report' })).toBeInTheDocument();
	});

	it('shows a group under More collapsed; expanded, each card in it is choosable', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [], more: [group([value('HR'), value('BSA')])], onContinue });
		await page.getByRole('button', { name: 'More decisions (2)' }).click();
		const toggle = page.getByRole('button', { name: 'Seen in one report: HR, BSA' });
		await expect.element(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect.element(page.getByRole('button', { name: 'BSA: Not needed' })).not.toBeInTheDocument();
		await toggle.click();
		await page.getByRole('button', { name: 'BSA: Not needed' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'value', key: 'BSA', choice: { need: 'not_needed' }, source: 'creation' }]);
	});

	it('Edit wording opens the wording fields and records the written wording', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [concept()], onContinue });
		await expect.element(page.getByText('Usually: “No previous imaging.”')).toBeInTheDocument();
		await expect.element(page.getByText(`Left out when ${PRIOR}.`)).toBeInTheDocument();
		await page.getByRole('button', { name: 'Comparison with previous imaging: Edit wording' }).click();
		await userEvent.fill(page.getByLabelText('When it applies'), 'Compared with the {study} of {date}.');
		await page.getByRole('button', { name: 'Use this wording' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'concept', key: 'comparison', source: 'creation',
			choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with the {study} of {date}.', condition: PRIOR, dictated: false } }]);
	});

	it('asks which contrast state is usual, shows both wordings and the setup, never pre-ticked', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [usual()], onContinue });
		await expect.element(page.getByText("From the study setup: 'CT abdomen'")).toBeInTheDocument();
		await expect.element(page.getByText('Given: “Post contrast.”')).toBeInTheDocument();
		await expect.element(page.getByText('Not given: “Non-contrast.”')).toBeInTheDocument();
		const given = page.getByRole('button', { name: 'Is contrast usually given for this scan?: Usually given' });
		const notGiven = page.getByRole('button', { name: 'Is contrast usually given for this scan?: Usually not given' });
		await expect.element(given).toHaveAttribute('aria-pressed', 'false');
		await expect.element(notGiven).toHaveAttribute('aria-pressed', 'false');
		await notGiven.click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'concept', key: 'contrast', source: 'creation',
			choice: { use: true, default: 'Non-contrast.', when_met: 'Post contrast.', condition: GIVEN, dictated: false } }]);
	});

	it('Edit wording moves focus into the fields; empty wording cannot be used', async () => {
		render(RulesStep, { cards: [concept()], notice: 'Heads up.', onContinue: vi.fn() });
		await expect.element(page.getByRole('status')).toHaveTextContent('Heads up.');
		await page.getByRole('button', { name: 'Comparison with previous imaging: Edit wording' }).click();
		await expect.element(page.getByLabelText('Usually')).toHaveFocus();
		const use = page.getByRole('button', { name: 'Use this wording' });
		await expect.element(use).not.toBeDisabled();
		await userEvent.clear(page.getByLabelText('Usually'));
		await expect.element(use).toBeDisabled();
	});

	it('a fragment cannot be used and the hint says why', async () => {
		render(RulesStep, { cards: [concept()], onContinue: vi.fn() });
		await page.getByRole('button', { name: 'Comparison with previous imaging: Edit wording' }).click();
		await userEvent.fill(page.getByLabelText('When it applies'), 'compared with {date}');
		await expect.element(page.getByRole('button', { name: 'Use this wording' })).toBeDisabled();
		await expect.element(page.getByText('Write it as a full sentence.')).toBeInTheDocument();
		await userEvent.fill(page.getByLabelText('When it applies'), 'Compared with {date}.');
		await expect.element(page.getByRole('button', { name: 'Use this wording' })).not.toBeDisabled();
		await expect.element(page.getByText('Write it as a full sentence.')).not.toBeInTheDocument();
	});

	it('adds a required value', async () => {
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('ECV')], onContinue });
		await userEvent.fill(page.getByLabelText('Add a value'), 'Heart rate');
		await page.getByRole('button', { name: '+ Add' }).click();
		await page.getByRole('button', { name: 'Continue' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'value', key: 'Heart rate', choice: { need: 'every' }, source: 'creation' }]);
	});

	it('Skip records the defaults; review mode records first-use answers and has no Skip', async () => {
		const onSkip = vi.fn();
		const { unmount } = render(RulesStep, { cards: [], defaults: [{ kind: 'value', key: 'LVEF', choice: { need: 'every' } }], onContinue: vi.fn(), onSkip });
		await page.getByRole('button', { name: 'Skip' }).click();
		expect(onSkip).toHaveBeenCalledWith([{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, source: 'default' }]);
		unmount();
		const onContinue = vi.fn();
		render(RulesStep, { cards: [value('LVEF', 'every')], mode: 'review', onContinue });
		await expect.element(page.getByRole('button', { name: 'Skip' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'LVEF: Not needed' }).click();
		await page.getByRole('button', { name: 'Apply' }).click();
		expect(onContinue).toHaveBeenCalledWith([{ kind: 'value', key: 'LVEF', choice: { need: 'not_needed' }, source: 'first_use_review' }]);
	});
});
