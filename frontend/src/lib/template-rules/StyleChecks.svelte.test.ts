import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import StyleChecks from './StyleChecks.svelte';
import type { DecisionCard, SheetChecksResponse } from './types';

const fixedCard: DecisionCard = {
	id: 'fixed:no previous imaging available', kind: 'fixed', step: 'style', title: 'No previous imaging available.', evidence: [],
	ledger_kind: 'fixed', key: 'No previous imaging available.', selected: null, rank: 3,
	choices: [
		{ id: 'always', label: 'Always the same', choice: { keep: 'always' } },
		{ id: 'dictated', label: 'Only when dictated', choice: { keep: 'dictated' } },
		{ id: 'remove', label: 'Remove', choice: { keep: 'remove' } }
	]
};
const uncoveredCard: DecisionCard = {
	id: 'uncovered:liver :: gallbladder', kind: 'uncovered', step: 'style', title: 'Liver: gallbladder', evidence: [],
	ledger_kind: 'normal', key: 'Liver :: gallbladder', selected: null, rank: 5,
	choices: [{ id: 'add', label: 'Add wording', choice: null }, { id: 'leave', label: 'Leave unmentioned', choice: { text: '' } }]
};
const checks = (): SheetChecksResponse => ({
	success: true, errors: [], stale_quotes: [], unmatched_cards: [], duplicate_cards: [],
	fixed_cards: [structuredClone(fixedCard)],
	uncovered_cards: [structuredClone(uncoveredCard)],
	normal_report: [{ section: 'FINDINGS', header: 'Findings:', sentences: [
		{ key: 'Liver :: liver', text: 'The liver is normal in size.', kind: 'normal', paragraph: 'Liver' }] }]
});

