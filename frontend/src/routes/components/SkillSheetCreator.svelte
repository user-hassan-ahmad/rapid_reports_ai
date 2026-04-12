<script>
	import { createEventDispatcher, onMount, tick } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { tagsStore } from '$lib/stores/tags';
	import { getTagColor } from '$lib/utils/tagColors.js';
	import { fade, fly } from 'svelte/transition';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	import StructureTree from './skill-sheet-summary/StructureTree.svelte';
	import VoicePhrases from './skill-sheet-summary/VoicePhrases.svelte';
	import ConventionRules from './skill-sheet-summary/ConventionRules.svelte';
	import ImpressionFlow from './skill-sheet-summary/ImpressionFlow.svelte';

	marked.setOptions({ breaks: true, gfm: true });

	/** @param {string} md */
	function renderMarkdown(md) {
		if (!md) return '';
		return DOMPurify.sanitize(/** @type {string} */ (marked.parse(md)));
	}

	/**
	 * Coerce a backend value to a string. The LLM sometimes returns
	 * arrays of bullets or nested objects where we expect plain text.
	 * @param {unknown} v
	 * @returns {string}
	 */
	function coerceToText(v) {
		if (v == null) return '';
		if (typeof v === 'string') return v;
		if (Array.isArray(v)) return v.map((item) => coerceToText(item)).join('\n');
		if (typeof v === 'object') {
			try { return JSON.stringify(v, null, 2); } catch { return ''; }
		}
		return String(v);
	}

	const dispatch = createEventDispatcher();

	// ── State ──────────────────────────────────────────────────────────────────

	// Phase 1 — examples
	let scanType = '';
	let protocolNotes = '';
	const exampleHints = ['Report 1', 'Report 2', 'Report 3'];
	let examples = [
		{ label: '', content: '' },
		{ label: '', content: '' },
		{ label: '', content: '' }
	];
	let activeExampleTab = 0;

	// Phase 2 — workbench
	let skillSheet = '';
	/** @type {{
	 *   structure?: { sections: { name: string, paragraphs: string[] }[] },
	 *   voice?: { description: string, phrases: string[] },
	 *   conventions?: { rules: { title: string, detail: string }[] },
	 *   impression?: { flow: string[], detail: string }
	 * } | null} */
	let summary = null;
	/** @type {{ role: 'user'|'assistant', content: string }[]} */
	let chatHistory = [];
	let chatInput = '';

	// Questions — unified model: each Q has question, suggestions, and a status
	/** @type {{ question: string, suggestions: string[], status: 'pending'|'answered'|'skipped', answer: string }[]} */
	let questions = [];
	let activeQuestionIdx = -1; // which Q has the custom input open

	let sampleFindings = '';
	let sampleClinicalHistory = '';
	let testClinicalHistory = '';
	let testFindings = '';
	let testReport = '';

	// Compare-with-previous flipper for the report preview.
	// Single-column "blink comparator": flip between previous and current
	// in place, scroll position preserved, so the eye picks up real diffs.
	let prevReport = '';
	let compareMode = false;
	/** @type {'previous' | 'current'} */
	let compareView = 'previous';
	/** @type {HTMLDivElement | null} */
	let reportScrollEl = null;

	// Snapshot of the inputs at the time of the last successful analysis.
	// Used to offer "Resume workbench" when the user navigates back to Phase 1
	// without changing anything, and to flag stale state when they have.
	let lastAnalyzedSnapshot = '';

	let phase = /** @type {1|2} */ (1);
	/** @type {'summary'|'questions'|'test'|'refine'} */
	let stage = 'summary';
	let loading = false;
	let loadingTest = false;
	let error = '';
	let hasGenerated = false;

	let showSaveDialog = false;
	let templateName = '';
	/** @type {string[]} */
	let tags = [];
	let newTag = '';
	let saving = false;
	let saved = false;

	$: existingTags = /** @type {string[]} */ ($tagsStore.tags || []);
	$: tagSuggestions = newTag.trim()
		? existingTags
				.filter((t) => t.toLowerCase().includes(newTag.trim().toLowerCase()))
				.filter((t) => !tags.some((existing) => existing.toLowerCase() === t.toLowerCase()))
				.slice(0, 6)
		: [];

	onMount(async () => {
		if (!$tagsStore.tags || $tagsStore.tags.length === 0) {
			await tagsStore.loadTags();
		}
	});

	/** @param {string} [tagToAdd] */
	function addTag(tagToAdd) {
		const raw = (tagToAdd ?? newTag).trim();
		if (!raw) return;
		const match = existingTags.find((t) => t.toLowerCase() === raw.toLowerCase());
		const finalTag = match || raw;
		if (tags.some((t) => t.toLowerCase() === finalTag.toLowerCase())) {
			newTag = '';
			return;
		}
		tags = [...tags, finalTag];
		newTag = '';
	}

	/** @param {string} tag */
	function removeTag(tag) {
		tags = tags.filter((t) => t !== tag);
	}

	/** @param {KeyboardEvent} e */
	function handleTagKeydown(e) {
		if (e.key === 'Enter') {
			e.preventDefault();
			addTag();
		} else if (e.key === 'Backspace' && !newTag && tags.length > 0) {
			tags = tags.slice(0, -1);
		}
	}

	// Stage navigation
	const stageOrder = /** @type {const} */ (['summary', 'questions', 'test', 'refine']);
	const stageLabels = { summary: 'Style', questions: 'Questions', test: 'Test', refine: 'Refine' };
	const stageDescriptions = {
		summary: "Here's what we learned from your reports",
		questions: 'We have a few questions to fine-tune your template',
		test: 'Review the pre-filled test case, edit if needed, then generate',
		refine: 'Add corrections or rules — regenerate to see the effect'
	};
	$: stageIdx = stageOrder.indexOf(stage);

	// Track highest stage reached (0-3) — never decreases on back-navigation
	let maxStageReached = 0;

	function goToStage(/** @type {typeof stage} */ s) {
		stage = s;
		const idx = stageOrder.indexOf(s);
		if (idx > maxStageReached) maxStageReached = idx;
	}
	function nextStage() {
		const next = stageOrder[stageIdx + 1];
		if (next) goToStage(next);
	}

	$: canNavigate = stageOrder.map((_, i) => i <= maxStageReached);
	$: pendingCount = questions.filter(q => q.status === 'pending').length;
	$: allQuestionsResolved = questions.length > 0 && pendingCount === 0;

	// Copy button state
	let copyConfirm = false;
	function copyReportWithConfirm() {
		if (testReport && typeof navigator !== 'undefined') {
			navigator.clipboard.writeText(testReport);
			copyConfirm = true;
			setTimeout(() => { copyConfirm = false; }, 2000);
		}
	}

	function toggleCompareMode() {
		compareMode = !compareMode;
		if (compareMode) compareView = 'previous';
	}

	/** @param {'previous' | 'current'} [target] */
	async function flipCompare(target) {
		const next = target ?? (compareView === 'previous' ? 'current' : 'previous');
		if (next === compareView) return;
		const scrollTop = reportScrollEl?.scrollTop ?? 0;
		compareView = next;
		await tick();
		if (reportScrollEl) reportScrollEl.scrollTop = scrollTop;
	}

	/** @param {KeyboardEvent} e */
	function handleCompareKeydown(e) {
		if (!compareMode) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			compareMode = false;
			return;
		}
		if (e.key === ' ' || e.code === 'Space') {
			const tag = typeof document !== 'undefined' ? document.activeElement?.tagName : '';
			if (tag === 'INPUT' || tag === 'TEXTAREA') return;
			e.preventDefault();
			flipCompare();
		}
	}

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
	$: currentExamplesSnapshot = JSON.stringify({
		scanType,
		protocolNotes,
		examples: examples.map((e) => ({ label: e.label, content: e.content }))
	});
	$: hasResumableAnalysis = skillSheet !== '' && lastAnalyzedSnapshot === currentExamplesSnapshot;
	$: hasStaleAnalysis =
		skillSheet !== '' && lastAnalyzedSnapshot !== '' && lastAnalyzedSnapshot !== currentExamplesSnapshot;

	// ── Actions ────────────────────────────────────────────────────────────────

	async function analyzeExamples() {
		error = '';
		const filled = examples.filter((e) => e.content.trim());
		if (filled.length < 3) { error = 'Please provide at least 3 example reports.'; return; }
		loading = true;
		try {
			const data = await postJson('/api/templates/skill-sheet/analyze', {
				scan_type: scanType,
				protocol_notes: protocolNotes.trim(),
				examples: filled
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			summary = (typeof data.summary === 'object' && data.summary !== null) ? data.summary : null;
			sampleFindings = coerceToText(data.sample_findings);
			sampleClinicalHistory = coerceToText(data.sample_clinical_history);
			testFindings = sampleFindings;
			testClinicalHistory = sampleClinicalHistory;
			questions = (data.questions || []).slice(0, 3).map(q => ({
				question: q.question,
				suggestions: q.suggestions || [],
				status: /** @type {'pending'} */ ('pending'),
				answer: ''
			}));
			activeQuestionIdx = -1;
			chatHistory = [];
			hasGenerated = false;
			testReport = '';
			prevReport = '';
			maxStageReached = 0;
			stage = 'summary';
			lastAnalyzedSnapshot = currentExamplesSnapshot;
			phase = 2;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loading = false; }
	}

	async function sendAnswer(/** @type {string} */ msg) {
		if (!msg.trim() || !skillSheet) return;
		chatInput = '';
		let fullMsg = msg;

		// If answering a specific question, mark it
		if (activeQuestionIdx >= 0 && questions[activeQuestionIdx]) {
			const q = questions[activeQuestionIdx];
			fullMsg = `Q: ${q.question}\nA: ${msg}`;
			questions[activeQuestionIdx] = { ...q, status: 'answered', answer: msg };
			questions = questions; // trigger reactivity
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
	function skipQuestion(/** @type {number} */ qIdx) {
		questions[qIdx] = { ...questions[qIdx], status: 'skipped', answer: '' };
		questions = questions;
	}
	function unskipQuestion(/** @type {number} */ qIdx) {
		questions[qIdx] = { ...questions[qIdx], status: 'pending', answer: '' };
		questions = questions;
	}
	function skipAllQuestions() {
		questions = questions.map(q => q.status === 'pending' ? { ...q, status: 'skipped' } : q);
		goToStage('test');
	}

	async function runTestGenerate() {
		if (!skillSheet || !testFindings.trim()) return;
		loadingTest = true;
		error = '';
		prevReport = testReport;
		testReport = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/test-generate', {
				skill_sheet: skillSheet,
				scan_type: scanType,
				clinical_history: testClinicalHistory,
				findings_input: testFindings
			});
			if (!data.success) throw new Error(data.error);
			testReport = coerceToText(data.report_content);
			hasGenerated = true;
			goToStage('refine');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingTest = false;
		}
	}

	// copyReport removed — use copyReportWithConfirm instead

	/** @param {string} md */
	function extractSkillSheetName(md) {
		const m = md.match(/^#\s*Skill Sheet:\s*(.+)$/m);
		return m ? m[1].trim() : '';
	}

	function openSaveDialog() {
		if (!templateName.trim()) templateName = extractSkillSheetName(skillSheet);
		showSaveDialog = true;
	}

	async function saveAsTemplate() {
		if (!templateName.trim() || !skillSheet) return;
		saving = true; error = '';
		try {
			const data = await postJson('/api/templates/skill-sheet/save', {
				skill_sheet: skillSheet,
				scan_type: scanType,
				template_name: templateName.trim(),
				tags
			});
			if (!data.success) throw new Error(data.error || 'Save failed');
			showSaveDialog = false; saved = true;
			tagsStore.refreshTags();
			dispatch('templateCreated');
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { saving = false; }
	}

	function handleClose() { dispatch('close'); }
</script>

<svelte:window on:keydown={handleCompareKeydown} />

<!-- ── Phase 1: Paste Reports ──────────────────────────────────────────── -->
{#if phase === 1}
	<div class="max-w-4xl mx-auto">
		<div class="flex items-center justify-between mb-6">
			<div>
				<h2 class="text-xl font-semibold text-white tracking-tight">Create from examples</h2>
				<p class="text-sm text-gray-400 mt-1">Paste 3–5 reports to teach RadFlow your reporting style.</p>
			</div>
			<button class="btn-ghost text-sm" on:click={handleClose}>Cancel</button>
		</div>

		<!-- Scan type + protocol notes -->
		<div class="card-dark mb-4 space-y-4">
			<div>
				<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Scan type</label>
				<input class="input-dark" bind:value={scanType} placeholder="e.g. CT chest with IV contrast, MRI knee, CT staging colorectal" />
			</div>
			<div>
				<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
					Context notes <span class="text-gray-600 normal-case tracking-normal font-normal">— optional</span>
				</label>
				<textarea
					class="input-dark resize-y"
					rows="2"
					bind:value={protocolNotes}
					placeholder="What's this scan typically for, and anything about the protocol worth flagging? Otherwise we'll infer from the reports."
				></textarea>
			</div>
		</div>

		<!-- Tabbed report card -->
		<div class="card-dark !p-0 overflow-hidden">
			<div class="flex items-center border-b border-white/[0.06] px-1 pt-1">
				{#each examples as ex, i}
					<button
						class="relative flex items-center gap-2 px-4 py-2.5 text-sm transition-all duration-200 rounded-t-lg
							{activeExampleTab === i ? 'text-white bg-white/[0.05]' : (i >= 3 ? 'text-gray-600 hover:text-gray-400' : 'text-gray-400 hover:text-white hover:bg-white/[0.03]')}
							{i >= 3 ? 'text-xs' : ''}"
						on:click={() => { activeExampleTab = i; }}
					>
						{#if ex.content.trim()}
							<span class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></span>
						{:else if i < 3}
							<span class="w-2 h-2 rounded-full bg-purple-500/60 animate-pulse shrink-0"></span>
						{:else}
							<span class="w-1.5 h-1.5 rounded-full bg-gray-700 shrink-0"></span>
						{/if}
						<span>Report {i + 1}</span>
						{#if i >= 3 && examples.length > 3}
							<button class="ml-1 text-gray-600 hover:text-red-400 transition-colors" on:click|stopPropagation={() => { removeExample(i); if (activeExampleTab >= examples.length) activeExampleTab = examples.length - 1; }}>&times;</button>
						{/if}
						{#if activeExampleTab === i}
							<div class="absolute bottom-0 left-2 right-2 h-[2px] bg-purple-500 rounded-full"></div>
						{/if}
					</button>
				{/each}
				{#if examples.length < 5}
					<button class="px-3 py-2.5 text-gray-600 hover:text-gray-400 text-sm transition-colors" on:click={() => { addExample(); activeExampleTab = examples.length - 1; }} title="Add another report (optional)">+</button>
				{/if}
			</div>
			<p class="px-5 pt-3 pb-0 text-[11px] text-gray-600">For best results, include a mix — a straightforward case, one with findings, and a complex one.</p>
			<div class="p-5 pt-2 space-y-3">
				<div class="flex items-center justify-between">
					<label class="text-xs font-medium text-gray-400 uppercase tracking-wider">
						Report {activeExampleTab + 1}
						{#if activeExampleTab < 3}<span class="text-purple-400 ml-1.5">required</span>{/if}
					</label>
					{#if examples[activeExampleTab]?.content.trim()}
						<span class="text-xs text-emerald-500">{examples[activeExampleTab].content.length} chars</span>
					{/if}
				</div>
				<input class="input-dark" bind:value={examples[activeExampleTab].label} placeholder="Describe the case..." />
				<textarea class="input-dark resize-y" rows="14" bind:value={examples[activeExampleTab].content} placeholder="Paste complete report..."></textarea>
			</div>
		</div>

		<div class="flex items-center justify-between mt-5">
			<div class="flex items-center gap-3">
				<span class="text-xs text-gray-500">{filledCount} of 3 required</span>
				{#if hasStaleAnalysis}
					<span class="text-xs text-amber-500/80 flex items-center gap-1.5">
						<span class="w-1 h-1 rounded-full bg-amber-500/80"></span>
						Changes since last analysis — re-analyse to apply
					</span>
				{/if}
			</div>
			<div class="flex items-center gap-3">
				{#if hasResumableAnalysis}
					<button class="btn-ghost flex items-center gap-2 text-sm" on:click={() => (phase = 2)}>
						Resume workbench
						<span>&rarr;</span>
					</button>
				{/if}
				<button class="btn-primary flex items-center gap-2" on:click={analyzeExamples} disabled={!canAnalyse}>
					{#if loading}
						<span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
						Analysing...
					{:else}
						Analyse my style
					{/if}
				</button>
			</div>
		</div>
	</div>

<!-- ── Phase 2: Workbench ──────────────────────────────────────────────── -->
{:else if phase === 2}
	<div class="flex gap-0 -mx-4 md:-mx-6 -mb-4 md:-mb-6" style="height: calc(100vh - 80px);">

		<!-- LEFT PANEL: Sliding stages -->
		<div style="width: 42%; min-width: 380px; max-width: 560px; flex-shrink: 0;" class="flex flex-col border-r border-white/10 bg-black/30 backdrop-blur-xl">

			<!-- Header: back + scan type -->
			<div class="flex items-center justify-between px-5 py-3 border-b border-white/[0.06] shrink-0">
				<button class="text-xs text-gray-500 hover:text-gray-300 transition-colors" on:click={() => { phase = 1; }}>&larr; Reports</button>
				<span class="text-xs font-medium text-gray-400 uppercase tracking-wider truncate ml-2">{scanType}</span>
			</div>

			<!-- Stage indicator -->
			<div class="flex items-center gap-1 px-5 py-2.5 border-b border-white/[0.06] shrink-0">
				{#each stageOrder as s, i}
					<button
						class="flex items-center gap-1.5 text-xs transition-all duration-200
							{stage === s ? 'text-white' : canNavigate[i] ? 'text-gray-500 hover:text-gray-300' : 'text-gray-700'}"
						on:click={() => { if (canNavigate[i]) goToStage(s); }}
						disabled={!canNavigate[i]}
					>
						{#if canNavigate[i] && stage !== s}
							<svg class="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
						{:else if stage === s}
							<span class="w-1.5 h-1.5 rounded-full bg-purple-500"></span>
						{:else}
							<span class="w-1.5 h-1.5 rounded-full bg-gray-700"></span>
						{/if}
						<span>{stageLabels[s]}</span>
					</button>
					{#if i < stageOrder.length - 1}
						<span class="text-gray-700 text-xs mx-0.5">/</span>
					{/if}
				{/each}
			</div>

			<!-- Stage content (sliding) -->
			<div class="flex-1 flex flex-col min-h-0 overflow-hidden">

				<!-- STAGE: Summary -->
				{#if stage === 'summary'}
					<div class="flex-1 flex flex-col min-h-0" in:fly={{ x: -20, duration: 200 }}>
						<p class="text-sm text-gray-400 px-5 pt-4 pb-3 shrink-0">{stageDescriptions.summary}</p>
						<div class="flex-1 overflow-y-auto overflow-x-hidden min-w-0 px-5 pb-4">
							{#if summary}
								<div class="space-y-7 pt-1">
									<!-- Structure -->
									{#if summary.structure && summary.structure.sections}
										<section>
											<div class="flex items-center gap-2 mb-3">
												<span class="text-[10px] text-gray-500 uppercase tracking-[0.25em] font-mono">Structure</span>
												<div class="flex-1 h-px bg-white/[0.06]"></div>
											</div>
											<StructureTree sections={summary.structure.sections} />
										</section>
									{/if}

									<!-- Voice -->
									{#if summary.voice}
										<section>
											<div class="flex items-center gap-2 mb-3">
												<span class="text-[10px] text-gray-500 uppercase tracking-[0.25em] font-mono">Voice</span>
												<div class="flex-1 h-px bg-white/[0.06]"></div>
											</div>
											<VoicePhrases description={summary.voice.description} phrases={summary.voice.phrases || []} />
										</section>
									{/if}

									<!-- Conventions -->
									{#if summary.conventions && summary.conventions.rules}
										<section>
											<div class="flex items-center gap-2 mb-3">
												<span class="text-[10px] text-gray-500 uppercase tracking-[0.25em] font-mono">Conventions</span>
												<div class="flex-1 h-px bg-white/[0.06]"></div>
											</div>
											<ConventionRules rules={summary.conventions.rules} />
										</section>
									{/if}

									<!-- Impression -->
									{#if summary.impression}
										<section>
											<div class="flex items-center gap-2 mb-3">
												<span class="text-[10px] text-gray-500 uppercase tracking-[0.25em] font-mono">Impression</span>
												<div class="flex-1 h-px bg-white/[0.06]"></div>
											</div>
											<ImpressionFlow flow={summary.impression.flow || []} detail={summary.impression.detail || ''} />
										</section>
									{/if}
								</div>
							{:else}
								<p class="text-sm text-gray-600">No summary available.</p>
							{/if}
						</div>
						<div class="flex justify-end px-5 py-3 border-t border-white/[0.06] shrink-0">
							<button class="btn-primary flex items-center gap-2" on:click={nextStage}>
								Continue
								<span class="text-white/60">&rarr;</span>
							</button>
						</div>
					</div>

				<!-- STAGE: Questions -->
				{:else if stage === 'questions'}
					<div class="flex-1 flex flex-col min-h-0" in:fly={{ x: 20, duration: 200 }}>
						<p class="text-sm text-gray-400 px-5 pt-4 pb-2 shrink-0">{stageDescriptions.questions}</p>
						<div class="flex-1 overflow-y-auto px-5 pb-4 space-y-3">

							{#each questions as q, qIdx}
								{#if q.status === 'answered'}
									<!-- Answered: collapsed -->
									<div class="flex items-start gap-2 text-xs py-1.5 px-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
										<svg class="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
										<span class="text-gray-500 flex-1">{q.question}</span>
										<span class="text-emerald-400 shrink-0 font-medium">{q.answer}</span>
									</div>
								{:else if q.status === 'skipped'}
									<!-- Skipped: collapsed, click to re-engage -->
									<button
										type="button"
										class="w-full flex items-center gap-2 text-xs py-1.5 px-3 rounded-lg bg-white/[0.02] hover:bg-amber-500/[0.06] border border-transparent hover:border-amber-500/20 transition-colors duration-150 group"
										on:click={() => unskipQuestion(qIdx)}
										title="Click to answer this question"
									>
										<span class="text-amber-600/50 group-hover:text-amber-400">—</span>
										<span class="text-amber-600/50 group-hover:text-amber-300 flex-1 truncate text-left">{q.question}</span>
										<span class="text-amber-600/50 group-hover:text-amber-400 shrink-0">skipped · answer</span>
									</button>
								{:else}
									<!-- Pending: full card -->
									<div class="card-dark space-y-3">
										<p class="text-sm text-gray-200 leading-relaxed">{q.question}</p>
										<div class="flex flex-wrap gap-1.5">
											{#each q.suggestions as suggestion}
												<button
													class="text-xs bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 hover:text-purple-200 border border-purple-500/15 hover:border-purple-500/30 rounded-full px-3 py-1.5 transition-all duration-200"
													on:click={() => clickSuggestion(qIdx, suggestion)}
												>{suggestion}</button>
											{/each}
											<button
												class="text-xs text-gray-500 hover:text-gray-300 border border-white/10 border-dashed rounded-full px-3 py-1.5 transition-colors duration-200"
												on:click={() => openCustomAnswer(qIdx)}
											>Other...</button>
											<button
												class="text-xs text-gray-600 hover:text-gray-400 ml-1 transition-colors duration-200"
												on:click={() => skipQuestion(qIdx)}
											>Skip</button>
										</div>
									</div>
								{/if}
							{/each}

							{#if loading}
								<div class="text-sm text-gray-500 flex items-center gap-2">
									<span class="inline-block w-3 h-3 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
									Updating...
								</div>
							{/if}
						</div>

						<!-- Custom answer input (when active) -->
						{#if activeQuestionIdx >= 0 && questions[activeQuestionIdx]}
							<div class="px-5 py-3 border-t border-white/[0.06] shrink-0">
								<p class="text-xs text-gray-500 mb-2 truncate">Re: {questions[activeQuestionIdx].question}</p>
								<div class="flex gap-2">
									<input class="input-dark !py-2 !text-sm" bind:value={chatInput} on:keydown={handleChatKey} placeholder="Your answer..." disabled={loading} />
									<button class="btn-accent !px-3.5 !py-2" on:click={() => sendAnswer(chatInput)} disabled={loading || !chatInput.trim()}>&uarr;</button>
								</div>
								<button class="text-xs text-gray-600 hover:text-gray-400 mt-1 transition-colors" on:click={() => { activeQuestionIdx = -1; }}>Cancel</button>
							</div>
						{/if}

						<!-- Bottom: skip all or continue -->
						<div class="px-5 py-3 border-t border-white/[0.06] shrink-0 flex items-center justify-between">
							{#if pendingCount > 0}
								<button class="text-sm text-gray-500 hover:text-gray-300 transition-colors" on:click={skipAllQuestions}>Skip remaining</button>
							{:else}
								<span class="text-xs text-gray-600">All questions resolved</span>
							{/if}
							{#if allQuestionsResolved}
								<button class="btn-primary flex items-center gap-2" on:click={() => goToStage('test')}>
									Test your template <span class="text-white/60">&rarr;</span>
								</button>
							{/if}
						</div>
					</div>

				<!-- STAGE: Test -->
				{:else if stage === 'test'}
					<div class="flex-1 flex flex-col px-5 py-5 space-y-4" in:fly={{ x: 20, duration: 200 }}>
						<p class="text-sm text-gray-400 shrink-0">{stageDescriptions.test}</p>
						<div class="flex-1 overflow-y-auto space-y-4">
							<div>
								<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Clinical history</label>
								<textarea
									class="input-dark !text-sm resize-none"
									rows="3"
									bind:value={testClinicalHistory}
									placeholder="e.g. 68F progressive knee pain, awaiting surgical review"
								></textarea>
							</div>
							<div>
								<label class="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Findings</label>
								<textarea
									class="input-dark !text-sm resize-y"
									rows="12"
									bind:value={testFindings}
									placeholder="Raw scratchpad findings..."
								></textarea>
							</div>
						</div>
						<div class="flex justify-end shrink-0">
							<button
								class="btn-primary flex items-center gap-2"
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
						</div>
					</div>

				<!-- STAGE: Refine -->
				{:else if stage === 'refine'}
					<div class="flex-1 flex flex-col min-h-0" in:fly={{ x: 20, duration: 200 }}>
						<p class="text-sm text-gray-400 px-5 pt-4 pb-2 shrink-0">{stageDescriptions.refine}</p>
						<div class="flex-1 overflow-y-auto px-5 pb-4 space-y-3">

							<!-- Answered questions (compact) -->
							{#if questions.some(q => q.status === 'answered')}
								<div class="space-y-1.5 pb-3 mb-3 border-b border-white/[0.06]">
									{#each questions.filter(q => q.status === 'answered') as aq}
										<div class="flex items-start gap-2 text-xs">
											<svg class="w-3 h-3 text-emerald-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
											<span class="text-gray-500 truncate flex-1">{aq.question}</span>
											<span class="text-gray-300 shrink-0">{aq.answer}</span>
										</div>
									{/each}
								</div>
							{/if}

							{#each chatHistory as msg}
								{#if msg.role === 'user'}
									<div class="flex justify-end">
										<div class="max-w-[90%] bg-purple-600/20 border border-purple-500/15 rounded-2xl rounded-br-sm px-4 py-2.5 text-sm text-gray-200" style="white-space: pre-wrap;">{msg.content}</div>
									</div>
								{:else}
									<div class="max-w-[90%] bg-white/[0.03] border border-white/10 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-300 leading-relaxed" style="white-space: pre-wrap;">{msg.content}</div>
								{/if}
							{/each}

							{#if loading}
								<div class="text-sm text-gray-500 flex items-center gap-2">
									<span class="inline-block w-3 h-3 border-2 border-gray-600 border-t-gray-400 rounded-full animate-spin"></span>
									Updating...
								</div>
							{/if}

						</div>

						<!-- Chat input + regenerate -->
						<div class="px-5 py-3 border-t border-white/[0.06] shrink-0 space-y-2">
							<div class="flex gap-2">
								<input class="input-dark !py-2 !text-sm" bind:value={chatInput} on:keydown={handleChatKey} placeholder="Add a rule or correction..." disabled={loading} />
								<button class="btn-accent !px-3.5 !py-2" on:click={() => sendAnswer(chatInput)} disabled={loading || !chatInput.trim()}>&uarr;</button>
							</div>
							{#if hasGenerated}
								<button
									class="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-purple-300 hover:text-purple-200 bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/15 hover:border-purple-500/30 transition-all duration-200"
									on:click={runTestGenerate}
									disabled={loadingTest}
								>
									{#if loadingTest}
										<span class="inline-block w-3 h-3 border-2 border-purple-400/30 border-t-purple-400 rounded-full animate-spin"></span>
										Regenerating...
									{:else}
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
										Regenerate
									{/if}
								</button>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>

		<!-- RIGHT PANEL: Report output (constant) -->
		<div style="flex: 1; min-width: 0;" class="flex flex-col bg-white/[0.02]">

			<!-- Header -->
			<div class="flex items-center justify-between px-6 py-3 border-b border-white/[0.06] shrink-0">
				<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Report preview</span>
				{#if testReport}
					<div class="flex items-center gap-2">
						<!-- Compare with previous -->
						{#if prevReport && prevReport !== testReport}
							<button
								class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-all duration-200
									{compareMode ? 'text-purple-200 bg-purple-500/20 border border-purple-500/30' : 'text-purple-300 hover:text-purple-200 bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/15 hover:border-purple-500/30'}"
								on:click={toggleCompareMode}
								title={compareMode ? 'Exit compare mode (Esc)' : 'Compare with previous version'}
							>
								<svg class="w-3.5 h-3.5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>
								{compareMode ? 'Exit compare' : 'Compare'}
							</button>
						{/if}
						<!-- Copy -->
						<button
							class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-all duration-200
								{copyConfirm ? 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/20' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}"
							on:click={copyReportWithConfirm}
						>
							{#if copyConfirm}
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
								Copied
							{:else}
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
								Copy
							{/if}
						</button>
						<!-- Edit test case -->
						<button
							class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-all duration-200"
							on:click={() => goToStage('test')}
						>
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
							Edit case
						</button>
					</div>
				{/if}
			</div>

			<!-- Report -->
			<div class="flex-1 overflow-hidden min-h-0">
				{#if testReport}
					{#if compareMode && prevReport}
						<div class="h-full flex flex-col">
							<!-- Flip toggle bar -->
							<div class="flex items-center justify-between gap-3 px-5 py-2.5 border-b border-white/[0.06] shrink-0 bg-black/20">
								<div class="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-white/[0.04] border border-white/[0.08]">
									<button
										type="button"
										class="px-3 py-1 text-xs font-medium rounded-md transition-all duration-150
											{compareView === 'previous' ? 'bg-white/10 text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-300'}"
										on:click={() => flipCompare('previous')}
									>
										Previous
									</button>
									<button
										type="button"
										class="px-3 py-1 text-xs font-medium rounded-md transition-all duration-150
											{compareView === 'current' ? 'bg-purple-500/25 text-purple-100 shadow-sm' : 'text-gray-500 hover:text-gray-300'}"
										on:click={() => flipCompare('current')}
									>
										Current
									</button>
								</div>
								<span class="text-[10px] text-gray-600 hidden sm:flex items-center gap-1.5">
									<kbd class="px-1.5 py-0.5 rounded bg-white/[0.06] border border-white/[0.08] font-mono text-[10px]">space</kbd>
									flip
									<span class="text-gray-700 mx-1">·</span>
									<kbd class="px-1.5 py-0.5 rounded bg-white/[0.06] border border-white/[0.08] font-mono text-[10px]">esc</kbd>
									exit
								</span>
							</div>
							<!-- Single rendered report (flippable) -->
							<div class="flex-1 overflow-y-auto px-6 py-5" bind:this={reportScrollEl}>
								<div class="prose prose-invert prose-sm max-w-2xl mx-auto">
									{@html renderMarkdown(compareView === 'previous' ? prevReport : testReport)}
								</div>
							</div>
						</div>
					{:else}
						<div class="h-full overflow-y-auto px-6 py-5">
							<div class="prose prose-invert prose-sm max-w-2xl mx-auto">
								{@html renderMarkdown(testReport)}
							</div>
							<!-- Refinement hint -->
							<div class="mt-6 pt-4 border-t border-white/[0.06] flex items-start gap-3 max-w-2xl mx-auto">
								<svg class="w-4 h-4 text-purple-400/60 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
								<p class="text-xs text-gray-600 leading-relaxed">
									Not quite right? Use the <button class="text-purple-400 hover:text-purple-300" on:click={() => goToStage('refine')}>Refine</button> tab to add corrections — describe what should change and your style guide updates automatically. Then regenerate to see the effect.
								</p>
							</div>
						</div>
					{/if}
				{:else if loadingTest}
					<div class="flex items-center justify-center h-full">
						<div class="flex flex-col items-center gap-3">
							<span class="inline-block w-6 h-6 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin"></span>
							<span class="text-sm text-gray-500">Generating report...</span>
						</div>
					</div>
				{:else}
					<div class="flex items-center justify-center h-full px-6">
						<div class="flex flex-col items-center gap-5">
							<div class="page-outline" aria-hidden="true">
								<div class="page-line page-line-heading"></div>
								<div class="page-line page-line-subheading"></div>
								<div class="page-line"></div>
								<div class="page-line page-line-short"></div>
								<div class="page-line"></div>
								<div class="page-line page-line-medium"></div>
								<div class="page-line page-line-short"></div>
							</div>
							<div class="text-center">
								<p class="text-sm text-gray-500">Report will appear here</p>
								<p class="text-xs text-gray-500 mt-1">Complete the steps on the left, then generate</p>
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Bottom bar -->
			<div class="px-6 py-3 border-t border-white/[0.06] shrink-0">
				{#if saved}
					<div class="flex items-center justify-between">
						<p class="text-sm text-emerald-400">Template saved.</p>
						<button class="btn-ghost text-sm" on:click={handleClose}>Done</button>
					</div>
				{:else if !hasGenerated}
					<p class="text-xs text-gray-600">Generate a test report before saving.</p>
				{:else if !showSaveDialog}
					<div class="flex items-center justify-between">
						<p class="text-xs text-gray-500">Refine on the left, regenerate to check.</p>
						<button class="btn-primary" on:click={openSaveDialog}>Save as template</button>
					</div>
				{:else}
					<div class="space-y-2.5">
						<input
							class="input-dark !py-2 w-full"
							bind:value={templateName}
							placeholder="Template name — e.g. CT Chest — Dr Smith"
						/>
						<div class="relative">
							<div class="flex flex-wrap items-center gap-1.5 px-2 py-1.5 bg-black/30 border border-white/10 rounded-lg">
								{#each tags as tag}
									<span
										class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs"
										style="background-color: {getTagColor(tag, {})}; color: white;"
									>
										{tag}
										<button
											type="button"
											class="hover:bg-white/20 rounded-full p-0.5 transition-colors"
											aria-label="Remove tag"
											on:click={() => removeTag(tag)}
										>
											<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" /></svg>
										</button>
									</span>
								{/each}
								<input
									type="text"
									bind:value={newTag}
									on:keydown={handleTagKeydown}
									placeholder={tags.length === 0 ? 'Add tags — Enter to confirm' : ''}
									class="flex-1 min-w-[8rem] bg-transparent border-0 outline-none ring-0 focus:outline-none focus:ring-0 focus:border-0 text-sm text-white placeholder-gray-600 py-0.5"
								style="box-shadow: none;"
								/>
							</div>
							{#if tagSuggestions.length > 0}
								<div class="absolute z-20 left-0 right-0 mt-1 bg-gray-900 border border-white/10 rounded-lg shadow-2xl overflow-hidden">
									{#each tagSuggestions as suggestion}
										<button
											type="button"
											class="w-full text-left px-3 py-1.5 hover:bg-white/5 text-sm text-white transition-colors"
											on:mousedown|preventDefault={() => addTag(suggestion)}
										>
											{suggestion}
										</button>
									{/each}
								</div>
							{/if}
						</div>
						<div class="flex items-center justify-end gap-2 pt-0.5">
							<button class="btn-ghost text-xs" on:click={() => (showSaveDialog = false)}>Cancel</button>
							<button class="btn-primary !px-5 flex items-center gap-2" on:click={saveAsTemplate} disabled={saving || !templateName.trim()}>
								{#if saving}<span class="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>{/if}
								Save
							</button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

{#if error}
	<div class="fixed bottom-4 right-4 card-dark !bg-red-900 !border-red-500 px-5 py-3 text-red-200 text-sm shadow-xl z-50 max-w-lg backdrop-blur-xl">
		{error}
		<button class="ml-3 text-red-400 hover:text-red-200 transition-colors" on:click={() => (error = '')}>dismiss</button>
	</div>
{/if}
