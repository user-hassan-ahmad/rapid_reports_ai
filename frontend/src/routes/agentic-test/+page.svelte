<script>
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import bgCircuit from '$lib/assets/background circuit board effect.png';

	/** Opt-in only: add PUBLIC_ENABLE_AGENTIC_CONSOLE=true to frontend .env and restart dev/build. */
	const consoleEnabled = import.meta.env.PUBLIC_ENABLE_AGENTIC_CONSOLE === 'true';

	let clinicalHistory = '?PE';
	let scanType = 'CT pulmonary angiogram';
	let findings =
		'Filling defects in bilateral lower lobe segmental pulmonary arteries. Right heart strain with RV:LV ratio >1. No pleural effusion.';
	let priorReport = '';
	let skipGuidelines = true;

	let loading = false;
	let error = '';
	let lastEndpoint = '';
	let rawJson = '';
	let planBrief = '';
	let reportPreview = '';
	let metaLine = '';

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

	function resetOutput() {
		error = '';
		rawJson = '';
		planBrief = '';
		reportPreview = '';
		metaLine = '';
	}

	function payload() {
		return {
			clinical_history: clinicalHistory,
			scan_type: scanType,
			findings,
			prior_report: priorReport,
			skip_guidelines: skipGuidelines
		};
	}

	async function runPlan() {
		resetOutput();
		loading = true;
		lastEndpoint = 'POST /api/v2/plan';
		try {
			const data = await postJson('/api/v2/plan', payload());
			rawJson = JSON.stringify(data, null, 2);
			planBrief = data?.plan?.execution_brief ?? '';
			metaLine = `plan_ms: ${data?.plan_ms ?? '—'} ms`;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function runGenerate() {
		resetOutput();
		loading = true;
		lastEndpoint = 'POST /api/v2/generate';
		try {
			const data = await postJson('/api/v2/generate', payload());
			rawJson = JSON.stringify(data, null, 2);
			planBrief = data?.plan?.execution_brief ?? '';
			reportPreview = data?.report_content ?? '';
			const ms = data?.pipeline_ms;
			const viol = data?.plan_adherence_violations;
			metaLine = [
				ms != null ? `pipeline_ms: ${ms} ms` : '',
				Array.isArray(viol) && viol.length ? `violations: ${viol.length}` : 'violations: none'
			]
				.filter(Boolean)
				.join(' · ');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function runCompare() {
		resetOutput();
		loading = true;
		lastEndpoint = 'POST /api/v2/compare';
		try {
			const data = await postJson('/api/v2/compare', payload());
			rawJson = JSON.stringify(data, null, 2);
			planBrief = data?.plan?.execution_brief ?? '';
			const cur = data?.current_output ?? '';
			const ag = data?.agentic_output ?? '';
			reportPreview = `--- CURRENT (${data?.current_ms ?? '?'} ms) ---\n\n${cur}\n\n--- AGENTIC (${data?.agentic_ms ?? '?'} ms) ---\n\n${ag}`;
			metaLine = `current_ms: ${data?.current_ms ?? '—'} · agentic_ms: ${data?.agentic_ms ?? '—'}`;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function runCompareMonolithic() {
		resetOutput();
		loading = true;
		lastEndpoint = 'POST /api/v2/compare-monolithic';
		try {
			const data = await postJson('/api/v2/compare-monolithic', payload());
			rawJson = JSON.stringify(data, null, 2);
			planBrief = '';
			const cl = data?.classic_output ?? '';
			const cc = data?.clinical_clusters_output ?? '';
			reportPreview = `--- CLASSIC MONOLITHIC zai-glm-4.7.json (${data?.classic_ms ?? '?'} ms) ---\n\n${cl}\n\n--- CLINICAL CLUSTERS VARIANT (${data?.clusters_ms ?? '?'} ms) ---\n\n${cc}`;
			metaLine = [
				`classic_ms: ${data?.classic_ms ?? '—'}`,
				`clusters_ms: ${data?.clusters_ms ?? '—'}`,
				data?.model_used ? `model: ${data.model_used}` : ''
			]
				.filter(Boolean)
				.join(' · ');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function copyRaw() {
		if (!rawJson || typeof navigator === 'undefined') return;
		navigator.clipboard.writeText(rawJson);
	}
</script>

<svelte:head>
	<title>Agentic pipeline console — RadFlow</title>
</svelte:head>

{#if !consoleEnabled}
	<div
		class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 p-8 text-center"
	>
		<p class="text-gray-300 mb-4">This debug console is not enabled.</p>
		<p class="text-gray-500 text-sm mb-6">
			Set <code class="text-amber-200/90">PUBLIC_ENABLE_AGENTIC_CONSOLE=true</code> in the frontend
			<code class="text-gray-400">.env</code> (or build env), restart the dev server or rebuild, then open this route again.
		</p>
		<a href="/" class="text-purple-400 hover:text-purple-300">← Back to app</a>
	</div>
{:else if !$token}
	<div
		class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 p-8 text-center relative overflow-hidden"
	>
		<div class="absolute inset-0 pointer-events-none opacity-30">
			<img src={bgCircuit} alt="" class="w-full h-full object-cover mix-blend-overlay" />
		</div>
		<div class="relative z-10 max-w-md">
			<p class="text-gray-200 mb-2">Sign in to call the agentic API.</p>
			<p class="text-gray-500 text-sm mb-6">Your session token is sent as <code class="text-gray-400">Authorization: Bearer</code>.</p>
			<a
				href="/login"
				class="inline-block px-5 py-2.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-medium"
				>Go to login</a
			>
			<p class="mt-6">
				<a href="/" class="text-gray-400 hover:text-white text-sm">← Back to app</a>
			</p>
		</div>
	</div>
{:else}
	<div
		class="min-h-screen bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 text-gray-100 relative overflow-hidden"
	>
		<div class="absolute inset-0 pointer-events-none opacity-20">
			<img src={bgCircuit} alt="" class="w-full h-full object-cover mix-blend-overlay" />
		</div>

		<div class="relative z-10 max-w-6xl mx-auto px-4 py-6 pb-16">
			<header class="flex flex-wrap items-center justify-between gap-4 mb-8 border-b border-white/10 pb-4">
				<div>
					<h1 class="text-2xl font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
						Agentic pipeline console
					</h1>
					<p class="text-sm text-gray-400 mt-1">
						Debug <code class="text-gray-300">/api/v2/plan</code>,
						<code class="text-gray-300">/api/v2/generate</code>,
						<code class="text-gray-300">/api/v2/compare</code>,
						<code class="text-gray-300">/api/v2/compare-monolithic</code>
					</p>
				</div>
				<a href="/" class="text-sm text-purple-300 hover:text-white">← Back to app</a>
			</header>

			<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
				<div class="space-y-4 rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm">
					<h2 class="text-sm font-semibold text-gray-300 uppercase tracking-wide">Request</h2>

					<label class="block" for="at-clinical">
						<span class="text-xs text-gray-500">Clinical history</span>
						<input
							id="at-clinical"
							type="text"
							bind:value={clinicalHistory}
							class="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
						/>
					</label>

					<label class="block" for="at-scan">
						<span class="text-xs text-gray-500">Scan type</span>
						<input
							id="at-scan"
							type="text"
							bind:value={scanType}
							class="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
						/>
					</label>

					<label class="block" for="at-findings">
						<span class="text-xs text-gray-500">Findings</span>
						<textarea
							id="at-findings"
							bind:value={findings}
							rows="6"
							class="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-2 text-sm font-mono focus:border-purple-500 focus:outline-none"
						></textarea>
					</label>

					<label class="block" for="at-prior">
						<span class="text-xs text-gray-500">Prior report (optional)</span>
						<textarea
							id="at-prior"
							bind:value={priorReport}
							rows="3"
							class="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
						></textarea>
					</label>

					<label class="flex items-center gap-2 cursor-pointer">
						<input type="checkbox" bind:checked={skipGuidelines} class="rounded border-white/20" />
						<span class="text-sm text-gray-300">Skip guideline fetch (Phase 1.5)</span>
					</label>

					<div class="flex flex-wrap gap-2 pt-2">
						<button
							type="button"
							disabled={loading}
							onclick={runPlan}
							class="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-sm font-medium"
						>
							Plan only
						</button>
						<button
							type="button"
							disabled={loading}
							onclick={runGenerate}
							class="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-sm font-medium"
						>
							Full generate
						</button>
						<button
							type="button"
							disabled={loading}
							onclick={runCompare}
							class="px-4 py-2 rounded-lg bg-blue-600/80 hover:bg-blue-500 disabled:opacity-50 text-sm font-medium"
						>
							Compare A/B
						</button>
						<button
							type="button"
							disabled={loading}
							onclick={runCompareMonolithic}
							class="px-4 py-2 rounded-lg bg-teal-600/80 hover:bg-teal-500 disabled:opacity-50 text-sm font-medium"
						>
							Compare monolithic prompts
						</button>
					</div>
					<p class="text-xs text-gray-500">
						Compare A/B needs Anthropic + Cerebras (+ Groq when plan confidence is not high). Compare monolithic prompts:
						Anthropic + Cerebras (two runs of the primary report model with different JSON prompts). Plan / Generate need
						Cerebras.
					</p>
				</div>

				<div class="space-y-4 rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur-sm min-h-[320px]">
					<div class="flex items-center justify-between gap-2">
						<h2 class="text-sm font-semibold text-gray-300 uppercase tracking-wide">Response</h2>
						{#if rawJson}
							<button
								type="button"
								onclick={copyRaw}
								class="text-xs text-purple-400 hover:text-purple-300"
							>
								Copy JSON
							</button>
						{/if}
					</div>

					{#if loading}
						<p class="text-gray-400 animate-pulse">Running {lastEndpoint}…</p>
					{:else if error}
						<div class="rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-200 whitespace-pre-wrap">
							{error}
						</div>
					{:else if !rawJson}
						<p class="text-gray-500 text-sm">Run an action to see the response.</p>
					{/if}

					{#if metaLine}
						<p class="text-xs text-gray-500">{metaLine}</p>
					{/if}
					{#if lastEndpoint}
						<p class="text-xs text-gray-600">{lastEndpoint}</p>
					{/if}

					{#if planBrief}
						<div>
							<h3 class="text-xs font-semibold text-amber-200/90 mb-1">execution_brief</h3>
							<pre
								class="text-xs text-gray-300 whitespace-pre-wrap max-h-48 overflow-auto rounded border border-white/10 bg-black/60 p-3">{planBrief}</pre>
						</div>
					{/if}

					{#if reportPreview}
						<div>
							<h3 class="text-xs font-semibold text-emerald-200/90 mb-1">
								{lastEndpoint === 'POST /api/v2/compare-monolithic'
									? 'Monolithic prompt compare'
									: 'Report / compare output'}
							</h3>
							<pre
								class="text-xs text-gray-300 whitespace-pre-wrap max-h-96 overflow-auto rounded border border-white/10 bg-black/60 p-3">{reportPreview}</pre>
						</div>
					{/if}

					{#if rawJson}
						<div>
							<h3 class="text-xs font-semibold text-gray-400 mb-1">Full JSON</h3>
							<pre
								class="text-xs text-gray-400 whitespace-pre-wrap max-h-[28rem] overflow-auto rounded border border-white/5 bg-black/30 p-3 font-mono">{rawJson}</pre>
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
