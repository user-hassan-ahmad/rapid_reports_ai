<script>
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	// ── State ──────────────────────────────────────────────────────────────────

	let scanType = '';
	let examples = [
		{ label: '', content: '' },
		{ label: '', content: '' },
		{ label: '', content: '' }
	];

	let skillSheet = '';
	let summary = '';
	/** @type {{ role: 'user'|'assistant', content: string }[]} */
	let chatHistory = [];
	let chatInput = '';
	/** @type {{ question: string, suggestions: string[] }[]} */
	let pendingQuestions = [];
	let activeQuestionIdx = -1;

	let sampleFindings = '';
	let testClinicalHistory = '';
	let testFindings = '';
	let testReport = '';

	let phase = /** @type {1|2} */ (1);
	let loading = false;
	let loadingTest = false;
	let error = '';
	let hasGenerated = false;

	let showSaveDialog = false;
	let templateName = '';
	let saving = false;
	let saved = false;

	// ── Helpers ────────────────────────────────────────────────────────────────

	/** @param {string} path @param {Record<string, unknown>} body */
	async function postJson(path, body) {
		/** @type {Record<string, string>} */
		const headers = { 'Content-Type': 'application/json' };
		if ($token) headers['Authorization'] = `Bearer ${$token}`;
		const res = await fetch(`${API_URL}${path}`, {
			method: 'POST', headers, body: JSON.stringify(body)
		});
		const text = await res.text();
		let data;
		try { data = text ? JSON.parse(text) : null; }
		catch { data = { _parseError: true, raw: text }; }
		if (!res.ok) {
			const detail = data?.detail ?? data?.message ?? (typeof data === 'string' ? data : JSON.stringify(data));
			throw new Error(`${res.status} ${res.statusText}: ${detail}`);
		}
		return data;
	}

	function addExample() { if (examples.length < 5) examples = [...examples, { label: '', content: '' }]; }
	function removeExample(i) { if (examples.length > 3) examples = examples.filter((_, idx) => idx !== i); }

	$: filledCount = examples.filter((e) => e.content.trim()).length;
	$: canAnalyse = filledCount >= 3 && scanType.trim() && !loading;

	// ── Actions ────────────────────────────────────────────────────────────────

	async function analyzeExamples() {
		error = '';
		const filled = examples.filter((e) => e.content.trim());
		if (filled.length < 3) { error = 'Please provide at least 3 example reports.'; return; }
		loading = true;
		try {
			const data = await postJson('/api/templates/skill-sheet/analyze', { scan_type: scanType, examples: filled });
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			summary = data.summary || '';
			sampleFindings = data.sample_findings || '';
			testFindings = sampleFindings;
			testClinicalHistory = data.sample_clinical_history || '';
			pendingQuestions = (data.questions || []).slice(0, 3);
			activeQuestionIdx = -1;
			chatHistory = [];
			hasGenerated = false;
			testReport = '';
			phase = 2;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loading = false; }
	}

	async function sendAnswer(/** @type {string} */ msg) {
		if (!msg.trim() || !skillSheet) return;
		chatInput = '';
		let fullMsg = msg;
		if (activeQuestionIdx >= 0 && pendingQuestions[activeQuestionIdx]) {
			fullMsg = `Q: ${pendingQuestions[activeQuestionIdx].question}\nA: ${msg}`;
		}
		if (activeQuestionIdx >= 0) {
			pendingQuestions = pendingQuestions.filter((_, i) => i !== activeQuestionIdx);
			activeQuestionIdx = -1;
		}
		chatHistory = [...chatHistory, { role: 'user', content: msg }];
		loading = true; error = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/refine', {
				skill_sheet: skillSheet, message: fullMsg, chat_history: chatHistory.slice(0, -1)
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			chatHistory = [...chatHistory, { role: 'assistant', content: data.response }];
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			chatHistory = chatHistory.slice(0, -1);
		} finally { loading = false; }
	}

	function handleChatKey(/** @type {KeyboardEvent} */ e) {
		if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAnswer(chatInput); }
	}

	function clickSuggestion(/** @type {number} */ qIdx, /** @type {string} */ suggestion) {
		activeQuestionIdx = qIdx; sendAnswer(suggestion);
	}

	function openCustomAnswer(/** @type {number} */ qIdx) { activeQuestionIdx = qIdx; chatInput = ''; }
	function dismissQuestions() { pendingQuestions = []; activeQuestionIdx = -1; }

	async function runTestGenerate() {
		if (!skillSheet || !testFindings.trim()) return;
		loadingTest = true; error = ''; testReport = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/test-generate', {
				skill_sheet: skillSheet, scan_type: scanType,
				clinical_history: testClinicalHistory, findings_input: testFindings
			});
			if (!data.success) throw new Error(data.error);
			testReport = data.report_content;
			hasGenerated = true;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loadingTest = false; }
	}

	function copyReport() { if (testReport && typeof navigator !== 'undefined') navigator.clipboard.writeText(testReport); }

	async function saveAsTemplate() {
		if (!templateName.trim() || !skillSheet) return;
		saving = true; error = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/save', {
				skill_sheet: skillSheet, scan_type: scanType, template_name: templateName.trim()
			});
			if (!data.success) throw new Error(data.error || 'Save failed');
			showSaveDialog = false; saved = true;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { saving = false; }
	}
