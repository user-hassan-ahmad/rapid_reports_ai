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

const ITEMS = [
	item({ id: 'a1', label: 'Spleen size missing' }),
	item({ id: 'a2', label: 'Ascites' })
];

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
		{
			section: 'FINDINGS',
			find: 'No ascites.',
			replace: 'Small ascites.',
			verified: true,
			failed: []
		},
		{
			section: 'FINDINGS',
			find: 'spleen',
			replace: 'spleen 14 cm',
			verified: false,
			failed: ['ungrounded_number']
		}
	],
	sources: []
};

async function mount(props: Record<string, unknown> = {}) {
	const store = createReviewStore('rep1');
	getReview.mockResolvedValueOnce(response());
	await store.load();
	const applyEdit = vi.fn(
		(messageId: string, index: number, e: { section: string; find: string; replace: string }) => {
			const it = chatItem('rep1', messageId, index, e);
			store.upsert([{ ...it, status: 'applied' }]);
			return null;
		}
	);
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
		expect(applyEdit.mock.calls[0][2]).toMatchObject({
			find: 'No ascites.',
			replace: 'Small ascites.'
		});
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
		await expect
			.element(page.getByRole('button', { name: 'Apply chat edit: Small ascites.' }))
			.toBeInTheDocument();
	});

	it('"Ask in chat" pre-fill: the composer takes the text', async () => {
		const { screen } = await mount();
		await screen.rerender({ chatPrefill: { text: 'Ascites: why', seq: 1 } });
		await expect
			.element(page.getByRole('textbox', { name: 'Chat message' }))
			.toHaveValue('Ascites: why');
	});

	it('the Expand icon widens the rail', async () => {
		sendChat.mockResolvedValue(REPLY);
		await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('q');
		await page.getByRole('button', { name: 'Send' }).click();
		const before = rail().getBoundingClientRect().width;
		await page.getByRole('button', { name: 'Expand chat' }).click();
		await expect.poll(() => rail().getBoundingClientRect().width).toBeGreaterThan(before);
	});

	it('without `chat` there is no composer', async () => {
		await mount({ chat: undefined });
		await expect.element(page.getByText('Spleen size missing')).toBeInTheDocument();
		expect(document.querySelector('textarea')).toBeNull();
	});
});

describe('ReviewRail chat sources (F2 M8)', () => {
	it('links only http(s) sources; any other scheme shows as plain text', async () => {
		sendChat.mockResolvedValue({
			...REPLY,
			sources: [
				{ title: 'Safe source', url: 'https://example.org/guide' },
				{ title: 'Script source', url: 'javascript:alert(1)' },
				{ title: 'Data source', url: 'data:text/html,<b>x</b>' }
			]
		});
		await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('Sources?');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect
			.element(page.getByRole('link', { name: 'Safe source' }))
			.toHaveAttribute('href', 'https://example.org/guide');
		await expect.element(page.getByText('Script source')).toBeInTheDocument();
		await expect.element(page.getByText('Data source')).toBeInTheDocument();
		const hrefs = [...rail().querySelectorAll('.rv-sources a')].map((a) => a.getAttribute('href'));
		expect(hrefs).toEqual(['https://example.org/guide']);
	});
});

