import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackItem, StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});
const GROUPS = ['Technique', 'Liver', 'Kidneys', 'Spleen', 'Other findings', 'General', 'Conclusion'];
const PILLS = ['Liver', 'Kidneys', 'Spleen'];
const base = () => ({ groups: GROUPS, pillRegions: PILLS, onMove: vi.fn(), onEditLine: vi.fn(), onConfirm: vi.fn() });
const row = (id: string, sentences: string[], extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'finding', region: 'Liver', question: 'Biliary dilatation?', why: 'A cyst can obstruct.', sentences, answered: false, ...extra
});

describe('HybridStackView v2', () => {
	it('abnormal regions in the scratchpad, normals in the tray, rows asked with the sentence on the button', async () => {
		const props = { ...base(), onAnswer: vi.fn() };
		render(HybridStackView, {
			...props,
			units: [
				u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'], structure: 'liver' }),
				u(1, 'The kidneys are normal.', 'Kidneys', { covers: ['Kidneys'] })
			],
			items: [row('a', ['No biliary dilatation.'])],
			namedNormals: true
		});
		await expect.element(page.getByRole('heading', { name: 'Liver' })).toBeInTheDocument();
		await expect.element(page.getByRole('heading', { name: 'Kidneys' })).not.toBeInTheDocument();
		await expect.element(page.getByText('Remainder of liver: assumed normal')).not.toBeInTheDocument();   // never named
		await expect.element(page.getByText('Kidneys', { exact: true })).toHaveAttribute('data-state', 'dictated');
		await expect.element(page.getByText('Spleen', { exact: true })).toHaveAttribute('data-state', 'assumed');
		await expect.element(page.getByText('Biliary dilatation?')).toBeInTheDocument();
		await page.getByRole('button', { name: '✓ Normal' }).click();
		expect(props.onAnswer).toHaveBeenCalledWith('a');
	});

	it('the referral row leads; one "✓ Normal" adds what is listed; × removes one; a tapped row turns green', async () => {
		const props = { ...base(), onAnswer: vi.fn(), onRemoveSentence: vi.fn() };
		const ref = row('r', ['The appendix is normal.'], { kind: 'referral', region: 'Appendix', question: 'Appendix normal or inflamed?' });
		const two = row('b', ['No torsion.', 'No rupture.'], { region: 'Liver' });
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })];
		const r = render(HybridStackView, { ...props, units, items: [ref, two] });
		await expect.element(page.getByText('Referral', { exact: true })).toBeInTheDocument();
		await expect.element(page.getByTitle('Add: No torsion. No rupture.')).toBeInTheDocument();
		await page.getByLabelText('Remove No rupture.').click();
		expect(props.onRemoveSentence).toHaveBeenCalledWith('No rupture.');
		r.rerender({ ...props, units, items: [ref, two], removed: ['No rupture.'] });
		await expect.element(page.getByTitle('Add: No torsion.')).toBeInTheDocument();   // adds only what is left
		r.rerender({ ...props, units, items: [ref, two], tapped: ['r'] });
		await expect.element(page.getByText(/✓ The appendix is normal\./)).toBeInTheDocument();
	});

	it('the quiet line shows what will be reported, three at a time', async () => {
		render(HybridStackView, {
			...base(), onRemoveSentence: vi.fn(),
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			assumed: { Liver: ['No biliary dilatation.', 'The portal vein is patent.', 'No other lesion.', 'The gallbladder is normal.', 'No ascites.'] }
		});
		await expect.element(page.getByText('Will also be reported')).toBeInTheDocument();
		await expect.element(page.getByText('The portal vein is patent.')).toBeInTheDocument();
		await expect.element(page.getByText('No ascites.')).not.toBeInTheDocument();
		await page.getByText('+2 more').click();
		await expect.element(page.getByText('No ascites.')).toBeInTheDocument();
	});

	it('shows the live strip and lets a line be edited and committed with Enter', async () => {
		const props = base();
		render(HybridStackView, {
			...props,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			pending: ['The spleen is normal.'],
			ghost: 'kidneys are'
		});
		await expect.element(page.getByText('The spleen is normal.')).toBeInTheDocument();
		await expect.element(page.getByText('kidneys are')).toBeInTheDocument();
		await page.getByText('An 8 mm liver cyst.').click();
		await page.getByLabelText('Edit line').fill('A 9 mm liver cyst.');
		await userEvent.keyboard('{Enter}');
		expect(props.onEditLine).toHaveBeenCalledWith(0, null, 'A 9 mm liver cyst.');
	});

	it('dictation goes into the open line at the caret', async () => {
		const props = base();
		const r = render(HybridStackView, { ...props, units: [u(0, 'A liver cyst.', 'Liver', { abnormal: true })] });
		await page.getByText('A liver cyst.').click();
		const input = page.getByLabelText('Edit line').element() as HTMLInputElement;
		input.setSelectionRange(2, 2);
		r.rerender({ ...props, units: [u(0, 'A liver cyst.', 'Liver', { abnormal: true })], incoming: { seq: 1, text: '9 mm' } });
		await expect.element(page.getByLabelText('Edit line')).toHaveValue('A 9 mm liver cyst.');
	});

	it('a region that turns abnormal leaves the tray', async () => {
		const props = base();
		const r = render(HybridStackView, { ...props, units: [u(0, 'The kidneys are normal.', 'Kidneys', { covers: ['Kidneys'] })] });
		await expect.element(page.getByText('Kidneys', { exact: true })).toHaveAttribute('data-state', 'dictated');
		r.rerender({ ...props, units: [u(0, 'A 4 mm left renal calculus.', 'Kidneys', { abnormal: true })] });
		await expect.element(page.getByRole('heading', { name: 'Kidneys' })).toBeInTheDocument();
		await new Promise((res) => setTimeout(res, 600));
		expect(document.querySelectorAll('[data-state]').length).toBe(2); // Liver, Spleen
	});

	it('a dashed tray pill shows the sentences it will report', async () => {
		render(HybridStackView, { ...base(), units: [], assumed: { Spleen: ['The spleen is normal in size.'] } });
		await page.getByText('Spleen', { exact: true }).click();
		await expect.element(page.getByText('The spleen is normal in size.')).toBeInTheDocument();
	});

	it('a typed finding is appended on Enter', async () => {
		const onAppend = vi.fn();
		render(HybridStackView, { ...base(), onAppend, units: [] });
		await page.getByLabelText('New line').fill('The spleen is enlarged at 15 cm.');
		await userEvent.keyboard('{Enter}');
		expect(onAppend).toHaveBeenCalledWith('The spleen is enlarged at 15 cm.');
	});

	it('the gate bar: referral questions block Confirm; finding checks never do, and Skip folds one', async () => {
		const props = { ...base(), onSkip: vi.fn() };
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')];
		const ref = row('r', ['The appendix is normal.'], { kind: 'referral', region: '', question: 'Appendix normal?' });
		const check = row('a', ['No biliary dilatation.']);
		const r = render(HybridStackView, { ...props, units, conclusion: { kind: 'dictated' }, items: [ref, check], namedNormals: true });
		await expect.element(page.getByText('1 referral question open')).toBeInTheDocument();
		await expect.element(page.getByText('1 check unanswered (not stated)')).toBeInTheDocument();
		await expect.element(page.getByText('2 regions assumed normal (no sheet yet)')).toBeInTheDocument();   // by name (no sheet)
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeDisabled();
		await page.getByRole('button', { name: 'Skip' }).click();
		expect(props.onSkip).toHaveBeenCalledWith('a');
		r.rerender({ ...props, units, conclusion: { kind: 'dictated' }, items: [ref, check], skipped: ['r'], namedNormals: true });
		await expect.element(page.getByText('0 referral questions open')).toBeInTheDocument();   // "Not assessed"
		await page.getByRole('button', { name: 'Confirm' }).click();
		expect(props.onConfirm).toHaveBeenCalled();
	});

	it('Confirm waits for a conclusion; with none, the field asks for one and offers a draft', async () => {
		const onDraftRefresh = vi.fn();
		render(HybridStackView, { ...base(), onDraftRefresh, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })], conclusion: { kind: 'none', failed: true } });
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeDisabled();
		await expect.element(page.getByPlaceholder('Type or dictate a conclusion')).toBeInTheDocument();
		await expect.element(page.getByText(/could not be made/)).toBeInTheDocument();
		await page.getByText('Draft one').click();
		expect(onDraftRefresh).toHaveBeenCalled();
	});

	it('shows an editable AI draft and the refresh prompt when findings changed', async () => {
		const onDraftRefresh = vi.fn();
		render(HybridStackView, {
			...base(),
			onDraftRefresh,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			conclusion: { kind: 'draft', text: 'Simple hepatic cyst.', stale: true, edited: false }
		});
		await expect.element(page.getByText('AI draft')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Conclusion draft')).toHaveValue('Simple hepatic cyst.');
		await page.getByText('Findings changed — refresh?').click();
		expect(onDraftRefresh).toHaveBeenCalled();
	});

	it('a review that failed on both models is shown at the gate, never silent', async () => {
		render(HybridStackView, { ...base(), units: [u(0, 'A liver cyst.', 'Liver', { abnormal: true })], reviewFailed: true });
		await expect.element(page.getByText('checks unavailable: review the scan as usual')).toBeInTheDocument();
	});

	it('a sentence spanning regions stays whole under one joined heading', async () => {
		render(HybridStackView, {
			...base(), groups: ['Technique', 'Lungs', 'Pleura', 'Other findings', 'General', 'Conclusion'], pillRegions: ['Lungs', 'Pleura'],
			units: [u(0, 'A small left pneumothorax and minor basal contusion.', 'Pleura', {
				abnormal: true, parts: [{ text: 'A small left pneumothorax', group: 'Pleura', abnormal: true },
					{ text: 'and minor basal contusion.', group: 'Lungs', abnormal: true }]
			})]
		});
		await expect.element(page.getByRole('heading', { name: 'Lungs · Pleura' })).toBeInTheDocument();
		await expect.element(page.getByText('A small left pneumothorax and minor basal contusion.')).toBeInTheDocument();
		await expect.element(page.getByRole('heading', { name: 'Pleura', exact: true })).not.toBeInTheDocument();
	});

	it('a region with nothing left to assume leaves the normal section once the check has answered', async () => {
		const props = { ...base(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })], assumed: { Spleen: ['The spleen is normal.'] } };
		const r = render(HybridStackView, props);
		await expect.element(page.getByText('Kidneys', { exact: true })).toBeInTheDocument();   // not answered yet: kept
		r.rerender({ ...props, assumedReady: true });
		await expect.element(page.getByText('Kidneys', { exact: true })).not.toBeInTheDocument();
		await expect.element(page.getByText('Spleen', { exact: true })).toBeInTheDocument();
	});

	it('shows placeholder rows while the end-of-dictation review runs', async () => {
		const props = { ...base(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })] };
		const r = render(HybridStackView, { ...props, reviewing: true });
		await expect.element(page.getByTestId('review-skeleton')).toBeInTheDocument();
		r.rerender({ ...props, reviewing: false });
		await expect.element(page.getByTestId('review-skeleton')).not.toBeInTheDocument();
	});

	it('"Dictate finding" opens a box in the row and starts the mic; Enter adds the finding and folds the row', async () => {
		const onAbnormal = vi.fn();
		const onToggleMic = vi.fn();
		render(HybridStackView, { ...base(), onAbnormal, onToggleMic, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			items: [row('a', ['No biliary dilatation.'])] });
		await page.getByRole('button', { name: 'Dictate finding' }).click();
		expect(onToggleMic).toHaveBeenCalledTimes(1);
		await page.getByLabelText('Abnormal finding').fill('Mild intrahepatic biliary dilatation.');
		await userEvent.keyboard('{Enter}');
		expect(onAbnormal).toHaveBeenCalledWith('a', 'Mild intrahepatic biliary dilatation.');
	});

	it('a dictated normal is edited in place, like any line', async () => {
		const props = base();
		render(HybridStackView, { ...props, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }),
			u(1, 'The kidneys are normal.', 'Kidneys', { covers: ['Kidneys'] })] });
		await page.getByTitle('Click to edit: The kidneys are normal.').click();
		await page.getByLabelText('Edit line').fill('The kidneys are normal in size.');
		await userEvent.keyboard('{Enter}');
		expect(props.onEditLine).toHaveBeenCalledWith(1, null, 'The kidneys are normal in size.');
	});

	it('an edited pre-written normal becomes the radiologist\'s own words', async () => {
		const onEditAssumed = vi.fn();
		render(HybridStackView, { ...base(), onEditAssumed, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			assumed: { Liver: ['No biliary dilatation.'] } });
		await page.getByText('No biliary dilatation.').click();
		await page.getByLabelText('Edit normal').fill('No intrahepatic biliary dilatation.');
		await userEvent.keyboard('{Enter}');
		expect(onEditAssumed).toHaveBeenCalledWith('No biliary dilatation.', 'No intrahepatic biliary dilatation.');
	});

	it('before the review, a referral row is a reminder only: no answers, no buttons', async () => {
		const ref = row('r', ['The appendix is normal.'], { kind: 'referral', region: '', question: 'Appendix normal?' });
		render(HybridStackView, { ...base(), units: [], items: [ref], actionsReady: false });
		await expect.element(page.getByText('answer it in your dictation')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: '✓ Normal' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Not assessed' })).not.toBeInTheDocument();
	});
});
