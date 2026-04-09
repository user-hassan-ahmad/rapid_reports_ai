<script>
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	// ── State ──────────────────────────────────────────────────────────────────

	// Step 1 – examples
	let scanType = 'CT chest with IV contrast';
	let examples = [{ label: '', content: '' }];

	// Step 2 – chat / skill sheet
	/** @type {{ role: 'user'|'assistant', content: string }[]} */
	let chatHistory = [];
	let skillSheet = '';
	let chatInput = '';

	// Step 3 – test generate
	let testClinicalHistory = '';
	let testFindings = '';
	let testReport = '';

	// UI state
	let phase = /** @type {'examples'|'chat'|'test'} */ ('examples');
	let loading = false;
	let error = '';

	// ── Helpers ────────────────────────────────────────────────────────────────

	/** @param {string} path @param {Record<string, unknown>} body */
	async function postJson(path, body) {
		/** @type {Record<string, string>} */
		const headers = { 'Content-Type': 'application/json' };
		if ($token) headers['Authorization'] = `Bearer ${$token}`;
		const res = await fetch(`${API_URL}${path}`, {
			method: 'POST',
			headers,
			body: JSON.stringify(body)
		});
		const text = await res.text();
		let data;
		try {
			data = text ? JSON.parse(text) : null;
		} catch {
			data = { _parseError: true, raw: text };
		}
		if (!res.ok) {
			const detail =
				data?.detail ?? data?.message ?? (typeof data === 'string' ? data : JSON.stringify(data));
			throw new Error(`${res.status} ${res.statusText}: ${detail}`);
		}
		return data;
	}

	function addExample() {
		if (examples.length < 5) examples = [...examples, { label: '', content: '' }];
	}

	function removeExample(i) {
		if (examples.length > 1) examples = examples.filter((_, idx) => idx !== i);
	}

	// ── Actions ────────────────────────────────────────────────────────────────

	async function analyzeExamples() {
		error = '';
		const filled = examples.filter((e) => e.content.trim());
		if (!filled.length) {
			error = 'Paste at least one example report.';
			return;
		}
		loading = true;
		try {
			const data = await postJson('/api/templates/skill-sheet/analyze', {
				scan_type: scanType,
				examples: filled
			});
			if (!data.success) throw new Error(data.error);

			skillSheet = data.skill_sheet;
			chatHistory = [
				{
					role: 'assistant',
					content:
						data.summary +
						(data.questions?.length
							? '\n\nA few things to clarify:\n' +
								data.questions.map((q, i) => `${i + 1}. ${q}`).join('\n')
							: '')
				}
			];
			phase = 'chat';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function sendChat() {
		const msg = chatInput.trim();
		if (!msg || !skillSheet) return;
		chatInput = '';
		chatHistory = [...chatHistory, { role: 'user', content: msg }];
		loading = true;
		error = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/refine', {
				skill_sheet: skillSheet,
				message: msg,
				chat_history: chatHistory.slice(0, -1) // exclude the message we just added
			});
			if (!data.success) throw new Error(data.error);

			skillSheet = data.skill_sheet;
			chatHistory = [...chatHistory, { role: 'assistant', content: data.response }];
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			chatHistory = chatHistory.slice(0, -1); // remove the optimistically added user message
		} finally {
			loading = false;
		}
	}

	function handleChatKey(/** @type {KeyboardEvent} */ e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendChat();
		}
	}

	async function runTestGenerate() {
		if (!skillSheet || !testFindings.trim()) return;
		loading = true;
		error = '';
		testReport = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/test-generate', {
				skill_sheet: skillSheet,
				scan_type: scanType,
				clinical_history: testClinicalHistory,
				findings_input: testFindings
			});
			if (!data.success) throw new Error(data.error);
			testReport = data.report_content;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function copySkillSheet() {
		if (skillSheet && typeof navigator !== 'undefined') navigator.clipboard.writeText(skillSheet);
	}

	function copyReport() {
		if (testReport && typeof navigator !== 'undefined') navigator.clipboard.writeText(testReport);
	}
</script>

<svelte:head>
	<title>Skill Sheet tester — RadFlow</title>
</svelte:head>

