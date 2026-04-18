<script>
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	// ── Inputs ──
	let scanType = '';
	let clinicalHistory = '';
	let findings = '';

	// ── Analyser output ──
	let skillSheet = '';
	let analyserLatency = 0;
	let analyserModel = '';

	// ── Generator output ──
	let reportContent = '';
	let reportDescription = '';
	let generatorLatency = 0;
	let generatorModel = '';

	// ── Model selector (proto A/B) ──
	const MODEL_OPTIONS = [
		// Proprietary
		{ value: 'zai-glm-4.7', label: 'GLM-4.7 (Cerebras)', group: 'Proprietary' },
		{ value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', group: 'Proprietary' },
		// Open source
		{ value: 'gpt-oss-120b', label: 'GPT-OSS-120B (Cerebras)', group: 'Open source' },
		{ value: 'qwen-3-235b-a22b-instruct-2507', label: 'Qwen 3 235B (Cerebras)', group: 'Open source' },
		{ value: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B (Groq)', group: 'Open source' },
		{ value: 'qwen/qwen3-32b', label: 'Qwen 3 32B (Groq)', group: 'Open source' },
	];
	let selectedModel = 'zai-glm-4.7';

	// ── Shared ──
	let runId = '';
	let sheetId = '';  // persisted ephemeral_skill_sheets.id from /analyse
	let reportId = ''; // persisted reports.id from /generate
	let loadingAnalyse = false;
	let loadingGenerate = false;
	let error = '';

	$: canAnalyse = scanType.trim() && clinicalHistory.trim() && !loadingAnalyse;
	$: canGenerate = skillSheet && findings.trim() && !loadingGenerate;

	// ── Helpers ──
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

	/** @param {number} ms */
	function formatLatency(ms) {
		if (!ms) return '';
		if (ms < 1000) return `${ms} ms`;
		return `${(ms / 1000).toFixed(1)} s`;
	}

	/** @param {string} text */
	async function copyText(text) {
		try { await navigator.clipboard.writeText(text); } catch {}
	}

	// ── Actions ──
	async function runAnalyse() {
		error = '';
		skillSheet = '';
		reportContent = '';
		runId = '';
		sheetId = '';
		reportId = '';
		loadingAnalyse = true;
		try {
			const data = await postJson('/api/quick-report-proto/analyse', {
				scan_type: scanType.trim(),
				clinical_history: clinicalHistory.trim(),
			});
			if (!data.success) throw new Error(data.error || 'Analyser failed');
			skillSheet = data.skill_sheet || '';
			analyserLatency = data.latency_ms || 0;
			analyserModel = data.model_used || '';
			runId = data.run_id || '';
			sheetId = data.sheet_id || '';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingAnalyse = false;
		}
	}

	async function runGenerate() {
		error = '';
		reportContent = '';
		loadingGenerate = true;
		try {
			const data = await postJson('/api/quick-report-proto/generate', {
				skill_sheet: skillSheet,
				scan_type: scanType.trim(),
				clinical_history: clinicalHistory.trim(),
				findings: findings.trim(),
				run_id: runId || null,
				model: selectedModel,
				sheet_id: sheetId || null,
			});
			if (!data.success) throw new Error(data.error || 'Generator failed');
			reportContent = data.report_content || '';
			reportDescription = data.description || '';
			generatorLatency = data.latency_ms || 0;
			generatorModel = data.model_used || '';
			runId = data.run_id || runId;
			reportId = data.report_id || '';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingGenerate = false;
		}
	}
</script>

<svelte:head>
	<title>Quick Report Proto — End-to-end analyser test</title>
</svelte:head>

{#if !$token}
	<div class="min-h-screen bg-black flex items-center justify-center">
		<p class="text-gray-500 text-sm">Not logged in. Sign in from the main app.</p>
	</div>
{:else}
	<div class="min-h-screen bg-black text-gray-200">
		<!-- ── Top bar ── -->
		<header class="flex items-center justify-between px-6 py-3 border-b border-white/10">
			<div class="flex items-center gap-4">
				<a href="/home" class="btn-sm text-gray-500 hover:text-gray-300">&larr; Home</a>
				<span class="text-sm font-medium text-gray-300">Quick Report Proto</span>
				<span class="text-xs text-gray-600">End-to-end analyser + generator stress test</span>
			</div>
			<div class="flex items-center gap-3 text-xs text-gray-500">
				{#if runId}
					<button
						class="font-mono text-purple-400 hover:text-purple-300"
						on:click={() => copyText(runId)}
						title="Click to copy"
					>run: {runId}</button>
				{/if}
				<span class="font-mono opacity-60">/tmp/radflow_quick_proto.log</span>
			</div>
		</header>

		<main class="max-w-5xl mx-auto px-6 py-8 space-y-6">

			<!-- ── Step 1: Scan context ── -->
			<section class="card-dark">
				<div class="flex items-baseline justify-between mb-4">
					<div>
						<h2 class="text-sm font-medium text-gray-200 uppercase tracking-wider">
							<span class="text-purple-400">Step 1</span> &middot; Scan context
						</h2>
						<p class="text-xs text-gray-500 mt-1">
							Captured at workspace creation in production. Analyser fires here — in parallel with dictation.
						</p>
					</div>
					{#if analyserLatency}
						<span class="text-xs text-gray-500 font-mono">
							analyser · {formatLatency(analyserLatency)} · {analyserModel}
						</span>
					{/if}
				</div>

				<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
					<div>
						<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Scan type</label>
						<input
							class="input-dark"
							bind:value={scanType}
							placeholder="e.g. CT abdomen and pelvis with contrast"
							disabled={loadingAnalyse}
						/>
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Clinical history</label>
						<textarea
							class="input-dark resize-none"
							rows="3"
							bind:value={clinicalHistory}
							placeholder="e.g. RIF pain, raised WCC, ?appendicitis"
							disabled={loadingAnalyse}
						></textarea>
					</div>
				</div>

				<button
					class="btn-primary mt-4 flex items-center gap-2"
					on:click={runAnalyse}
					disabled={!canAnalyse}
				>
					{#if loadingAnalyse}
						<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
						Generating skill sheet...
					{:else if skillSheet}
						Re-generate skill sheet
					{:else}
						Generate skill sheet
					{/if}
				</button>
			</section>

			<!-- ── Step 2: Skill sheet ── -->
			{#if skillSheet || loadingAnalyse}
				<section class="card-dark">
					<div class="flex items-baseline justify-between mb-4">
						<div>
							<h2 class="text-sm font-medium text-gray-200 uppercase tracking-wider">
								<span class="text-purple-400">Step 2</span> &middot; Bespoke skill sheet
							</h2>
							<p class="text-xs text-gray-500 mt-1">
								Ephemeral — inferred from scan type + clinical history via the 8-phase framework. This is the load-bearing artefact to eyeball.
							</p>
						</div>
						{#if skillSheet}
							<button
								class="btn-sm text-gray-500 hover:text-gray-300"
								on:click={() => copyText(skillSheet)}
							>Copy</button>
						{/if}
					</div>

					{#if loadingAnalyse}
						<div class="flex items-center justify-center py-16">
							<span class="inline-block w-5 h-5 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
						</div>
					{:else}
						<pre class="text-sm text-gray-200 whitespace-pre-wrap font-mono leading-relaxed max-h-[60vh] overflow-y-auto p-4 bg-black/40 border border-white/5 rounded">{skillSheet}</pre>
					{/if}
				</section>
			{/if}

			<!-- ── Step 3: Findings + Report ── -->
			{#if skillSheet}
				<section class="card-dark">
					<div class="flex items-baseline justify-between mb-4">
						<div>
							<h2 class="text-sm font-medium text-gray-200 uppercase tracking-wider">
								<span class="text-purple-400">Step 3</span> &middot; Findings → Report
							</h2>
							<p class="text-xs text-gray-500 mt-1">
								Generator composes global style guide + skill sheet + findings. Same skill_sheet_guided path as templates.
							</p>
						</div>
						<div class="flex items-center gap-3">
							<select
								class="input-dark !py-1 !px-2 text-xs font-mono"
								bind:value={selectedModel}
								disabled={loadingGenerate}
								title="Generator model (proto only)"
							>
								<optgroup label="Proprietary">
									{#each MODEL_OPTIONS.filter(o => o.group === 'Proprietary') as opt}
										<option value={opt.value}>{opt.label}</option>
									{/each}
								</optgroup>
								<optgroup label="Open source">
									{#each MODEL_OPTIONS.filter(o => o.group === 'Open source') as opt}
										<option value={opt.value}>{opt.label}</option>
									{/each}
								</optgroup>
							</select>
							{#if generatorLatency}
								<span class="text-xs text-gray-500 font-mono">
									{formatLatency(generatorLatency)} · {generatorModel}
								</span>
							{/if}
						</div>
					</div>

					<div>
						<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Findings (dictation)</label>
						<textarea
							class="input-dark font-mono resize-y"
							rows="6"
							bind:value={findings}
							placeholder="Shorthand or prose — e.g. dilated appendix 11mm, peri-app fat stranding, small pelvic free fluid, no abscess"
							disabled={loadingGenerate}
						></textarea>
					</div>

					<button
						class="btn-primary mt-4 flex items-center gap-2"
						on:click={runGenerate}
						disabled={!canGenerate}
					>
						{#if loadingGenerate}
							<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
							Generating report...
						{:else if reportContent}
							Re-generate report
						{:else}
							Generate report
						{/if}
					</button>

					{#if reportContent || loadingGenerate}
						<div class="mt-6 border-t border-white/10 pt-4">
							<div class="flex items-baseline justify-between mb-3">
								<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Report</span>
								{#if reportContent}
									<div class="flex items-center gap-3">
										{#if reportDescription}
											<span class="text-xs text-gray-500 italic">{reportDescription}</span>
										{/if}
										<button
											class="btn-sm text-gray-500 hover:text-gray-300"
											on:click={() => copyText(reportContent)}
										>Copy</button>
									</div>
								{/if}
							</div>
							{#if loadingGenerate}
								<div class="flex items-center justify-center py-16">
									<span class="inline-block w-5 h-5 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
								</div>
							{:else}
								<pre class="text-sm text-gray-200 whitespace-pre-wrap font-mono leading-relaxed p-4 bg-black/40 border border-white/5 rounded">{reportContent}</pre>
							{/if}
						</div>
					{/if}
				</section>
			{/if}

			{#if error}
				<div class="card-dark border-red-500/40">
					<p class="text-sm text-red-400">{error}</p>
				</div>
			{/if}

			<!-- Footer hint -->
			<p class="text-xs text-gray-600 text-center pt-4 pb-8">
				Full logs written to <span class="font-mono">/tmp/radflow_quick_proto.log</span>.
				Grep by <span class="font-mono">run_id</span> to extract a single case.
			</p>
		</main>
	</div>
{/if}
