import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import ChatCards from './ChatCards.svelte';
import type { DecisionCard } from '$lib/template-rules/types';
import type { ProposalCard } from './types';

const value: DecisionCard = {
	id: 'value:Width', kind: 'value', step: 'chat', title: 'Width', evidence: [], ledger_kind: 'value', key: 'Width',
	choices: [
		{ id: 'every', label: 'Every report', choice: { need: 'every' } },
		{ id: 'not_needed', label: 'Not needed', choice: { need: 'not_needed' } }
	],
	selected: null, rank: 1
};
const normal: DecisionCard = {
	id: 'normal:Upper', kind: 'normal', step: 'chat', title: 'Upper: alpha', evidence: [], ledger_kind: 'normal',
	key: 'Upper :: alpha', choices: [{ id: 'write', label: 'Write my own', choice: null }], selected: null, rank: 4,
	wording: { text: 'Alpha looks fine.' }
};
const proposal: ProposalCard = {
	id: 'proposal:1', kind: 'proposal', title: 'Make this change? The Upper paragraph is now called Top.',
	apply: { kind: 'layout', op: { op: 'rename_paragraph', paragraph: 'Upper', to: 'Top' } }
};

describe('ChatCards', () => {
	it('a decision card answers with its ledger change, nothing pre-selected', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [value], onAnswer });
		await page.getByRole('button', { name: 'Not needed' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'value', key: 'Width', choice: { need: 'not_needed' } });
		await expect.element(page.getByRole('button', { name: 'Every report' })).not.toBeInTheDocument();
	});

	it('a wording card is prefilled and sends the edited wording', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [normal], onAnswer });
		await page.getByRole('button', { name: 'Write my own' }).click();
		const input = page.getByLabelText('Wording');
		await expect.element(input).toHaveValue('Alpha looks fine.');
		await input.fill('Alpha is fine.');
		await page.getByRole('button', { name: 'Use this wording' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'normal', key: 'Upper :: alpha', choice: { text: 'Alpha is fine.' } });
	});

	it('a usual-state card (contrast, no clear majority) answers with the chosen state', async () => {
		const usual: DecisionCard = {
			id: 'concept:contrast', kind: 'concept', step: 'chat', title: 'Is contrast usually given for this scan?',
			evidence: [], ledger_kind: 'concept', key: 'contrast', selected: null, rank: 2,
			choices: [
				{ id: 'usual:given', label: 'Usually given', choice: { use: true, default: 'A.', when_met: 'B.', condition: 'c2', dictated: false } },
				{ id: 'usual:not_given', label: 'Usually not given', choice: { use: true, default: 'B.', when_met: 'A.', condition: 'c1', dictated: false } }
			]
		};
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [usual], onAnswer });
		await page.getByRole('button', { name: 'Usually not given' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'concept', key: 'contrast', choice: { use: true, default: 'B.', when_met: 'A.', condition: 'c1', dictated: false } });
	});

	it('a forget choice is sent as is (the backend removes the entry)', async () => {
		const unmatched: DecisionCard = { ...value, id: 'unmatched:Width', choices: [{ id: 'forget', label: 'Forget this decision', choice: { forget: true } }] };
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [unmatched], onAnswer });
		await page.getByRole('button', { name: 'Forget this decision' }).click();
		expect(onAnswer).toHaveBeenCalledWith({ kind: 'value', key: 'Width', choice: { forget: true } });
	});

	it('wording the server would refuse is flagged and not sent', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [normal], onAnswer });
		await page.getByRole('button', { name: 'Write my own' }).click();
		await page.getByLabelText('Wording').fill('Alpha is {size}.');
		await page.getByRole('button', { name: 'Use this wording' }).click();
		expect(onAnswer).not.toHaveBeenCalled();
		await expect.element(page.getByText('Leave out values to fill in.')).toBeInTheDocument();
	});

	it('a parked habit card is shown with no choices', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [{ id: 'habit:1', kind: 'habit', title: 'Saved as a habit to set up: when X, say Y', instruction: 'x' }], onAnswer });
		await expect.element(page.getByText('Saved as a habit to set up: when X, say Y')).toBeInTheDocument();
		await expect.element(page.getByText('Nothing in the template changed for it.')).toBeInTheDocument();
		expect(onAnswer).not.toHaveBeenCalled();
	});

	it('a proposal card applies on tap, or is left alone without a call', async () => {
		const onAnswer = vi.fn();
		render(ChatCards, { cards: [proposal, { ...proposal, id: 'proposal:2' }], onAnswer });
		await page.getByRole('button', { name: 'Apply' }).first().click();
		expect(onAnswer).toHaveBeenCalledWith({ proposal: proposal.apply });
		await page.getByRole('button', { name: 'Leave as is' }).click();
		expect(onAnswer).toHaveBeenCalledTimes(1);
		await expect.element(page.getByText('Left as is')).toBeInTheDocument();
	});
});