{#if !$token}
	<div class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 p-8 text-center">
		<p class="text-gray-300 mb-6">Sign in to use the Skill Sheet tester.</p>
		<a href="/login" class="px-5 py-2.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-medium">Go to login</a>
		<p class="mt-6"><a href="/" class="text-gray-400 hover:text-white text-sm">← Back to app</a></p>
	</div>
{:else}
	<div class="min-h-screen bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 text-gray-100">
		<div class="max-w-screen-2xl mx-auto px-4 py-6 pb-16">

			<!-- Header -->
			<header class="flex flex-wrap items-center justify-between gap-4 mb-6 border-b border-white/10 pb-4">
				<div>
					<h1 class="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
						Skill Sheet tester
					</h1>
					<p class="text-sm text-gray-400 mt-1">
						Paste example reports → chat to refine → test generate → copy skill sheet
					</p>
				</div>
				<div class="flex items-center gap-4">
					<!-- Phase tabs -->
					<div class="flex rounded-lg border border-white/10 overflow-hidden text-sm">
						<button
							class="px-3 py-1.5 {phase === 'examples' ? 'bg-emerald-600 text-white' : 'text-gray-400 hover:text-white hover:bg-white/5'}"
							on:click={() => (phase = 'examples')}
						>
							1 · Examples
						</button>
						<button
							class="px-3 py-1.5 {phase === 'chat' ? 'bg-emerald-600 text-white' : 'text-gray-400 hover:text-white hover:bg-white/5'} {!skillSheet ? 'opacity-40 cursor-not-allowed' : ''}"
							on:click={() => skillSheet && (phase = 'chat')}
						>
							2 · Refine
						</button>
						<button
							class="px-3 py-1.5 {phase === 'test' ? 'bg-emerald-600 text-white' : 'text-gray-400 hover:text-white hover:bg-white/5'} {!skillSheet ? 'opacity-40 cursor-not-allowed' : ''}"
							on:click={() => skillSheet && (phase = 'test')}
						>
							3 · Test
						</button>
					</div>
					<a href="/" class="text-sm text-gray-400 hover:text-white">← Back to app</a>
				</div>
			</header>

			{#if error}
				<div class="mb-4 rounded-lg bg-red-900/40 border border-red-500/40 px-4 py-3 text-red-300 text-sm">{error}</div>
			{/if}

			<!-- ── Phase 1: Examples ─────────────────────────────────────────── -->
			{#if phase === 'examples'}
				<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">

					<!-- Scan type + examples -->
					<div class="xl:col-span-2 space-y-4">
						<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm">
							<label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Scan type</label>
							<input
								class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
								bind:value={scanType}
								placeholder="e.g. CT chest with IV contrast"
							/>
						</div>

						{#each examples as ex, i}
							<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm space-y-3">
								<div class="flex items-center justify-between">
									<span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Example {i + 1}</span>
									{#if examples.length > 1}
										<button
											class="text-xs text-red-400 hover:text-red-300"
											on:click={() => removeExample(i)}
										>Remove</button>
									{/if}
								</div>
								<input
									class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
									bind:value={ex.label}
									placeholder="Label (optional — e.g. 'Normal chest', 'Lung cancer FU')"
								/>
								<textarea
									class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 font-mono resize-y"
									rows="10"
									bind:value={ex.content}
									placeholder="Paste example report here..."
								></textarea>
							</div>
						{/each}

						<div class="flex gap-3">
							{#if examples.length < 5}
								<button
									class="text-sm text-emerald-400 hover:text-emerald-300 border border-emerald-500/30 rounded-lg px-3 py-1.5 hover:bg-emerald-500/10"
									on:click={addExample}
								>+ Add example</button>
							{/if}
							<button
								class="ml-auto px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
								on:click={analyzeExamples}
								disabled={loading}
							>
								{#if loading}
									<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
								{/if}
								Analyse examples
							</button>
						</div>
					</div>

					<!-- Info panel -->
					<div class="rounded-xl border border-white/10 bg-black/30 p-5 backdrop-blur-sm text-sm text-gray-400 space-y-3 h-fit">
						<p class="text-gray-300 font-medium">How it works</p>
						<p>Paste 1–5 example radiology reports of the same type. The LLM will extract your implicit reporting conventions and generate a <span class="text-emerald-400">Skill Sheet</span>.</p>
						<p>You then refine it via chat — add rules, correct patterns, clarify edge cases. Once happy, test it by generating a report from a sample finding.</p>
						<p class="text-gray-500 text-xs">The skill sheet can be saved into any template's config to guide report generation without needing the wizard.</p>
					</div>
				</div>

			<!-- ── Phase 2: Chat + Skill Sheet ──────────────────────────────── -->
			{:else if phase === 'chat'}
				<div class="grid grid-cols-1 xl:grid-cols-2 gap-6 h-[calc(100vh-160px)]">

					<!-- Chat panel -->
					<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm flex flex-col gap-3">
						<h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Refinement chat</h2>

						<!-- Messages -->
						<div class="flex-1 overflow-y-auto space-y-3 pr-1 min-h-0">
							{#each chatHistory as msg}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									<div
										class="max-w-[85%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap {msg.role === 'user'
											? 'bg-emerald-700/60 text-emerald-50'
											: 'bg-white/8 text-gray-200'}"
									>
										{msg.content}
									</div>
								</div>
							{/each}
							{#if loading}
								<div class="flex justify-start">
									<div class="bg-white/8 rounded-xl px-4 py-2.5 text-sm text-gray-400 flex items-center gap-2">
										<span class="inline-block w-3 h-3 border-2 border-gray-500 border-t-gray-300 rounded-full animate-spin"></span>
										Refining...
									</div>
								</div>
							{/if}
						</div>

						<!-- Input -->
						<div class="flex gap-2">
							<textarea
								class="flex-1 rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none"
								rows="3"
								bind:value={chatInput}
								on:keydown={handleChatKey}
								placeholder="Add a rule, correct a pattern, or ask a question… (Enter to send)"
								disabled={loading}
							></textarea>
							<button
								class="px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-40"
								on:click={sendChat}
								disabled={loading || !chatInput.trim()}
							>Send</button>
						</div>

						<div class="flex gap-2">
							<button
								class="text-xs text-cyan-400 hover:text-cyan-300 border border-cyan-500/30 rounded-lg px-3 py-1.5 hover:bg-cyan-500/10"
								on:click={() => (phase = 'test')}
							>→ Test generation</button>
						</div>
					</div>

					<!-- Skill sheet panel -->
					<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm flex flex-col gap-3">
						<div class="flex items-center justify-between">
							<h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Skill sheet (live)</h2>
							<button
								class="text-xs text-gray-400 hover:text-white border border-white/10 rounded px-2 py-1 hover:bg-white/5"
								on:click={copySkillSheet}
							>Copy</button>
						</div>
						<textarea
							class="flex-1 rounded-lg bg-black/60 border border-white/10 px-3 py-3 text-xs text-gray-200 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-emerald-500 min-h-0"
							bind:value={skillSheet}
							spellcheck="false"
						></textarea>
						<p class="text-xs text-gray-500">You can edit this directly. Changes apply to the next chat turn and test generation.</p>
					</div>
				</div>

			<!-- ── Phase 3: Test generate ────────────────────────────────────── -->
			{:else if phase === 'test'}
				<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">

					<!-- Inputs -->
					<div class="space-y-4">
						<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm space-y-4">
							<h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Test inputs</h2>

							<div>
								<label class="block text-xs text-gray-400 mb-1">Scan type</label>
								<input
									class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
									bind:value={scanType}
								/>
							</div>

							<div>
								<label class="block text-xs text-gray-400 mb-1">Clinical history</label>
								<textarea
									class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-y"
									rows="3"
									bind:value={testClinicalHistory}
									placeholder="e.g. 65F, known RLL adenocarcinoma, post 2 cycles chemo"
								></textarea>
							</div>

							<div>
								<label class="block text-xs text-gray-400 mb-1">Findings / dictation</label>
								<textarea
									class="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-y font-mono"
									rows="8"
									bind:value={testFindings}
									placeholder="Paste raw findings or voice dictation here..."
								></textarea>
							</div>

							<button
								class="w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-sm disabled:opacity-40 flex items-center justify-center gap-2"
								on:click={runTestGenerate}
								disabled={loading || !testFindings.trim() || !skillSheet}
							>
								{#if loading}
									<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
								{/if}
								Generate test report
							</button>
						</div>

						<button
							class="text-xs text-emerald-400 hover:text-emerald-300 border border-emerald-500/30 rounded-lg px-3 py-1.5 hover:bg-emerald-500/10"
							on:click={() => (phase = 'chat')}
						>← Back to refine</button>
					</div>

					<!-- Skill sheet (read-only summary) -->
					<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm flex flex-col gap-3">
						<div class="flex items-center justify-between">
							<h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Active skill sheet</h2>
							<button
								class="text-xs text-gray-400 hover:text-white border border-white/10 rounded px-2 py-1 hover:bg-white/5"
								on:click={copySkillSheet}
							>Copy</button>
						</div>
						<pre class="flex-1 overflow-y-auto text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">{skillSheet}</pre>
					</div>

					<!-- Generated report -->
					<div class="rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm flex flex-col gap-3">
						<div class="flex items-center justify-between">
							<h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Generated report</h2>
							{#if testReport}
								<button
									class="text-xs text-gray-400 hover:text-white border border-white/10 rounded px-2 py-1 hover:bg-white/5"
									on:click={copyReport}
								>Copy</button>
							{/if}
						</div>
						{#if testReport}
							<pre class="flex-1 overflow-y-auto text-sm text-gray-100 whitespace-pre-wrap font-mono leading-relaxed">{testReport}</pre>
						{:else}
							<p class="text-sm text-gray-500 mt-4">Generated report will appear here.</p>
						{/if}
					</div>
				</div>
			{/if}

		</div>
	</div>
{/if}
