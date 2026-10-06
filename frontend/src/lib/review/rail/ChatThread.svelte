<script lang="ts">
	/**
	 * The chat thread in the rail (plan Task D2, spec §12.5). The composer is always there; the thread shows when the
	 * rail is in chat view (`showThread`). A reply's verified edits each have Apply (the host turns it into a local
	 * `lane: chat` item through the same apply command); unverified edits show why they failed and no Apply.
	 * Unapplied edits stay in the thread. The backend saves each turn: the thread opens with the saved messages
	 * (`thread`, spec §12.6) and keeps the saved ids, so chat items stay linked to their message across reloads.
	 * Messages with no saved id (errors, unsaved turns) get `local-` ids.
	 */
	import { tick, untrack } from 'svelte';
	import {
		chatItemId,
		failureText,
		sendChat,
		type ChatEdit,
		type ChatHistoryEntry,
		type ChatOpenItem,
		type ChatSource,
		type ChatThreadMessage
	} from '../chat';
	import { dedupeSources, renderChatMarkdown } from '../markdown';
	import type { ItemStatus } from '../types';

	interface Message {
		id: string;
		role: 'user' | 'assistant';
		content: string;
		edits: ChatEdit[];
		sources: ChatSource[];
		error?: boolean;
	}

	let {
		reportId,
		getText,
		openItems,
		applyEdit,
		undoEdit,
		statusOf,
		showThread = false,
		onSent,
		prefill = null,
		thread = []
	}: {
		reportId: string;
		/** The live editor document (sent as `text`). */
		getText: () => string;
		openItems: () => ChatOpenItem[];
		/** Apply a verified edit; null on success, else why it could not be placed. */
		applyEdit: (messageId: string, index: number, edit: ChatEdit) => string | null;
		undoEdit?: (itemId: string) => void;
		/** The status of a chat item in the store (undefined: never applied). */
		statusOf: (itemId: string) => ItemStatus | undefined;
		showThread?: boolean;
		/** Called as a message is sent (the rail switches to the thread). */
		onSent?: () => void;
		/** "Ask in chat": the composer takes `text` whenever `seq` changes. */
		prefill?: { text: string; seq: number } | null;
		/** The saved thread the composer continues (read once, at mount). */
		thread?: ChatThreadMessage[];
	} = $props();

	let messages = $state<Message[]>(
		untrack(() =>
			thread.map((m) => ({ id: m.id, role: m.role, content: m.content, edits: m.edits, sources: m.sources }))
		)
	);
	let draft = $state('');
	let sending = $state(false);

	/** Source links come from the model: only http(s) URLs become links (never javascript:, data:, …). */
	function isWebUrl(url: string): boolean {
		try {
			return ['http:', 'https:'].includes(new URL(url).protocol);
		} catch {
			return false;
		}
	}
	let seq = 0;
	let applyErrors = $state<Record<string, string>>({});
	let composer = $state<HTMLTextAreaElement | null>(null);
	let threadEl = $state<HTMLElement | null>(null);

	let lastPrefill = -1;
	$effect(() => {
		const p = prefill;
		if (!p || p.seq === lastPrefill) return;
		lastPrefill = p.seq;
		draft = p.text;
		void tick().then(() => composer?.focus());
	});

	async function scrollDown() {
		await tick();
		if (threadEl) threadEl.scrollTop = threadEl.scrollHeight;
	}

	async function send() {
		const text = draft.trim();
		if (!text || sending) return;
		const history: ChatHistoryEntry[] = messages
			.filter((m) => !m.error)
			.map((m) => ({ role: m.role, content: m.content }));
		const userId = `local-${++seq}`;
		messages.push({ id: userId, role: 'user', content: text, edits: [], sources: [] });
		draft = '';
		sending = true;
		onSent?.();
		void scrollDown();
		try {
			const reply = await sendChat(reportId, {
				message: text,
				history,
				text: getText(),
				openItems: openItems()
			});
			const sent = messages.find((m) => m.id === userId);
			if (sent && reply.userMessageId) sent.id = reply.userMessageId;
			messages.push({
				id: reply.messageId ?? `local-${++seq}`,
				role: 'assistant',
				content: reply.response,
				edits: reply.edits,
				sources: reply.sources
			});
		} catch (e) {
			messages.push({
				id: `local-${++seq}`,
				role: 'assistant',
				content: e instanceof Error ? e.message : String(e),
				edits: [],
				sources: [],
				error: true
			});
		} finally {
			sending = false;
			void scrollDown();
		}
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void send();
		}
	}

	function apply(m: Message, k: number) {
		const key = chatItemId(m.id, k);
		const err = applyEdit(m.id, k, m.edits[k]);
		const next = { ...applyErrors };
		if (err) next[key] = err;
		else delete next[key];
		applyErrors = next;
	}
