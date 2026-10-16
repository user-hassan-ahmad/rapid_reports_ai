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
	it('a template row asks the template question: Yes / No write its sentence, Not assessed writes nothing', async () => {
		const props = { ...base(), onAnswerTemplate: vi.fn(), onSkip: vi.fn(), onAnswer: vi.fn() };
		const tpl = row('t', ['The cyst is septated.', 'No septation.'], {
			kind: 'template', question: 'Septation?', why: 'Your template asks this when a liver cyst is reported.',
			yes: 'The cyst is septated.', no: 'No septation.'
		});
		render(HybridStackView, { ...props, units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] })], items: [tpl] });
		await expect.element(page.getByText('Septation?')).toBeInTheDocument();
		await page.getByRole('button', { name: 'No', exact: true }).click();
		expect(props.onAnswerTemplate).toHaveBeenCalledWith('t', 'no');
		await page.getByRole('button', { name: 'Yes', exact: true }).click();
		expect(props.onAnswerTemplate).toHaveBeenCalledWith('t', 'yes');
		await page.getByRole('button', { name: 'Not assessed' }).click();
		expect(props.onSkip).toHaveBeenCalledWith('t');
		expect(props.onAnswer).not.toHaveBeenCalled();
	});

	it('an answered template row shows the sentence chosen', async () => {
		render(HybridStackView, {
			...base(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] })], tapped: ['t'],
			items: [row('t', ['No septation.'], { kind: 'template', question: 'Septation?', yes: 'The cyst is septated.', no: 'No septation.' })]
		});
		await expect.element(page.getByText('✓ No septation.')).toBeInTheDocument();
	});
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

	it('a flagged normal shows an amber check marker on the region card and in the tray, and stays removable (R1)', async () => {
		const props = { ...base(), onRemoveSentence: vi.fn() };
		const title = 'May conflict with your dictation: confirm or remove';
		render(HybridStackView, {
			...props,
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			assumed: { Liver: ['No biliary dilatation.', 'The portal vein is patent.', 'No other lesion.', 'No ascites.'],
				Kidneys: ['The kidneys are normal.'], Spleen: ['The spleen is normal.'] },
			flagged: { Liver: ['No ascites.'], Kidneys: ['The kidneys are normal.'], Spleen: ['No biliary dilatation.'] }, assumedReady: true
		});
		// on the card: a flagged sentence is never hidden behind "+N more"
		const card = page.getByRole('region', { name: 'Liver' });
		await expect.element(card.getByText('No ascites.')).toBeInTheDocument();
		await expect.element(card.getByTitle(title, { exact: true })).toBeInTheDocument();
		expect(card.getByTitle(title, { exact: true }).elements()).toHaveLength(1);   // flagged in Spleen, not in Liver: no marker
		// in the tray: the pill carries the marker before it is opened; opened, the sentence does
		const pill = page.getByRole('button', { name: /^Kidneys/ });
		await expect.element(pill).toHaveAttribute('data-flagged', 'true');
		await expect.element(page.getByRole('button', { name: /^Spleen/ })).not.toHaveAttribute('data-flagged');
		await pill.click();
		const tray = page.getByRole('region', { name: 'Normal regions' });
		await expect.element(tray.getByText('The kidneys are normal.')).toBeInTheDocument();
		await expect.element(tray.getByTitle(title, { exact: true })).toBeInTheDocument();
		await page.getByLabelText('Remove The kidneys are normal.').click();
		expect(props.onRemoveSentence).toHaveBeenCalledWith('The kidneys are normal.');
	});

	it('a dictated-normal region shows "Normal, as you said" and the sheet sentences left as "will be reported" (R2)', async () => {
		const props = { ...base(), onRemoveSentence: vi.fn() };
		render(HybridStackView, {
			...props,
			units: [u(0, 'The right kidney is normal.', 'Kidneys', { covers: ['Kidneys'] })],
			assumed: { Kidneys: ['The left kidney is normal.'], Liver: ['The liver is normal.'] }, assumedReady: true
		});
		const tray = page.getByRole('region', { name: 'Normal regions' });
		await expect.element(tray.getByText('Normal, as you said')).toBeInTheDocument();
		await expect.element(tray.getByText('Kidneys', { exact: true })).toHaveAttribute('data-state', 'dictated');
		await expect.element(tray.getByText('Kidneys · will be reported')).toBeInTheDocument();
		await expect.element(tray.getByText('The left kidney is normal.')).toBeInTheDocument();
		await expect.element(page.getByText('2 assumed normal')).toBeInTheDocument();   // Kidneys' sentence counts
		await page.getByLabelText('Remove The left kidney is normal.').click();
		expect(props.onRemoveSentence).toHaveBeenCalledWith('The left kidney is normal.');
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

	it('a template paragraph covering several structures shows one assumed chip per structure (sub-pills)', async () => {
		const props = { ...base(), onRemoveSentence: vi.fn() };
		render(HybridStackView, {
			...props, units: [],
			assumed: { Spleen: ['Normal cardiac chambers.', 'No lung nodule.', 'No osseous lesion.', 'No incidental finding.'] },
			structures: { Spleen: { 'Cardiac chambers': ['Normal cardiac chambers.'], Lungs: ['No lung nodule.'], Bones: ['No osseous lesion.'] } },
			assumedReady: true
		});
		const tray = page.getByRole('region', { name: 'Normal regions' });
		for (const name of ['Cardiac chambers', 'Lungs', 'Bones', 'Spleen']) {
			await expect.element(tray.getByRole('button', { name, exact: true })).toHaveAttribute('data-state', 'assumed');
		}
		await tray.getByRole('button', { name: 'Lungs', exact: true }).click();
		await expect.element(tray.getByText('Lungs · will be reported')).toBeInTheDocument();
		await expect.element(tray.getByText('No osseous lesion.')).not.toBeInTheDocument();
		await page.getByLabelText('Remove No lung nodule.').click();
		expect(props.onRemoveSentence).toHaveBeenCalledWith('No lung nodule.');
		await expect.element(page.getByText('4 assumed normal')).toBeInTheDocument();   // the count is unchanged
	});

	it('a dictated-normal split paragraph: answered structures go green, the rest stay assumed chips', async () => {
		render(HybridStackView, {
			...base(),
			units: [u(0, 'No lung nodules.', 'Spleen', { covers: ['Spleen'] })],
			assumed: { Spleen: ['Normal cardiac chambers.', 'No osseous lesion.'] },
			structures: { Spleen: { 'Cardiac chambers': ['Normal cardiac chambers.'], Lungs: ['No lung nodule.'], Bones: ['No osseous lesion.'] } },
			assumedReady: true
		});
		const tray = page.getByRole('region', { name: 'Normal regions' });
		await expect.element(tray.getByText('Lungs', { exact: true })).toHaveAttribute('data-state', 'dictated');
		await expect.element(tray.getByRole('button', { name: 'Bones', exact: true })).toHaveAttribute('data-state', 'assumed');
		await expect.element(tray.getByRole('button', { name: 'Cardiac chambers', exact: true })).toBeInTheDocument();
		await expect.element(tray.getByText('Spleen · will be reported')).not.toBeInTheDocument();
	});

	it('× inside an expanded structure chip removes exactly that sentence', async () => {
		const onRemoveSentence = vi.fn();
		render(HybridStackView, {
			...base(), onRemoveSentence, units: [],
			assumed: { Spleen: ['Normal cardiac chambers.', 'No lung nodule.', 'No osseous lesion.'] },
			structures: { Spleen: { 'Cardiac chambers': ['Normal cardiac chambers.'], Lungs: ['No lung nodule.'], Bones: ['No osseous lesion.'] } },
			assumedReady: true
		});
		const tray = page.getByRole('region', { name: 'Normal regions' });
		await tray.getByRole('button', { name: 'Bones', exact: true }).click();
		await page.getByLabelText('Remove No osseous lesion.').click();
		expect(onRemoveSentence).toHaveBeenCalledTimes(1);
		expect(onRemoveSentence).toHaveBeenCalledWith('No osseous lesion.');
	});

	it('a structure named like another dictated region does not clash with it', async () => {
		render(HybridStackView, {
			...base(),
			units: [u(0, 'Normal.', 'Spleen', { covers: ['Spleen', 'Kidneys'] })],
			assumed: { Spleen: ['No bone lesion.'] },
			structures: { Spleen: { Kidneys: ['No renal stone.'], Bones: ['No bone lesion.'] } },
			assumedReady: true
		});
		const tray = page.getByRole('region', { name: 'Normal regions' });
		await expect.element(tray.getByText('Kidneys', { exact: true }).nth(1)).toHaveAttribute('data-state', 'dictated');
		await expect.element(tray.getByRole('button', { name: 'Bones', exact: true })).toBeInTheDocument();
	});

	it('a typed finding is appended on Enter', async () => {
		const onAppend = vi.fn();
		render(HybridStackView, { ...base(), onAppend, units: [] });
		await page.getByLabelText('New line').fill('The spleen is enlarged at 15 cm.');
		await userEvent.keyboard('{Enter}');
		expect(onAppend).toHaveBeenCalledWith('The spleen is enlarged at 15 cm.');
	});

	it('the gate bar: an open referral question sends Confirm to it; finding checks never do, and Skip folds one', async () => {
		const props = { ...base(), onSkip: vi.fn() };
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')];
		const ref = row('r', ['The appendix is normal.'], { kind: 'referral', region: '', question: 'Appendix normal?' });
		const check = row('a', ['No biliary dilatation.']);
		const r = render(HybridStackView, { ...props, units, conclusion: { kind: 'dictated' }, items: [ref, check], namedNormals: true });
		await expect.element(page.getByText('1 referral question open')).toBeInTheDocument();
		await expect.element(page.getByText('1 check unanswered (not stated)')).toBeInTheDocument();
		await expect.element(page.getByText('2 regions assumed normal (no sheet yet)')).toBeInTheDocument();   // by name (no sheet)
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		expect(props.onConfirm).not.toHaveBeenCalled();
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 1 of 1 · Referral question');
		await page.getByRole('button', { name: 'Exit' }).click();
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
		await page.getByRole('button', { name: 'Draft with AI' }).click();
		expect(onDraftRefresh).toHaveBeenCalled();
		await expect.element(page.getByRole('button', { name: 'Start dictating' }).first()).toBeInTheDocument();
	});

	it('the conclusion is greyed until the findings are in', async () => {
		render(HybridStackView, { ...base(), units: [], conclusion: { kind: 'waiting' } });
		await expect.element(page.getByTestId('conclusion-waiting')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Conclusion draft')).not.toBeInTheDocument();
	});

	it('a conclusion the radiologist owns gets a quiet note when the findings changed, with a suggestion to accept', async () => {
		const props = { ...base(), onNoteSuggest: vi.fn(), onNoteAccept: vi.fn(), onNoteDismiss: vi.fn(),
			units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			conclusion: { kind: 'draft', text: 'Simple hepatic cyst.', edited: true } as const };
		const r = render(HybridStackView, { ...props, conclusionNote: { added: ['A 3 cm left renal mass.'], suggestion: null, loading: false } });
		await expect.element(page.getByText('AI draft · edited')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Conclusion draft')).toHaveValue('Simple hepatic cyst.');
		await expect.element(page.getByRole('button', { name: 'Draft with AI' })).not.toBeInTheDocument();
		await page.getByText(/may not cover A 3 cm left renal mass/).click();
		expect(props.onNoteSuggest).toHaveBeenCalled();
		r.rerender({ ...props, conclusionNote: { added: [], suggestion: 'Hepatic cyst. Left renal mass.', loading: false } });
		await page.getByRole('button', { name: 'Use this' }).click();
		expect(props.onNoteAccept).toHaveBeenCalled();
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeEnabled();   // the note never blocks
	});

	it('the full review keeps the rows on screen instead of the skeleton', async () => {
		render(HybridStackView, { ...base(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })], reviewing: true,
			items: [row('a', ['No biliary dilatation.'])] });
		await expect.element(page.getByText('Biliary dilatation?')).toBeInTheDocument();
		await expect.element(page.getByTestId('review-skeleton')).not.toBeInTheDocument();
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

	it('the dictation hotkey can be recorded in settings, saved, and toggles the mic', async () => {
		localStorage.removeItem('rr_dictation_hotkey');
		const onToggleMic = vi.fn();
		render(HybridStackView, { ...base(), onToggleMic, units: [] });
		await expect.element(page.getByText('Press ⌥Space or the mic to dictate')).toBeInTheDocument();
		await page.getByLabelText('Dictation settings').click();
		await page.getByRole('button', { name: '⌥Space', exact: true }).click();
		await userEvent.keyboard('{Control>}{KeyD}{/Control}');
		await expect.element(page.getByRole('button', { name: '⌃D', exact: true })).toBeInTheDocument();
		expect(JSON.parse(localStorage.getItem('rr_dictation_hotkey') ?? '{}').code).toBe('KeyD');
		await page.getByRole('button', { name: 'Done' }).click();
		await userEvent.keyboard('{Control>}{KeyD}{/Control}');
		expect(onToggleMic).toHaveBeenCalledTimes(1);
		localStorage.removeItem('rr_dictation_hotkey');
	});

	it('an unfinished sentence is underlined; Confirm walks to it; Keep as dictated clears it and Confirm returns', async () => {
		const onCheckAnswer = vi.fn();
		const units = [u(0, 'An 8 mm liver cyst with', 'Liver', { abnormal: true })];
		const c = { key: 'truncation|x', kind: 'truncation', blocking: true, tier: 1 as const, message: 'Ends mid-sentence.', quote: 'An 8 mm liver cyst with', other: null, suggestion: '', unitId: 0 };
		const props = { ...base(), units, onCheckAnswer, conclusion: { kind: 'draft', text: 'Liver cyst.', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, checks: [c] });
		await expect.element(page.getByRole('button', { name: '1 to check · 1 blocking' })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 1 of 1 · Unfinished sentence');
		await expect.element(page.getByRole('dialog', { name: 'Unfinished sentence' })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Keep as dictated' }).click();
		expect(onCheckAnswer).toHaveBeenCalledWith('truncation|x', 'as_dictated');
		r.rerender({ ...props, checks: [c], checkAnswers: { 'truncation|x': 'as_dictated' } });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('All checked');
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		expect(props.onConfirm).toHaveBeenCalled();
	});

	it('a certain garble is a dotted advisory underline; hover shows the card and Replace edits the line', async () => {
		const onCheckAnswer = vi.fn();
		const units = [u(0, 'Dilatation of the pancreatic duck.', 'Liver', { abnormal: true })];
		const c = { key: 'garbled_phrase|duck', kind: 'garbled_phrase', blocking: false, tier: 2 as const, message: 'A misheard word.', quote: 'duck', other: null, suggestion: 'duct', unitId: 0 };
		const props = { ...base(), units, onCheckAnswer, checks: [c], conclusion: { kind: 'draft', text: 'Duct dilatation.', edited: false } as const, namedNormals: true };
		render(HybridStackView, props);
		await expect.element(page.getByRole('button', { name: '1 to check' })).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Confirm', exact: true })).toBeEnabled();   // advisory never blocks
		await page.getByText('duck', { exact: true }).hover();
		await expect.element(page.getByRole('dialog', { name: 'Possible dictation error' })).toHaveTextContent('Likely: duct');
		await page.getByRole('button', { name: 'Replace' }).click();
		expect(props.onEditLine).toHaveBeenCalledWith(0, null, 'Dilatation of the pancreatic duct.');
		expect(onCheckAnswer).toHaveBeenCalledWith('garbled_phrase|duck', 'replaced');
	});

	it('the walkthrough goes top to bottom: the referral row first, then blocking underlines; Next skips one', async () => {
		const units = [u(0, 'A 2 cm cyst in the left kidney.', 'Kidneys', { abnormal: true }), u(1, 'A tiny non-2 mm calculus.', 'Kidneys', { abnormal: true })];
		const side = { key: 's', kind: 'laterality_conflict', blocking: true, tier: 2 as const, message: 'Sides differ.', quote: 'left kidney', other: null, suggestion: '', unitId: 0 };
		const garble = { key: 'g', kind: 'garbled_phrase', blocking: true, tier: 2 as const, message: 'A word looks misheard.', quote: 'non-2 mm', other: null, suggestion: '', unitId: 1 };
		const ref = row('r', ['No hydronephrosis.'], { kind: 'referral', question: 'Obstruction?' });
		render(HybridStackView, { ...base(), units, items: [ref], checks: [garble, side], conclusion: { kind: 'draft', text: 'Right renal cyst.', edited: false } as const, namedNormals: true });
		await page.getByRole('button', { name: 'Confirm · 3 to resolve' }).click();
		const bar = page.getByTestId('walkthrough');
		await expect.element(bar).toHaveTextContent('Checking 1 of 3 · Referral question');
		await page.getByRole('button', { name: 'Next ›' }).click();
		await expect.element(bar).toHaveTextContent('Checking 1 of 3 · Sides as intended?');
		await expect.element(page.getByRole('dialog', { name: 'Sides as intended?' })).toBeInTheDocument();
		await page.getByRole('button', { name: 'Exit' }).click();
		await expect.element(page.getByTestId('walkthrough')).not.toBeInTheDocument();
	});
	it('the hover card survives the move from the words onto it, and closes after the pointer leaves it', async () => {
		const units = [u(0, 'Dilatation of the pancreatic duck.', 'Liver', { abnormal: true })];
		const c = { key: 'g', kind: 'garbled_phrase', blocking: false, tier: 2 as const, message: 'A misheard word.', quote: 'duck', other: null, suggestion: 'duct', unitId: 0 };
		render(HybridStackView, { ...base(), units, checks: [c], conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true });
		await page.getByText('duck', { exact: true }).hover();
		const card = page.getByRole('dialog', { name: 'Possible dictation error' });
		await expect.element(card).toBeInTheDocument();
		await card.hover();                                   // leaving the words for the card keeps it open
		await new Promise((r) => setTimeout(r, 500));
		await expect.element(card).toBeInTheDocument();
		await page.getByRole('heading', { name: 'Liver' }).hover();
		await expect.element(card).not.toBeInTheDocument();
	});
	it('Delete sentence removes an unfinished sentence, from the card or with D in the walkthrough', async () => {
		const units = [u(0, 'The pancreas is', 'Liver', { abnormal: true })];
		const c = { key: 'p', kind: 'truncation', blocking: true, tier: 1 as const, message: 'Unfinished.', quote: 'The pancreas is', other: null, suggestion: '', unitId: 0 };
		const props = { ...base(), units, checks: [c], conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true };
		render(HybridStackView, props);
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await userEvent.keyboard('d');
		expect(props.onEditLine).toHaveBeenCalledWith(0, null, '');
	});

	it('browser shortcuts stay theirs in the walkthrough: Ctrl+D does not delete the sentence (review 2026-10-12)', async () => {
		const units = [u(0, 'The pancreas is', 'Liver', { abnormal: true })];
		const c = { key: 'p', kind: 'truncation', blocking: true, tier: 1 as const, message: 'Unfinished.', quote: 'The pancreas is', other: null, suggestion: '', unitId: 0 };
		const props = { ...base(), units, checks: [c], conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true };
		render(HybridStackView, props);
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await userEvent.keyboard('{Control>}d{/Control}');
		expect(props.onEditLine).not.toHaveBeenCalled();
	});

	it('a check whose words differ only in case or spacing from the line still blocks (review 2026-10-12)', async () => {
		const units = [u(0, 'The pancreas is', 'Liver', { abnormal: true })];
		const c = { key: 'p', kind: 'truncation', blocking: true, tier: 1 as const, message: 'Unfinished.', quote: 'the  pancreas is', other: null, suggestion: '', unitId: 0 };
		render(HybridStackView, { ...base(), units, checks: [c], conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true });
		await expect.element(page.getByRole('button', { name: '1 to check · 1 blocking' })).toBeInTheDocument();
	});

	it('the walkthrough Confirm waits for a typed line to be added (review 2026-10-12)', async () => {
		const units = [u(0, 'The pancreas is', 'Liver', { abnormal: true })];
		const c = { key: 'p', kind: 'truncation', blocking: true, tier: 1 as const, message: 'Unfinished.', quote: 'The pancreas is', other: null, suggestion: '', unitId: 0 };
		const props = { ...base(), units, conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, checks: [c] });
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		r.rerender({ ...props, checks: [c], checkAnswers: { p: 'as_dictated' } });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('All checked');
		await page.getByLabelText('New line').fill('Small left renal cyst');
		await expect.element(page.getByRole('button', { name: 'Confirm', exact: true })).toBeDisabled();
	});

	it('rows over the cap wait behind one quiet "N more checks" line; opened, they are ordinary rows; never block Confirm', async () => {
		const props = { ...base(), onAnswer: vi.fn(), onToggleMore: vi.fn() };
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')];
		const more = [row('c1', ['No splenic lesion.'], { region: 'Spleen', question: 'Splenic lesion?' }), row('c2', ['No hydronephrosis.'], { region: 'Kidneys', question: 'Hydronephrosis?' })];
		const r = render(HybridStackView, { ...props, units, conclusion: { kind: 'dictated' }, items: [], more, moreWaiting: 2, namedNormals: true });
		await expect.element(page.getByRole('button', { name: '▸ 2 more checks' })).toBeInTheDocument();
		await expect.element(page.getByText('Splenic lesion?')).not.toBeInTheDocument();   // collapsed
		await expect.element(page.getByText('0 referral questions open')).toBeInTheDocument();
		await page.getByRole('button', { name: '▸ 2 more checks' }).click();
		expect(props.onToggleMore).toHaveBeenCalled();
		r.rerender({ ...props, units, conclusion: { kind: 'dictated' }, items: [], more, moreWaiting: 2, moreOpen: true, namedNormals: true });
		await expect.element(page.getByText('Splenic lesion?')).toBeInTheDocument();
		await page.getByRole('button', { name: '✓ Normal' }).first().click();
		expect(props.onAnswer).toHaveBeenCalledWith('c1');
		r.rerender({ ...props, units, conclusion: { kind: 'dictated' }, items: [], more, moreWaiting: 1, moreOpen: true, tapped: ['c1'], namedNormals: true });
		await expect.element(page.getByRole('button', { name: '▾ 1 more check' })).toBeInTheDocument();   // N: still asked
		await expect.element(page.getByText('✓ No splenic lesion.')).toBeInTheDocument();   // green, still behind the line
	});

	it('open and "stated?" required values block Confirm and are walked to, ringed; resolving them frees Confirm', async () => {
		const onEnterValue = vi.fn();
		const onKeepValue = vi.fn();
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })];
		const values = [
			{ item: 'LVEF', state: 'filled' as const, value: '45%', quote: 'LVEF 45%.' },
			{ item: 'RVEF', state: 'open' as const, value: null, quote: null },
			{ item: 'Conus level', state: 'check' as const, value: null, quote: null }
		];
		const props = { ...base(), units, onEnterValue, onKeepValue, conclusion: { kind: 'draft', text: 'Liver cyst.', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, values });
		await expect.element(page.getByTestId('value-cluster')).toBeInTheDocument();
		await expect.element(page.getByText('2 required values to resolve')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Confirm · 2 to resolve' }).click();
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 1 of 2 · Required value');
		await expect.element(page.getByLabelText('Value for RVEF')).toHaveFocus(); // the stop opens the chip to type
		await expect.element(page.getByTestId('value-editor')).toHaveClass('ring-2');
		await page.getByLabelText('Value for RVEF').fill('50%');
		await userEvent.keyboard('{Enter}');
		expect(onEnterValue).toHaveBeenCalledWith('RVEF', '50%');
		const typed = [values[0], { item: 'RVEF', state: 'entered' as const, value: '50%', quote: null }, values[2]];
		r.rerender({ ...props, values: typed });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 2 of 2 · Required value · needs a look');
		await page.getByRole('button', { name: 'Stated ✓' }).click();
		expect(onKeepValue).toHaveBeenCalledWith('Conus level');
		r.rerender({ ...props, values: [typed[0], typed[1], { item: 'Conus level', state: 'filled' as const, value: null, quote: null, kept: true }] });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('All checked');
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		expect(props.onConfirm).toHaveBeenCalled();
	});

	it('the walkthrough offers one step to mark every open value not provided ("stated?" still needs a look)', async () => {
		const onValuesRestNa = vi.fn();
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })];
		const values = [
			{ item: 'LVEF', state: 'open' as const, value: null, quote: null },
			{ item: 'RVEF', state: 'open' as const, value: null, quote: null },
			{ item: 'Conus level', state: 'check' as const, value: null, quote: null }
		];
		const props = { ...base(), units, onValuesRestNa, conclusion: { kind: 'draft', text: 'Liver cyst.', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, values });
		await expect.element(page.getByRole('button', { name: 'Mark 2 not provided' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Confirm · 3 to resolve' }).click();
		await page.getByRole('button', { name: 'Mark 2 not provided' }).click();
		expect(onValuesRestNa).toHaveBeenCalledOnce();
		r.rerender({ ...props, values: [{ ...values[0], state: 'na' as const }, { ...values[1], state: 'na' as const }, values[2]] });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Required value · needs a look');
		await expect.element(page.getByRole('button', { name: /not provided/ })).not.toBeInTheDocument();
	});

	it('a required-value editor holding unsaved text holds Confirm', async () => {
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })];
		const values = [{ item: 'LVEF', state: 'entered' as const, value: '45%', quote: null }];
		render(HybridStackView, { ...base(), units, values, conclusion: { kind: 'draft', text: 'Liver cyst.', edited: false } as const, namedNormals: true });
		const confirm = page.getByRole('button', { name: 'Confirm', exact: true });
		await expect.element(confirm).toBeEnabled();
		await page.getByRole('button', { name: 'LVEF 45%' }).click();
		await page.getByLabelText('Value for LVEF').fill('46%');
		await expect.element(confirm).toBeDisabled();
		await userEvent.keyboard('{Escape}');
		await expect.element(confirm).toBeEnabled();
	});

	it('a guideline walk stop opens its card once, even when the parent rebuilds the list on every open (final review C-1)', async () => {
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')];
		let r: ReturnType<typeof render>;
		const onOpenGuideline = vi.fn(() => r.rerender({ ...props, guidelinesUnresolved: [{ key: 'k', name: 'BTS 2015' }] }));   // a new array each time, as the session's publish does
		const props = { ...base(), units, conclusion: { kind: 'dictated' } as const, onOpenGuideline };
		r = render(HybridStackView, { ...props, guidelinesUnresolved: [{ key: 'k', name: 'BTS 2015' }] });
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await expect.element(page.getByText('Guideline unresolved · BTS 2015')).toBeInTheDocument();
		await new Promise((res) => setTimeout(res, 200));
		expect(onOpenGuideline).toHaveBeenCalledTimes(1);
	});

	it('guidelines unresolved (§7.12): each is a walk stop that blocks Confirm and opens its card; the chip opens the first; none: as before', async () => {
		const onOpenGuideline = vi.fn();
		const units = [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true }), u(1, 'Simple cyst.', 'Conclusion')];
		const props = { ...base(), units, conclusion: { kind: 'dictated' } as const, onOpenGuideline };
		const r = render(HybridStackView, { ...props, guidelinesUnresolved: [{ key: 'k', name: 'BTS 2015' }] });
		await page.getByRole('button', { name: '1 guideline unresolved' }).click();
		expect(onOpenGuideline).toHaveBeenCalledWith('k');
		onOpenGuideline.mockClear();
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();     // Confirm starts the walk instead
		await expect.element(page.getByText('Guideline unresolved · BTS 2015')).toBeInTheDocument();
		expect(onOpenGuideline).toHaveBeenCalledWith('k');
		await expect.element(page.getByRole('button', { name: /^Confirm( & Generate)?$/ })).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Exit' }).click();
		r.rerender({ ...props, guidelinesUnresolved: [{ key: 'a', name: 'A' }, { key: 'b', name: 'B' }] });
		await expect.element(page.getByRole('button', { name: '2 guidelines unresolved' })).toBeInTheDocument();
		r.rerender({ ...props, guidelinesUnresolved: [] });
		await expect.element(page.getByText(/guidelines? unresolved/)).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeEnabled();
	});

	it('applied recommendations: their own region renders after the Conclusion; none, no region', async () => {
		const rec = { key: 'k1', finding_id: 'u1', pack: 'p', version: 'v', bundle: 'b', source: 'BTS 2015', outcome: 'o', verdict: 'x', sentence: 'CT at 3 months (BTS 2015).', text: 'CT at 3 months (BTS 2015).', values: [] };
		const units = [u(0, 'A 7 mm solid nodule.', 'Liver', { abnormal: true, covers: ['Liver'] })];
		const r = render(HybridStackView, { ...base(), units, recommendations: [rec] });
		await expect.element(page.getByRole('region', { name: 'Recommendations' })).toHaveTextContent('CT at 3 months (BTS 2015).');
		const html = document.body.innerHTML;
		expect(html.indexOf('aria-label="Conclusion"')).toBeGreaterThan(-1);
		expect(html.indexOf('aria-label="Recommendations"')).toBeGreaterThan(html.indexOf('aria-label="Conclusion"'));
		await r.rerender({ ...base(), units, recommendations: [] });
		await expect.element(page.getByRole('region', { name: 'Recommendations' })).not.toBeInTheDocument();
	});
	// ── "Which side?" and the not-reported line (side brief 2026-10-14) ──
	const sideAsk = (region = 'Kidneys') => ({ key: `side_missing|${region}|k`, kind: 'side_missing', blocking: true, tier: 2 as const,
		message: 'A finding here is dictated without its side.', quote: 'The right/left kidney is normal.', other: null, suggestion: '', unitId: null, region });
	it('a side-less finding asks "Which side?" in its region card and blocks Confirm until kept or a side is dictated', async () => {
		const onCheckAnswer = vi.fn();
		const onToggleMic = vi.fn();
		const units = [u(0, 'A simple cyst in the kidney.', 'Kidneys', { abnormal: true })];
		const props = { ...base(), units, onCheckAnswer, onToggleMic, conclusion: { kind: 'draft', text: 'Renal cyst.', edited: false } as const, namedNormals: true };
		const r = render(HybridStackView, { ...props, checks: [sideAsk()] });
		const card = page.getByRole('region', { name: 'Kidneys' });
		await expect.element(card.getByText('Which side?')).toBeInTheDocument();
		await expect.element(card.getByText(/The right\/left kidney is normal\./)).toBeInTheDocument();
		await card.getByRole('button', { name: 'Dictate side' }).click();
		expect(onToggleMic).toHaveBeenCalled();
		await page.getByRole('button', { name: 'Confirm · 1 to resolve' }).click();
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('Checking 1 of 1 · Which side?');
		await card.getByRole('button', { name: 'Keep without side' }).click();
		expect(onCheckAnswer).toHaveBeenCalledWith('side_missing|Kidneys|k', 'as_dictated');
		// a side dictated: the next /assumed answer no longer asks, and Confirm returns by itself
		r.rerender({ ...props, checks: [] });
		await expect.element(page.getByTestId('walkthrough')).toHaveTextContent('All checked');
		await expect.element(page.getByText('Which side?')).not.toBeInTheDocument();
	});
	it('an ask whose region has no card shows up top', async () => {
		const units = [u(0, 'A 2 cm liver cyst.', 'Liver', { abnormal: true })];
		render(HybridStackView, { ...base(), units, checks: [sideAsk('Kidneys')], conclusion: { kind: 'draft', text: 'x', edited: false } as const, namedNormals: true });
		await expect.element(page.getByRole('region', { name: 'Checks' }).getByText('Which side?')).toBeInTheDocument();
	});
	it('a region with findings lists the normals left out for conflicting with the dictation, struck through', async () => {
		const units = [u(0, 'A 12 mm cyst in the left kidney.', 'Kidneys', { abnormal: true })];
		render(HybridStackView, { ...base(), units, assumed: { Kidneys: ['The right kidney is normal.'] },
			notReported: { Kidneys: [{ why: 'conflicts with dictation', sentences: ['The left kidney is normal.'] }, { why: 'side not stated', sentences: ['No right hydronephrosis.'] }],
				Liver: [{ why: 'conflicts with dictation', sentences: ['The liver is normal.'] }] }, sideFailed: 'kept' });
		const line = page.getByRole('region', { name: 'Kidneys' }).getByText('Not reported (conflicts with dictation)');
		await expect.element(line).toBeInTheDocument();
		const struck = page.getByText('The left kidney is normal.');
		await expect.element(struck).toBeInTheDocument();
		expect(struck.element().closest('s')).not.toBeNull();
		await expect.element(page.getByText('The liver is normal.')).not.toBeInTheDocument();   // no card: nothing shown
		// a side drop is not a conflict (review F7); a failed side check says so at the Confirm bar (review F2)
		await expect.element(page.getByRole('region', { name: 'Kidneys' }).getByText('Not reported (side not stated)')).toBeInTheDocument();
		await expect.element(page.getByText(/side check unavailable/)).toBeInTheDocument();
	});
	it('Q12: an open instruction card blocks Confirm (and so Generate) until it is answered', async () => {
		const props = { ...base(), onKeepHeld: vi.fn(), onRemoveHeld: vi.fn(), units: [u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true })],
			conclusion: { kind: 'draft', text: 'Simple hepatic cyst.', edited: true } as const };
		const r = render(HybridStackView, { ...props, held: [{ id: 1, text: 'Delete all the other sections.' }] });
		await expect.element(page.getByTestId('held-instruction')).toHaveTextContent(/Delete all the other sections/);
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeDisabled();
		await expect.element(page.getByText('1 instruction to answer')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Discard' }).click();
		expect(props.onRemoveHeld).toHaveBeenCalledWith(1);
		r.rerender({ ...props, held: [] });
		await expect.element(page.getByRole('button', { name: 'Confirm' })).toBeEnabled();
		await expect.element(page.getByText('1 instruction to answer')).not.toBeInTheDocument();
	});
});