</script>

<svelte:head>
	<title>Create Template — RadFlow</title>
</svelte:head>

{#if !$token}
	<div class="min-h-screen flex flex-col items-center justify-center bg-black p-8 text-center">
		<p class="text-gray-300 mb-6">Sign in to create a template.</p>
		<a href="/login" class="btn-primary">Go to login</a>
	</div>
{:else}
	<div class="min-h-screen bg-black text-gray-200">

		<!-- ── Phase 1: Paste reports ─────────────────────────────────────── -->
		{#if phase === 1}
			<div class="p-4 md:p-6 max-w-5xl mx-auto">

				<div class="mb-6">
					<h1 class="text-xl font-semibold text-white mb-1">Create template from examples</h1>
					<p class="text-sm text-gray-400">Paste 3-5 reports of the same scan type. Include a normal, a single finding, and a complex case.</p>
				</div>

				<div class="space-y-4">
					<!-- Scan type -->
					<div class="card-dark">
						<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Scan type</label>
						<input class="input-dark" bind:value={scanType} placeholder="e.g. CT chest with IV contrast, MRI knee, CT staging colorectal" />
					</div>

					<!-- Reports -->
					{#each examples as ex, i}
						<div class="card-dark space-y-3">
							<div class="flex items-center justify-between">
								<label class="text-xs font-medium text-gray-400 uppercase tracking-wider">
									Report {i + 1}
									{#if i < 3}<span class="text-purple-400 ml-1.5">required</span>{/if}
								</label>
								{#if examples.length > 3}
									<button class="btn-sm text-gray-500 hover:text-red-400" on:click={() => removeExample(i)}>Remove</button>
								{/if}
							</div>
							<input class="input-dark" bind:value={ex.label} placeholder="Label — e.g. 'Normal', 'Single PE', 'Complex bilateral'" />
							<textarea class="input-dark font-mono resize-y" rows="8" bind:value={ex.content} placeholder="Paste complete report..."></textarea>
						</div>
					{/each}
				</div>

				<div class="flex items-center gap-4 mt-6">
					{#if examples.length < 5}
						<button class="text-sm text-purple-400 hover:text-purple-300" on:click={addExample}>+ Add report ({examples.length}/5)</button>
					{/if}
					<span class="text-xs text-gray-500">{filledCount} of 3 required</span>
					<button class="btn-primary ml-auto flex items-center gap-2" on:click={analyzeExamples} disabled={!canAnalyse}>
						{#if loading}
							<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							Analysing...
						{:else}
							Analyse my style
						{/if}
					</button>
				</div>
			</div>

		<!-- ── Phase 2: Build + Generate ──────────────────────────────────── -->
		{:else if phase === 2}
			<div style="display: flex; flex-direction: row; height: 100vh; overflow: hidden;">

				<!-- LEFT PANEL -->
				<div style="width: 440px; min-width: 380px; flex-shrink: 0;" class="flex flex-col border-r border-white/10 bg-black">

					<!-- Back -->
					<div class="flex items-center justify-between px-4 py-3 border-b border-white/10">
						<button class="btn-sm text-gray-500 hover:text-gray-300" on:click={() => (phase = 1)}>&larr; Reports</button>
						<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">{scanType}</span>
					</div>

					<!-- Summary -->
					<div class="px-4 py-4 border-b border-white/10">
						<p class="text-sm text-gray-300 leading-relaxed">{summary}</p>
					</div>

					<!-- Chat -->
					<div class="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
						{#each chatHistory as msg}
							{#if msg.role === 'user'}
								<div class="flex justify-end">
									<div class="max-w-[85%] bg-purple-600/20 border border-purple-500/20 rounded-2xl rounded-br-sm px-4 py-2.5 text-sm text-gray-200" style="white-space: pre-wrap;">{msg.content}</div>
								</div>
							{:else}
								<div class="text-sm text-gray-300 leading-relaxed" style="white-space: pre-wrap;">{msg.content}</div>
							{/if}
						{/each}

						{#if loading}
							<div class="text-sm text-gray-500 flex items-center gap-2">
								<span class="inline-block w-3 h-3 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
								Updating style guide...
							</div>
						{/if}

						<!-- Questions -->
						{#if pendingQuestions.length > 0 && !loading}
							{#each pendingQuestions as q, qIdx}
								<div class="card-dark space-y-3">
									<p class="text-sm text-gray-200 leading-relaxed">{q.question}</p>
									<div class="flex flex-wrap gap-2">
										{#each q.suggestions as suggestion}
											<button
												class="text-xs bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 hover:text-purple-200 border border-purple-500/20 hover:border-purple-500/40 rounded-full px-3 py-1.5 transition-all"
												on:click={() => clickSuggestion(qIdx, suggestion)}
											>{suggestion}</button>
										{/each}
										<button
											class="text-xs text-gray-500 hover:text-gray-300 border border-white/10 border-dashed rounded-full px-3 py-1.5 transition-colors"
											on:click={() => openCustomAnswer(qIdx)}
										>Other...</button>
									</div>
								</div>
							{/each}
							<button class="text-xs text-gray-600 hover:text-gray-400" on:click={dismissQuestions}>Skip all — looks good</button>
						{/if}
					</div>

					<!-- Input bar -->
					<div class="px-4 py-3 border-t border-white/10">
						{#if activeQuestionIdx >= 0 && pendingQuestions[activeQuestionIdx]}
							<p class="text-xs text-gray-500 mb-2 truncate">Re: {pendingQuestions[activeQuestionIdx].question}</p>
						{/if}
						<div class="flex gap-2">
							<input
								class="input-dark !py-2"
								bind:value={chatInput}
								on:keydown={handleChatKey}
								placeholder="Add a rule or correction..."
								disabled={loading}
							/>
							<button
								class="btn-accent !px-3.5 !py-2"
								on:click={() => sendAnswer(chatInput)}
								disabled={loading || !chatInput.trim()}
							>&uarr;</button>
						</div>
						{#if activeQuestionIdx >= 0}
							<button class="text-xs text-gray-600 hover:text-gray-400 mt-1" on:click={() => { activeQuestionIdx = -1; }}>Cancel</button>
						{/if}
					</div>
				</div>

				<!-- RIGHT PANEL -->
				<div style="flex: 1; min-width: 0;" class="flex flex-col bg-black">

					<!-- Header -->
					<div class="flex items-center justify-between px-6 py-3 border-b border-white/10">
						<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Report preview</span>
						<div class="flex items-center gap-3">
							{#if testReport}
								<button class="btn-sm text-gray-500 hover:text-gray-300" on:click={copyReport}>Copy</button>
							{/if}
							{#if hasGenerated}
								<button
									class="btn-secondary !px-3 !py-1 text-xs flex items-center gap-1.5"
									on:click={runTestGenerate}
									disabled={loadingTest}
								>
									{#if loadingTest}
										<span class="inline-block w-3 h-3 border-2 border-gray-500 border-t-gray-300 rounded-full animate-spin"></span>
									{/if}
									Regenerate
								</button>
							{/if}
						</div>
					</div>

					<!-- Inputs -->
					<div class="px-6 py-4 border-b border-white/10">
						<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Clinical history</label>
								<textarea class="input-dark resize-none" rows="3" bind:value={testClinicalHistory} placeholder="e.g. 68F progressive knee pain, awaiting surgical review"></textarea>
							</div>
							<div>
								<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
									Findings
									{#if sampleFindings && testFindings === sampleFindings}
										<span class="text-purple-400 font-normal normal-case tracking-normal ml-1">pre-filled</span>
									{/if}
								</label>
								<textarea class="input-dark resize-none font-mono" rows="3" bind:value={testFindings} placeholder="Shorthand — e.g. complex tear PH MM, ICRS IV MFC 25x20mm"></textarea>
							</div>
						</div>
						{#if !hasGenerated}
							<button
								class="btn-primary w-full mt-4 flex items-center justify-center gap-2"
								on:click={runTestGenerate}
								disabled={loadingTest || !testFindings.trim() || !skillSheet}
							>
								{#if loadingTest}
									<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
									Generating...
								{:else}
									Generate report
								{/if}
							</button>
						{/if}
					</div>

					<!-- Report -->
					<div class="flex-1 overflow-y-auto px-6 py-5 min-h-0">
						{#if testReport}
							<pre class="text-sm text-gray-200 whitespace-pre-wrap font-mono leading-relaxed">{testReport}</pre>
						{:else if loadingTest}
							<div class="flex items-center justify-center h-full">
								<span class="inline-block w-5 h-5 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
							</div>
						{:else}
							<div class="flex items-center justify-center h-full">
								<p class="text-sm text-gray-600">Generate a report to preview your template</p>
							</div>
						{/if}
					</div>

					<!-- Bottom bar -->
					<div class="px-6 py-3 border-t border-white/10 flex items-center justify-between">
						{#if saved}
							<p class="text-sm text-purple-400">Template saved. <a href="/templates" class="underline hover:text-purple-300">View templates</a></p>
						{:else if !hasGenerated}
							<p class="text-xs text-gray-600">Generate a test report before saving.</p>
							<div></div>
						{:else if !showSaveDialog}
							<p class="text-xs text-gray-500">Refine on the left, regenerate to check.</p>
							<button class="btn-primary" on:click={() => (showSaveDialog = true)}>Save as template</button>
						{:else}
							<div class="flex items-center gap-3 w-full">
								<input class="input-dark !py-2" bind:value={templateName} placeholder="Template name — e.g. MRI Knee — Dr Smith" />
								<button class="btn-primary !px-5 flex items-center gap-2" on:click={saveAsTemplate} disabled={saving || !templateName.trim()}>
									{#if saving}<span class="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>{/if}
									Save
								</button>
								<button class="btn-sm text-gray-500 hover:text-gray-300" on:click={() => (showSaveDialog = false)}>Cancel</button>
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}

		{#if error}
			<div class="fixed bottom-4 left-1/2 -translate-x-1/2 card-dark !bg-red-900/90 border-red-500/40 px-5 py-3 text-red-200 text-sm shadow-xl z-50 max-w-lg">
				{error}
				<button class="ml-3 text-red-400 hover:text-red-200" on:click={() => (error = '')}>dismiss</button>
			</div>
		{/if}
	</div>
{/if}