describe('StyleChecks', () => {
	it('an always-printed line is one tap', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), onChange });
		await expect.element(page.getByText('“No previous imaging available.”')).toBeInTheDocument();
		await page.getByRole('button', { name: 'No previous imaging available.: Only when dictated' }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'fixed', key: 'No previous imaging available.', choice: { keep: 'dictated' }, source: 'creation' }]);
	});

	it('the normal report: tap a sentence to edit it or remove it', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), source: 'first_use_review', onChange });
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await expect.element(page.getByLabelText('Edit sentence')).toHaveFocus();
		await userEvent.fill(page.getByLabelText('Edit sentence'), 'The liver is unremarkable.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: liver', choice: { text: 'The liver is unremarkable.' }, source: 'first_use_review' }]);
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await page.getByRole('button', { name: 'Remove', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: liver', choice: { text: '' }, source: 'first_use_review' }]);
	});

	it('a covered structure without a normal: add wording or leave unmentioned', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), onChange });
		await page.getByRole('button', { name: 'Liver: gallbladder: Add wording' }).click();
		await expect.element(page.getByLabelText('Wording for Liver: gallbladder')).toHaveFocus();
		await userEvent.fill(page.getByLabelText('Wording for Liver: gallbladder'), 'The gallbladder is unremarkable.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: gallbladder', choice: { text: 'The gallbladder is unremarkable.' }, source: 'creation' }]);
		await page.getByRole('button', { name: 'Liver: gallbladder: Leave unmentioned' }).click();
		expect(onChange).toHaveBeenLastCalledWith([{ kind: 'normal', key: 'Liver :: gallbladder', choice: { text: '' }, source: 'creation' }]);
	});

	it('a line that may state a decided concept twice: remove it or keep both (a NEGATIVE acts on itself)', async () => {
		const onChange = vi.fn();
		const dup: DecisionCard = { id: 'duplicate:liver :: "no prior study."', kind: 'duplicate', step: 'style', title: 'No prior study.',
			evidence: [], note: 'May be stated twice: Comparison with previous imaging', ledger_kind: 'normal', key: 'Liver :: "No prior study."',
			selected: null, rank: 3, choices: [{ id: 'remove', label: 'Remove this line', choice: { text: '' } },
				{ id: 'keep', label: 'Keep both', choice: { text: 'No prior study.' } }] };
		render(StyleChecks, { checks: { ...checks(), duplicate_cards: [dup] }, onChange });
		await expect.element(page.getByText('May be stated twice: Comparison with previous imaging')).toBeInTheDocument();
		await page.getByRole('button', { name: 'No prior study.: Remove this line' }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'normal', key: 'Liver :: "No prior study."', choice: { text: '' }, source: 'creation' }]);
	});

	it('an entry that could not be placed shows its note and can be forgotten', async () => {
		const onChange = vi.fn();
		const unmatched: DecisionCard = { ...structuredClone(fixedCard), id: 'fixed:gone', title: 'A line the sheet lacks.', key: 'A line the sheet lacks.',
			step: 'review', note: "This rule couldn't be placed in your template when it was last saved. Choose again or remove it.",
			choices: [{ id: 'dictated', label: 'Only when dictated', choice: { keep: 'dictated' } }, { id: 'remove', label: 'Remove', choice: { keep: 'remove' } },
				{ id: 'forget', label: 'Forget this decision', choice: { forget: true } }] };
		render(StyleChecks, { checks: { ...checks(), unmatched_cards: [unmatched] }, onChange });
		await expect.element(page.getByText("This rule couldn't be placed", { exact: false })).toBeInTheDocument();
		await page.getByRole('button', { name: 'A line the sheet lacks.: Forget this decision' }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'fixed', key: 'A line the sheet lacks.', choice: { forget: true }, source: 'creation' }]);
	});

	it('nothing can be tapped while busy', async () => {
		render(StyleChecks, { checks: checks(), busy: true, onChange: vi.fn() });
		await expect.element(page.getByRole('button', { name: 'No previous imaging available.: Remove' })).toBeDisabled();
		await expect.element(page.getByRole('button', { name: 'Edit: The liver is normal in size.' })).toBeDisabled();
	});

	it('an unmatched concept is edited with its two wordings and gives a valid change', async () => {
		const onChange = vi.fn();
		const PRIOR = 'the dictation names a previous imaging study for comparison';
		const concept: DecisionCard = { id: 'concept:comparison', kind: 'concept', step: 'review', title: 'Comparison with previous imaging',
			evidence: [], ledger_kind: 'concept', key: 'comparison', selected: null, rank: 2, note: "This rule couldn't be placed.",
			wording: { default: 'No previous imaging.', when_met: 'Compared with {date}.', condition: PRIOR },
			choices: [{ id: 'keep', label: 'Keep', choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with {date}.', condition: PRIOR, dictated: false } },
				{ id: 'edit', label: 'Edit wording', choice: null },
				{ id: 'not_used', label: 'Not used', choice: { use: false, default: '', when_met: '', condition: '', dictated: false } }] };
		render(StyleChecks, { checks: { ...checks(), unmatched_cards: [concept] }, onChange });
		await page.getByRole('button', { name: 'Comparison with previous imaging: Edit wording' }).click();
		await expect.element(page.getByLabelText('Usually')).toHaveFocus();
		await userEvent.fill(page.getByLabelText('When it applies'), 'Compared with the study of {date}.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		expect(onChange).toHaveBeenCalledWith([{ kind: 'concept', key: 'comparison', source: 'creation',
			choice: { use: true, default: 'No previous imaging.', when_met: 'Compared with the study of {date}.', condition: PRIOR, dictated: false } }]);
	});

	it('Cancel and Escape close the sentence editor without a change', async () => {
		const onChange = vi.fn();
		render(StyleChecks, { checks: checks(), onChange });
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await page.getByRole('button', { name: 'Cancel' }).click();
		await expect.element(page.getByLabelText('Edit sentence')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await userEvent.keyboard('{Escape}');
		await expect.element(page.getByLabelText('Edit sentence')).not.toBeInTheDocument();
		expect(onChange).not.toHaveBeenCalled();
	});

	it('a failed apply keeps the draft open and shows the error', async () => {
		const onChange = vi.fn(async () => false);
		render(StyleChecks, { checks: checks(), error: 'Could not apply that choice', onChange });
		await page.getByRole('button', { name: 'Edit: The liver is normal in size.' }).click();
		await userEvent.fill(page.getByLabelText('Edit sentence'), 'The liver is unremarkable.');
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		await expect.element(page.getByLabelText('Edit sentence')).toHaveValue('The liver is unremarkable.');
		await expect.element(page.getByRole('alert')).toHaveTextContent('Could not apply that choice');
	});

	it('renders nothing without checks', async () => {
		render(StyleChecks, { checks: null, onChange: vi.fn() });
		await expect.element(page.getByText('Your normal report')).not.toBeInTheDocument();
	});
});