</script>

{#if showThread}
	<div class="rv-chat-thread" bind:this={threadEl} aria-label="Chat" role="log">
		{#each messages as m (m.id)}
			<div class="rv-msg rv-msg-{m.role}" class:rv-msg-error={m.error} data-rv-msg={m.id}>
				{#if m.role === 'assistant' && !m.error}
					<!-- model Markdown, sanitised to a strict allowlist (lib/review/markdown.ts) -->
					<div class="rv-msg-text rv-md">{@html renderChatMarkdown(m.content)}</div>
				{:else}
					<p class="rv-msg-text rv-plain">{m.content}</p>
				{/if}
				{#each m.edits as e, k (k)}
					{@const id = chatItemId(m.id, k)}
					{@const st = statusOf(id)}
					<div class="rv-edit" data-rv-edit={id} data-verified={e.verified}>
						{#if e.section}<div class="rv-edit-section">{e.section}</div>{/if}
						<div class="rv-diff">
							<del aria-label="Remove">{e.find}</del>
							{#if e.replace}<ins aria-label="Insert">{e.replace}</ins>{/if}
						</div>
						{#if !e.verified}
							<ul class="rv-edit-failed" aria-label="Not applied">
								{#each e.failed as code (code)}
									<li><span aria-hidden="true">⚠</span> {failureText(code)}</li>
								{/each}
							</ul>
						{:else if st === 'applied'}
							<div class="rv-edit-actions">
								<span class="rv-applied"><span aria-hidden="true">✓</span> Applied</span>
								{#if undoEdit}
									<button type="button" class="rv-btn" onclick={() => undoEdit(id)}>Undo</button>
								{/if}
							</div>
						{:else}
							<div class="rv-edit-actions">
								<button
									type="button"
									class="rv-btn rv-btn-primary"
									aria-label={`Apply chat edit: ${e.replace || 'remove ' + e.find}`}
									onclick={() => apply(m, k)}>Apply</button
								>
							</div>
							{#if applyErrors[id]}
								<p class="rv-edit-error" role="alert">Could not apply: {applyErrors[id]}</p>
							{/if}
						{/if}
					</div>
				{/each}
				{#if dedupeSources(m.sources).length}
					{@const sources = dedupeSources(m.sources)}
					<div class="rv-sources" data-rv-sources>
						<div class="rv-sources-title">Sources</div>
						<ul>
							{#each sources as s, k (k)}
								{#if s.url && isWebUrl(s.url)}
									<li><a href={s.url} target="_blank" rel="noopener noreferrer" title={s.url}>{s.title || s.url}</a></li>
								{:else}
									<li>{s.title || s.url}</li>
								{/if}
							{/each}
						</ul>
					</div>
				{/if}
			</div>
		{/each}
		{#if sending}<p class="rv-muted rv-thinking" role="status">Thinking…</p>{/if}
	</div>
{/if}

<form
	class="rv-composer"
	onsubmit={(e) => {
		e.preventDefault();
		void send();
	}}
>
	<textarea
		bind:this={composer}
		bind:value={draft}
		rows="2"
		placeholder="Ask about this report…"
		aria-label="Chat message"
		onkeydown={onKey}
	></textarea>
	<button type="submit" class="rv-btn rv-btn-primary" disabled={sending || !draft.trim()}>Send</button>
</form>

<style>
	.rv-chat-thread {
		flex: 1;
		overflow-y: auto;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.rv-msg {
		border-radius: 8px;
		padding: 6px 8px;
		border: 1px solid var(--rv-border);
	}
	.rv-msg-user {
		align-self: flex-end;
		max-width: 90%;
		background: var(--rv-surface-hover);
	}
	.rv-msg-error {
		border-color: var(--rv-red-line);
	}
	.rv-msg-text {
		margin: 0;
	}
	.rv-plain {
		white-space: pre-wrap;
	}
	/* rendered Markdown: compact, theme-coloured, no stray blank lines */
	.rv-md :global(:first-child) {
		margin-top: 0;
	}
	.rv-md :global(:last-child) {
		margin-bottom: 0;
	}
	.rv-md :global(p) {
		margin: 0 0 0.5em;
	}
	.rv-md :global(ul),
	.rv-md :global(ol) {
		margin: 0.25em 0 0.5em;
		padding-left: 1.2em;
	}
	.rv-md :global(ul) {
		list-style: disc;
	}
	.rv-md :global(ol) {
		list-style: decimal;
	}
	.rv-md :global(li) {
		margin: 0.15em 0;
		padding-left: 0.1em;
	}
	.rv-md :global(li > p) {
		margin: 0;
	}
	.rv-md :global(strong),
	.rv-md :global(b) {
		font-weight: 600;
		color: var(--rv-text);
	}
	.rv-md :global(h4),
	.rv-md :global(h5),
	.rv-md :global(h6) {
		margin: 0.4em 0 0.3em;
		font-size: 1em;
		font-weight: 600;
	}
	.rv-md :global(code) {
		font-size: 0.9em;
		padding: 0 3px;
		border-radius: 3px;
		background: var(--rv-surface-hover);
	}
	.rv-md :global(a) {
		color: var(--rv-blue-line);
	}
	.rv-edit {
		margin-top: 6px;
		padding: 6px;
		border-radius: 6px;
		border: 1px dashed var(--rv-border);
	}
	.rv-edit[data-verified='false'] {
		border-color: var(--rv-amber-line);
	}
	.rv-edit-section {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--rv-muted);
	}
	.rv-diff del {
		color: var(--rv-del);
	}
	.rv-diff ins {
		color: var(--rv-ins);
		text-decoration: none;
		margin-left: 4px;
	}
	.rv-edit-failed {
		list-style: none;
		margin: 4px 0 0;
		padding: 0;
		font-size: 0.75rem;
		color: var(--rv-amber-line);
	}
	.rv-edit-actions {
		display: flex;
		gap: 6px;
		align-items: center;
		margin-top: 4px;
	}
	.rv-applied {
		font-size: 0.75rem;
		color: var(--rv-green-line);
	}
	.rv-edit-error {
		margin: 4px 0 0;
		font-size: 0.75rem;
		color: var(--rv-red-line);
	}
	.rv-sources {
		margin: 6px 0 0;
		padding-top: 5px;
		border-top: 1px solid var(--rv-border);
		font-size: 0.7rem;
		line-height: 1.4;
		color: var(--rv-muted);
	}
	.rv-sources-title {
		font-size: 0.65rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		margin-bottom: 2px;
	}
	.rv-sources ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.rv-sources li {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.rv-sources a {
		color: var(--rv-muted);
		text-decoration: none;
	}
	.rv-sources a:hover {
		color: var(--rv-blue-line);
		text-decoration: underline;
	}
	.rv-thinking {
		font-size: 0.75rem;
	}
	.rv-muted {
		color: var(--rv-muted);
	}
	.rv-composer {
		display: flex;
		gap: 6px;
		align-items: flex-end;
		padding: 8px 10px;
		border-top: 1px solid var(--rv-border);
	}
	.rv-composer textarea {
		flex: 1;
		font: inherit;
		resize: vertical;
		min-height: 2.4em;
		background: rgba(0, 0, 0, 0.4);
		color: var(--rv-text);
		border: 1px solid var(--rv-border);
		border-radius: 0.5rem;
		padding: 6px 8px;
	}
	.rv-btn {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 500;
		padding: 2px 9px;
		line-height: 1.45;
		border-radius: 0.375rem;
		border: 1px solid var(--rv-border);
		background: var(--rv-surface);
		color: var(--rv-text);
		cursor: pointer;
		transition: background-color 0.15s, border-color 0.15s;
	}
	.rv-btn:hover:not(:disabled) {
		background: var(--rv-surface-hover);
		border-color: var(--rv-border-strong);
	}
	.rv-btn-primary {
		background: var(--rv-accent);
		border-color: var(--rv-accent);
		color: #fff;
		font-weight: 600;
	}
	.rv-btn-primary:hover:not(:disabled) {
		background: var(--rv-accent-hover);
		border-color: var(--rv-accent-hover);
	}
	.rv-btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	button:focus-visible,
	textarea:focus-visible {
		outline: 2px solid var(--rv-focus, #a855f7);
		outline-offset: 1px;
	}
</style>
