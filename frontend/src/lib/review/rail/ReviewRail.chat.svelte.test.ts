// The chat thread in the rail (Plan 3 D2, spec §12.5). SYNTHETIC items and replies only.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import type { ReviewItem, ReviewResponse } from '../types';
import type { ChatReply } from '../chat';

const getReview = vi.fn();
vi.mock('../api', () => ({
	getReview: (id: string) => getReview(id),
	postEvent: vi.fn(),
	rerun: vi.fn()
}));
const sendChat = vi.fn();
vi.mock('../chat', async (orig) => ({
	...(await orig<typeof import('../chat')>()),
	sendChat: (...a: unknown[]) => sendChat(...a)
}));

const { createReviewStore } = await import('../store');
const { chatItem } = await import('../chat');
const { default: ReviewRail } = await import('./ReviewRail.svelte');

function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		kind: 'omission',
		cls: 'action',
		section: 'FINDINGS',
		label: over.id,
		reason: 'why',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

const ITEMS = [item({ id: 'a1', label: 'Spleen size missing' }), item({ id: 'a2', label: 'Ascites' })];

function response(): ReviewResponse {
	const lanes = { coverage: 'done', accuracy: 'done', additions: 'done' };
	return {
		success: true,
		mode: 'live',
		rail: true,
		run: {
			id: 'run1',
			mode: 'live',
			engine_version: 'test',
			pathway: 'quick',
			lanes,
			timings_ms: {},
			cost: {},
			errors: {},
			created_at: null
		},
		lanes,
		items: ITEMS
	};
}

const REPLY: ChatReply = {
	response: 'Here are two edits.',
	edits: [
		{ section: 'FINDINGS', find: 'No ascites.', replace: 'Small ascites.', verified: true, failed: [] },
		{ section: 'FINDINGS', find: 'spleen', replace: 'spleen 14 cm', verified: false, failed: ['ungrounded_number'] }
	],
	sources: []
};

async function mount(props: Record<string, unknown> = {}) {
	const store = createReviewStore('rep1');
	getReview.mockResolvedValueOnce(response());
	await store.load();
	const applyEdit = vi.fn((messageId: string, index: number, e: { section: string; find: string; replace: string }) => {
		const it = chatItem('rep1', messageId, index, e);
		store.upsert([{ ...it, status: 'applied' }]);
		return null;
	});
	const onCommand = vi.fn();
	const screen = render(ReviewRail, {
		store,
		onCommand,
		layout: 'wide',
		chat: { reportId: 'rep1', getText: () => 'LIVE TEXT', applyEdit },
		...props
	});
	return { store, applyEdit, onCommand, screen };
}

const rail = () => document.querySelector<HTMLElement>('[data-testid="review-rail"]')!;

afterEach(() => {
	getReview.mockReset();
	sendChat.mockReset();
});

describe('ReviewRail chat', () => {
	it('sending switches to the thread with "← Review · N open"; the back strip returns to the review', async () => {
		sendChat.mockResolvedValue(REPLY);
		await mount();
		await expect.element(page.getByText('Spleen size missing')).toBeInTheDocument();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('Tighten the findings');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.element(page.getByText('Here are two edits.')).toBeInTheDocument();
		expect(rail().textContent).not.toContain('Spleen size missing');
		const back = page.getByRole('button', { name: '← Review · 2 open' });
		await expect.element(back).toBeInTheDocument();

		const [reportId, req] = sendChat.mock.calls[0] as [string, Record<string, unknown>];
		expect(reportId).toBe('rep1');
		expect(req.message).toBe('Tighten the findings');
		expect(req.text).toBe('LIVE TEXT');
		expect(req.openItems).toEqual([
			{ id: 'a1', section: 'FINDINGS', kind: 'omission', label: 'Spleen size missing' },
			{ id: 'a2', section: 'FINDINGS', kind: 'omission', label: 'Ascites' }
		]);

		await back.click();
		await expect.element(page.getByText('Spleen size missing')).toBeInTheDocument();
		expect(rail().textContent).not.toContain('Here are two edits.');
	});

	it('a verified edit has Apply (applies through the host); a failed edit shows its reasons and no Apply', async () => {
		sendChat.mockResolvedValue(REPLY);
		const { applyEdit } = await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('Fix it');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.element(page.getByText('Here are two edits.')).toBeInTheDocument();

		const failed = rail().querySelector('[data-verified="false"]')!;
		expect(failed.textContent).toContain('It adds a number that is not in the dictation');
		expect(failed.querySelector('button')).toBeNull();
		expect(page.getByRole('button', { name: /^Apply chat edit/ }).elements()).toHaveLength(1);

		await page.getByRole('button', { name: 'Apply chat edit: Small ascites.' }).click();
		expect(applyEdit).toHaveBeenCalledTimes(1);
		expect(applyEdit.mock.calls[0][2]).toMatchObject({ find: 'No ascites.', replace: 'Small ascites.' });
		await expect.element(page.getByText('Applied')).toBeInTheDocument();
		expect(page.getByRole('button', { name: /^Apply chat edit/ }).elements()).toHaveLength(0);
	});

	it('an apply that cannot be placed keeps Apply and says why', async () => {
		sendChat.mockResolvedValue(REPLY);
		await mount({
			chat: { reportId: 'rep1', getText: () => '', applyEdit: () => 'not_found' }
		});
		await page.getByRole('textbox', { name: 'Chat message' }).fill('Fix it');
		await page.getByRole('button', { name: 'Send' }).click();
		await page.getByRole('button', { name: 'Apply chat edit: Small ascites.' }).click();
		await expect.element(page.getByRole('alert')).toHaveTextContent('Could not apply');
		await expect.element(page.getByRole('button', { name: 'Apply chat edit: Small ascites.' })).toBeInTheDocument();
	});

	it('"Ask in chat" pre-fill: the composer takes the text', async () => {
		const { screen } = await mount();
		await screen.rerender({ chatPrefill: { text: 'Ascites: why', seq: 1 } });
		await expect.element(page.getByRole('textbox', { name: 'Chat message' })).toHaveValue('Ascites: why');
	});

	it('⤢ Expand widens the rail', async () => {
		sendChat.mockResolvedValue(REPLY);
		await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('q');
		await page.getByRole('button', { name: 'Send' }).click();
		const before = rail().getBoundingClientRect().width;
		await page.getByRole('button', { name: '⤢ Expand' }).click();
		await expect.poll(() => rail().getBoundingClientRect().width).toBeGreaterThan(before);
	});

	it('without `chat` there is no composer', async () => {
		await mount({ chat: undefined });
		await expect.element(page.getByText('Spleen size missing')).toBeInTheDocument();
		expect(document.querySelector('textarea')).toBeNull();
	});
});