describe('ReviewRail chat formatting', () => {
	async function ask(reply: Partial<ChatReply>) {
		sendChat.mockResolvedValue({ ...REPLY, edits: [], ...reply });
		await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('Staging?');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.poll(() => rail().querySelector('.rv-msg-assistant')).not.toBeNull();
		return rail().querySelector<HTMLElement>('.rv-msg-assistant .rv-msg-text')!;
	}

	it('renders the reply’s Markdown: paragraphs, bold and bullet lists (no literal ** or "*   ")', async () => {
		const md =
			'The provisional staging is:\n\n*   **T1c:** mass 2.8 cm.\n*   **N1:** hilar node.\n\n**Provisional stage: T1c N1 Mx**\n\nMDT discussion advised.';
		const body = await ask({ response: md });
		expect(body.textContent).not.toContain('**');
		expect(body.textContent).not.toMatch(/^\s*\*\s/m);
		expect([...body.querySelectorAll('li')].map((l) => l.textContent)).toEqual([
			'T1c: mass 2.8 cm.',
			'N1: hilar node.'
		]);
		expect([...body.querySelectorAll('strong')].map((b) => b.textContent)).toContain(
			'Provisional stage: T1c N1 Mx'
		);
		expect(body.querySelectorAll('p').length).toBe(3);
		// bullets indented inside the bubble, compact (no stray blank lines between paragraphs)
		const ul = body.querySelector('ul')!;
		expect(Number.parseFloat(getComputedStyle(ul).paddingLeft)).toBeGreaterThan(8);
		expect(getComputedStyle(ul).listStyleType).toBe('disc');
		expect(getComputedStyle(body).whiteSpace).not.toBe('pre-wrap');
	});

	it('sanitises HTML and script injection in the reply', async () => {
		const body = await ask({
			response:
				'Hi <script>window.__pwned = 1</script><img src=x onerror="window.__pwned=2"> <a href="javascript:alert(1)">x</a> <iframe src="https://evil.example"></iframe> [ok](https://example.org)'
		});
		await new Promise((r) => setTimeout(r, 50));
		expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
		expect(body.querySelector('script, img, iframe, [onerror]')).toBeNull();
		const links = [...body.querySelectorAll('a')];
		expect(links.map((a) => a.getAttribute('href'))).toEqual([null, 'https://example.org']);
		expect(links[1].getAttribute('rel')).toContain('noopener');
	});

	it('the user’s own message stays plain text', async () => {
		sendChat.mockResolvedValue({ ...REPLY, edits: [] });
		await mount();
		await page.getByRole('textbox', { name: 'Chat message' }).fill('**not bold** <b>x</b>');
		await page.getByRole('button', { name: 'Send' }).click();
		await expect.poll(() => rail().querySelector('.rv-msg-user .rv-msg-text')).not.toBeNull();
		const el = rail().querySelector<HTMLElement>('.rv-msg-user .rv-msg-text')!;
		expect(el.textContent).toBe('**not bold** <b>x</b>');
		expect(el.querySelector('b, strong')).toBeNull();
	});

	it('sources are deduplicated by URL and listed compactly under "Sources"', async () => {
		await ask({
			sources: [
				{ title: 'Lung cancer - NICE', url: 'https://cks.nice.org.uk/lung' },
				{ title: 'Lung cancer - NICE', url: 'https://cks.nice.org.uk/lung' },
				{ title: 'Lung cancer (dup, trailing slash)', url: 'https://cks.nice.org.uk/lung/' },
				{ title: 'Fleischner', url: 'https://example.org/fleischner' }
			]
		});
		const box = rail().querySelector<HTMLElement>('[data-rv-sources]')!;
		expect(box.querySelector('.rv-sources-title')!.textContent).toBe('Sources');
		expect([...box.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual([
			'https://cks.nice.org.uk/lung',
			'https://example.org/fleischner'
		]);
		for (const li of box.querySelectorAll('li')) expect(getComputedStyle(li).whiteSpace).toBe('nowrap');
	});

	it('the chat header is one compact row: "← Review · N open" left, the Expand icon right', async () => {
		await ask({});
		const head = rail().querySelector<HTMLElement>('[data-rv-chat-head]')!;
		const back = page.getByRole('button', { name: /← Review · \d+ open/ }).element();
		const expand = page.getByRole('button', { name: 'Expand chat' }).element();
		const b = back.getBoundingClientRect();
		const e = expand.getBoundingClientRect();
		expect(Math.abs((b.top + b.bottom) / 2 - (e.top + e.bottom) / 2)).toBeLessThan(4); // one row
		expect(b.left - head.getBoundingClientRect().left).toBeLessThan(16); // left
		expect(head.getBoundingClientRect().right - e.right).toBeLessThan(16); // right
		expect(expand.textContent?.trim()).toBe(''); // an icon button
		expect(head.getBoundingClientRect().height).toBeLessThan(44);
	});
});
