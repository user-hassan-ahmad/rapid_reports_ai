<script lang="ts">
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import { createEventDispatcher, onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { logger } from '$lib/utils/logger';
	import DiffMatchPatch from 'diff-match-patch';

	export let open = false;
	export let reportId: string | null = null;
	export let reportContent: string = '';

	const dispatch = createEventDispatcher();

	let katex: any = null;
	let katexLoaded = false;

	onMount(async () => {
		try {
			katex = (await import('katex')).default;
			await import('katex/dist/katex.css');
			katexLoaded = true;
		} catch {
			console.warn('KaTeX not available - math formulas will render as plain text');
		}
		try {
			const raw = localStorage.getItem('intervalDrawerHeight');
			if (raw) {
				const n = parseFloat(raw);
				if (!Number.isNaN(n)) drawerHeight = Math.min(95, Math.max(30, n));
			}
		} catch {
			/* ignore */
		}
	});

	marked.setOptions({ breaks: true, gfm: true });

	let priorReports: any[] = [];
	let showAddPriorModal = false;
	let editingPriorIndex: number | null = null;
	let newPrior = { text: '', date: '', scan_type: '' };
	let studyDateInput: HTMLInputElement;
	let comparing = false;
	let comparisonResult: any = null;
	let applyRevisedReportLoading = false;
	let showRevisedReportPreview = false;
	let revisedReportApplied = false;
	let previewMode: 'revised' | 'diff' = 'diff';
	let cachedDiffHtml = '';

	function computeDiffHtml(original: string, revised: string): string {
		try {
			const dmp = new DiffMatchPatch();
			const diffs = dmp.diff_main(original, revised);
			dmp.diff_cleanupSemantic(diffs);
			return diffs.map(([op, text]: [number, string]) => {
				const escaped = text
					.replace(/&/g, '&amp;')
					.replace(/</g, '&lt;')
					.replace(/>/g, '&gt;')
					.replace(/\n/g, '<br>');
				if (op === 1)  return `<ins class="diff-ins">${escaped}</ins>`;
				if (op === -1) return `<del class="diff-del">${escaped}</del>`;
				return `<span class="diff-eq">${escaped}</span>`;
			}).join('');
		} catch {
			return `<span class="diff-eq">${revised.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')}</span>`;
		}
	}

	function openPreviewModal() {
		cachedDiffHtml = computeDiffHtml(reportContent, comparisonResult?.revised_report ?? '');
		previewMode = 'diff';
		showRevisedReportPreview = true;
	}

	let drawerHeight = 65;
	let heightDragging = false;
	let dragStartY = 0;
	let dragStartHeight = 65;

	function formatDateUK(dateStr: string): string {
		if (!dateStr) return '';
		try {
			const [year, month, day] = dateStr.split('-');
			return `${day}/${month}/${year}`;
		} catch {
			return dateStr;
		}
	}

	function renderMarkdown(md: string) {
		if (!md) return '';
		let processed = md.replace(/\\n/g, '\n');
		processed = processed.replace(/\.\s*•\s*/g, '.\n- ');
		processed = processed.replace(/(^|[\n\r])•\s*/g, '$1- ');
		processed = processed.replace(/([.!?])\s+•\s+/g, '$1\n- ');
		processed = processed.replace(/\s+•\s+/g, '\n- ');
		processed = processed.replace(/^[\s]*-[\s]+-[\s]+/gm, '- ');
		processed = processed.replace(/^[\s]{2,}-[\s]+/gm, '- ');
		let html = marked.parse(processed) as string;
		if (katexLoaded && katex) {
			html = html.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
				try {
					const rendered = katex.renderToString(formula.trim(), { displayMode: true, throwOnError: false });
					return `<div class="katex-block-container" style="overflow-x: auto; overflow-y: hidden; max-width: 100%; margin: 1rem 0;">${rendered}</div>`;
				} catch {
					return match;
				}
			});
			html = html.replace(/\$([^$\n]+?)\$/g, (match, formula) => {
				try {
					const rendered = katex.renderToString(formula.trim(), { displayMode: false, throwOnError: false });
					return `<span class="katex-inline-container" style="display: inline-block; max-width: 100%; overflow-x: auto; word-break: break-word;">${rendered}</span>`;
				} catch {
					return match;
				}
			});
		}
		return html;
	}

	async function addPriorReport() {
		if (!newPrior.text.trim() || !newPrior.date || !newPrior.scan_type.trim()) return;
		if (editingPriorIndex !== null) {
			priorReports[editingPriorIndex] = {
				text: newPrior.text,
				date: newPrior.date,
				scan_type: newPrior.scan_type.trim()
			};
			editingPriorIndex = null;
		} else {
			priorReports = [
				...priorReports,
				{
					text: newPrior.text,
					date: newPrior.date,
					scan_type: newPrior.scan_type.trim()
				}
			];
		}
		newPrior = { text: '', date: '', scan_type: '' };
		showAddPriorModal = false;
	}

	function editPriorReport(index: number) {
		const prior = priorReports[index];
		newPrior = {
			text: prior.text,
			date: prior.date,
			scan_type: prior.scan_type || ''
		};
		editingPriorIndex = index;
		showAddPriorModal = true;
	}

	function removePriorReport(index: number) {
		priorReports = priorReports.filter((_, i) => i !== index);
		if (editingPriorIndex === index) {
			editingPriorIndex = null;
			showAddPriorModal = false;
		} else if (editingPriorIndex !== null && editingPriorIndex > index) {
			editingPriorIndex--;
		}
	}

	function cancelEdit() {
		newPrior = { text: '', date: '', scan_type: '' };
		editingPriorIndex = null;
		showAddPriorModal = false;
	}

	async function runComparison() {
		if (!reportId || priorReports.length === 0) return;
		comparing = true;
		try {
			const response = await fetch(`${API_URL}/api/reports/${reportId}/compare`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${$token}`
				},
				body: JSON.stringify({ prior_reports: priorReports })
			});
			if (!response.ok) {
				logger.error('runComparison: HTTP', await response.text());
				return;
			}
			const data = await response.json();
			if (data.success && data.comparison) {
				comparisonResult = data.comparison;
			} else {
				logger.error('runComparison: API error', data.error);
			}
		} catch (err) {
			logger.error('runComparison:', err);
		} finally {
			comparing = false;
		}
	}

	async function applyRevisedReport() {
		if (!comparisonResult?.revised_report || applyRevisedReportLoading || revisedReportApplied) return;
		applyRevisedReportLoading = true;
		dispatch('reportUpdating', { status: 'start' });
		try {
			const response = await fetch(`${API_URL}/api/reports/${reportId}/apply-comparison`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${$token}`
				},
				body: JSON.stringify({ revised_report: comparisonResult.revised_report })
			});
			const data = await response.json();
			if (data.success) {
				revisedReportApplied = true;
				dispatch('reportUpdated', { report: { report_content: data.updated_content } });
			}
		} catch (err) {
			logger.error('Apply failed:', err);
		} finally {
			applyRevisedReportLoading = false;
			dispatch('reportUpdating', { status: 'end' });
		}
	}

	function clearComparison() {
		comparisonResult = null;
		priorReports = [];
		newPrior = { text: '', date: '', scan_type: '' };
		applyRevisedReportLoading = false;
		revisedReportApplied = false;
		showRevisedReportPreview = false;
	}

	function startHeightDrag(e: PointerEvent) {
		heightDragging = true;
		dragStartY = e.clientY;
		dragStartHeight = drawerHeight;
		window.addEventListener('pointermove', onHeightDrag);
		window.addEventListener('pointerup', stopHeightDrag);
		document.body.style.cursor = 'row-resize';
		document.body.style.userSelect = 'none';
	}

	function onHeightDrag(e: PointerEvent) {
		if (!heightDragging) return;
		const vh = window.innerHeight / 100;
		const deltaVh = (dragStartY - e.clientY) / vh;
		drawerHeight = Math.min(95, Math.max(30, dragStartHeight + deltaVh));
	}

	function stopHeightDrag() {
		heightDragging = false;
		window.removeEventListener('pointermove', onHeightDrag);
		window.removeEventListener('pointerup', stopHeightDrag);
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		try {
			localStorage.setItem('intervalDrawerHeight', String(drawerHeight));
		} catch {
			/* ignore */
		}
	}

	$: if (!open) {
		showAddPriorModal = false;
	}

	let lastDrawerReportId: string | null = null;
	$: if (reportId !== lastDrawerReportId) {
		lastDrawerReportId = reportId;
		clearComparison();
	}
</script>

{#if open}
	<!-- Backdrop -->
	<button
		type="button"
		class="fixed inset-0 bg-black/40 z-[10400] cursor-default border-0 p-0 w-full h-full"
		onclick={() => dispatch('close')}
		aria-label="Close interval analysis"
	></button>

	<!-- Drawer shell -->
	<div
		class="fixed inset-x-0 bottom-0 z-[10500] flex flex-col bg-[#070710]/97 backdrop-blur-2xl border-t border-white/10 rounded-t-2xl shadow-2xl shadow-purple-500/20 transition-transform duration-300 ease-out"
		style="height: {drawerHeight}vh; max-height: 95vh;"
	>
		<!-- Drag handle -->
		<div
			class="flex justify-center pt-2.5 pb-2 shrink-0 cursor-row-resize group"
			onpointerdown={startHeightDrag}
			role="separator"
			aria-orientation="horizontal"
		>
			<div class="w-9 h-1 rounded-full bg-white/15 group-hover:bg-white/30 transition-colors"></div>
		</div>

		<!-- Header -->
		<div class="flex items-center gap-3 px-4 pb-3 shrink-0 border-b border-white/8 flex-wrap">
			<!-- Title -->
			<div class="flex items-center gap-2 text-sm font-semibold text-white">
				<svg class="w-4 h-4 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
				</svg>
				Interval Analysis
			</div>

			<!-- Stat pills — only shown when results are loaded -->
			{#if comparisonResult}
				{@const newCount    = comparisonResult.findings.filter((f: any) => f.status === 'new').length}
				{@const changedCount= comparisonResult.findings.filter((f: any) => f.status === 'changed').length}
				{@const stableCount = comparisonResult.findings.filter((f: any) => f.status === 'stable').length}
				<div class="flex gap-1.5 items-center flex-wrap">
					{#if newCount > 0}
						<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-red-500/12 border border-red-500/25 text-red-400">
							<span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>{newCount} New
						</span>
					{/if}
					{#if changedCount > 0}
						<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-orange-500/10 border border-orange-500/25 text-orange-400">
							<span class="w-1.5 h-1.5 rounded-full bg-orange-400"></span>{changedCount} Changed
						</span>
					{/if}
					{#if stableCount > 0}
						<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-green-500/8 border border-green-500/20 text-green-400">
							<span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>{stableCount} Stable
						</span>
					{/if}
				</div>
			{/if}

			<div class="flex-1"></div>

			<!-- Close -->
			<button
				type="button"
				class="p-1.5 text-gray-500 hover:text-white hover:bg-white/6 rounded-lg transition-colors"
				onclick={() => dispatch('close')}
				aria-label="Close"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<!-- Summary banner — shown when results loaded -->
		{#if comparisonResult?.summary}
			<div class="mx-4 mt-3 mb-0 px-3 py-2.5 bg-blue-500/8 border border-blue-500/20 rounded-xl text-blue-300 text-[12.5px] leading-relaxed flex gap-2 items-start shrink-0">
				<svg class="w-3.5 h-3.5 mt-0.5 shrink-0 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<circle cx="12" cy="12" r="10" stroke-width="2"/>
					<path stroke-linecap="round" stroke-width="2" d="M12 16v-4M12 8h.01"/>
				</svg>
				<span>{comparisonResult.summary}</span>
			</div>
		{/if}

		<!-- Body -->
		<div class="flex flex-1 min-h-0 gap-0">

			<!-- ── Left: Prior studies ── -->
			<div class="w-52 shrink-0 border-r border-white/8 overflow-y-auto p-3 flex flex-col gap-2">
				<p class="text-[10px] font-bold tracking-widest uppercase text-gray-500 px-1">Prior Studies</p>

				{#if priorReports.length === 0}
					<p class="text-[11.5px] text-gray-600 px-1 leading-relaxed">Add prior reports to compare against this study.</p>
				{:else}
					{#each priorReports as prior, idx}
						<div class="prior-study-card group bg-white/[0.03] border border-white/8 rounded-xl p-2.5 flex flex-col gap-1 cursor-default">
							<div class="text-[12px] font-semibold text-gray-200">{formatDateUK(prior.date)}</div>
							<div class="text-[10.5px] text-gray-500 leading-snug line-clamp-2">{prior.scan_type}</div>
							<div class="flex gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
								<button
									type="button"
									class="text-[10px] font-medium px-2 py-0.5 rounded-md bg-blue-500/12 text-blue-400 hover:bg-blue-500/20 transition-colors"
									onclick={() => editPriorReport(idx)}
								>Edit</button>
								<button
									type="button"
									class="text-[10px] font-medium px-2 py-0.5 rounded-md bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
									onclick={() => removePriorReport(idx)}
								>Remove</button>
							</div>
						</div>
					{/each}
				{/if}

				<button
					type="button"
					class="flex items-center justify-center gap-1.5 py-2 border border-dashed border-white/12 rounded-xl text-[11.5px] text-gray-500 hover:text-purple-400 hover:border-purple-500/40 hover:bg-purple-500/5 transition-all"
					onclick={() => (showAddPriorModal = true)}
				>
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 5v14M5 12h14" /></svg>
					Add prior report
				</button>

				{#if comparisonResult}
					<div class="h-px bg-white/8 my-1"></div>
					<p class="text-[10px] font-bold tracking-widest uppercase text-gray-500 px-1">Re-analyse</p>
					<button
						type="button"
						class="flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium bg-white/[0.04] border border-white/10 rounded-xl text-gray-400 hover:bg-white/8 hover:text-gray-200 transition-all"
						onclick={runComparison}
						disabled={comparing || !reportId}
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polyline stroke-linecap="round" stroke-linejoin="round" stroke-width="2" points="23 4 23 10 17 10"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
						Re-run Analysis
					</button>
				{/if}
			</div>

			<!-- ── Right: Results ── -->
			<div class="flex-1 min-w-0 overflow-y-auto p-4 flex flex-col gap-5">

				{#if !comparisonResult && !comparing && priorReports.length === 0}
					<!-- Empty state: no prior reports yet -->
					<div class="flex-1 flex items-center justify-center">
						<div class="text-center max-w-xs">
							<div class="w-12 h-12 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center mx-auto mb-4">
								<svg class="w-6 h-6 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
								</svg>
							</div>
							<h3 class="text-sm font-semibold text-white mb-2">Compare with Prior Studies</h3>
							<p class="text-[12px] text-gray-500 leading-relaxed mb-5">Add one or more prior radiology reports on the left, then run interval analysis to see structured findings and suggested report modifications.</p>
							<button
								type="button"
								class="btn-primary-subtle inline-flex items-center gap-2 text-sm px-4 py-2"
								onclick={() => (showAddPriorModal = true)}
							>
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M12 5v14M5 12h14" /></svg>
								Add First Prior Report
							</button>
						</div>
					</div>

				{:else if !comparisonResult && !comparing && priorReports.length > 0}
					<!-- Ready state: prior reports added, waiting to run -->
					<div class="flex-1 flex items-center justify-center">
						<div class="text-center max-w-sm">
							<div class="w-12 h-12 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center mx-auto mb-4">
								<svg class="w-6 h-6 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
								</svg>
							</div>
							<h3 class="text-sm font-semibold text-white mb-2">
								{priorReports.length === 1 ? '1 prior study ready' : `${priorReports.length} prior studies ready`}
							</h3>
							<p class="text-[12px] text-gray-500 leading-relaxed mb-5">
								Run interval analysis to compare this report against {priorReports.length === 1 ? 'your prior study' : 'your prior studies'} and get structured findings.
							</p>
							<button
								type="button"
								class="btn-primary-subtle inline-flex items-center gap-2 text-sm px-5 py-2"
								onclick={runComparison}
								disabled={!reportId}
							>
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
								Analyse Interval Changes
							</button>
						</div>
					</div>

				{:else if comparing}
					<div class="flex-1 flex items-center justify-center">
						<div class="text-center">
							<div class="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
							<p class="text-sm text-gray-400">Analysing interval changes…</p>
							<p class="text-xs text-gray-600 mt-1">Comparing with {priorReports.length} prior {priorReports.length === 1 ? 'study' : 'studies'}</p>
						</div>
					</div>

				{:else}
					{@const changedFindings = comparisonResult.findings.filter((f: any) => f.status === 'changed')}
					{@const newFindings     = comparisonResult.findings.filter((f: any) => f.status === 'new')}
					{@const stableFindings  = comparisonResult.findings.filter((f: any) => f.status === 'stable')}

					<!-- 3-column findings grid -->
					<div class="grid grid-cols-3 gap-3">

						<!-- NEW FINDINGS -->
						<div class="flex flex-col gap-2">
							<div class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[10.5px] font-bold tracking-wide uppercase bg-red-500/8 border border-red-500/20 text-red-400">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2.5"/><path stroke-linecap="round" stroke-width="2.5" d="M12 8v4M12 16h.01"/></svg>
								New Findings
								<span class="ml-auto w-4.5 h-4.5 flex items-center justify-center rounded-full bg-red-500/25 text-[9px] font-bold">{newFindings.length}</span>
							</div>

							{#if newFindings.length === 0}
								<p class="text-[11px] text-gray-600 px-1">No new findings.</p>
							{:else}
								{@const hasUrgent = newFindings.some((f: any) =>
									f.assessment?.toLowerCase().includes('urgent') ||
									f.assessment?.toLowerCase().includes('immediate') ||
									f.assessment?.toLowerCase().includes('concerning')
								)}
								{#if hasUrgent}
									<div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-600/15 border border-red-600/30 text-red-300 text-[10px] font-bold tracking-wide uppercase animate-pulse">
										<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L1 21h22L12 2zm0 3.5L20.5 19h-17L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/></svg>
										Urgent review required
									</div>
								{/if}
								{#each newFindings as finding}
									<div class="finding-card finding-card--new">
										<div class="text-[12px] font-semibold text-gray-100 leading-snug mb-1">{finding.name}</div>
										{#if finding.location}
											<div class="mb-1.5"><span class="location-chip">{finding.location}</span></div>
										{/if}
										{#if finding.current_measurement}
											<div class="flex items-center gap-1.5 mb-1.5">
												<span class="meas-pill meas-pill--new">{finding.current_measurement.raw_text}</span>
												{#if finding.assessment?.toLowerCase().includes('urgent') || finding.assessment?.toLowerCase().includes('immediate')}
													<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-red-600/30 text-red-200 text-[9px] font-bold uppercase tracking-wide animate-pulse">Urgent</span>
												{/if}
											</div>
										{/if}
										<p class="text-[11px] text-gray-400 leading-relaxed">{finding.assessment}</p>
									</div>
								{/each}
							{/if}
						</div>

						<!-- INTERVAL CHANGES -->
						<div class="flex flex-col gap-2">
							<div class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[10.5px] font-bold tracking-wide uppercase bg-orange-500/8 border border-orange-500/20 text-orange-400">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polyline stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" points="23 4 23 10 17 10"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
								Interval Changes
								<span class="ml-auto w-4.5 h-4.5 flex items-center justify-center rounded-full bg-orange-500/25 text-[9px] font-bold">{changedFindings.length}</span>
							</div>

							{#if changedFindings.length === 0}
								<p class="text-[11px] text-gray-600 px-1">No interval changes.</p>
							{:else}
								{#each changedFindings as finding}
									<div class="finding-card finding-card--changed">
										<div class="text-[12px] font-semibold text-gray-100 leading-snug mb-1">{finding.name}</div>
										{#if finding.location}
											<div class="mb-1.5"><span class="location-chip">{finding.location}</span></div>
										{/if}
										{#if finding.prior_measurement || finding.current_measurement}
											<div class="flex items-center gap-1.5 mb-1.5 flex-wrap">
												{#if finding.prior_measurement}
													<span class="meas-pill meas-pill--prior">{finding.prior_measurement.raw_text}</span>
												{/if}
												{#if finding.prior_measurement && finding.current_measurement}
													<svg class="w-3 h-3 text-orange-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 12h14m-7-7l7 7-7 7"/></svg>
												{/if}
												{#if finding.current_measurement}
													<span class="meas-pill meas-pill--current">{finding.current_measurement.raw_text}</span>
												{/if}
											</div>
										{/if}
										{#if finding.trend}
											<div class="flex items-center gap-1 text-[10.5px] text-gray-500 italic mb-1.5">
												{#if finding.trend.toLowerCase().includes('increas') || finding.trend.toLowerCase().includes('progress') || finding.trend.toLowerCase().includes('enlarg')}
													<span class="text-red-400">↑</span>
												{:else if finding.trend.toLowerCase().includes('decreas') || finding.trend.toLowerCase().includes('resolv') || finding.trend.toLowerCase().includes('reduc')}
													<span class="text-green-400">↓</span>
												{:else}
													<span class="text-gray-500">→</span>
												{/if}
												{finding.trend}
											</div>
										{:else if finding.prior_date}
											<div class="text-[10.5px] text-gray-600 mb-1.5">Prior: {finding.prior_date}</div>
										{/if}
										<p class="text-[11px] text-gray-400 leading-relaxed">{finding.assessment}</p>
									</div>
								{/each}
							{/if}
						</div>

						<!-- STABLE -->
						<div class="flex flex-col gap-2">
							<div class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[10.5px] font-bold tracking-wide uppercase bg-green-500/6 border border-green-500/18 text-green-400">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20 6L9 17l-5-5"/></svg>
								Stable / Unchanged
								<span class="ml-auto w-4.5 h-4.5 flex items-center justify-center rounded-full bg-green-500/20 text-[9px] font-bold">{stableFindings.length}</span>
							</div>

							{#if stableFindings.length === 0}
								<p class="text-[11px] text-gray-600 px-1">No stable findings recorded.</p>
							{:else}
								{#each stableFindings as finding}
									<div class="stable-item">
										<span class="text-green-400 shrink-0 text-[13px] leading-none">✓</span>
										<span class="text-[11.5px] text-green-100/80">{finding.name}</span>
									</div>
								{/each}
							{/if}
						</div>
					</div>

					<!-- Report Modifications -->
					{#if comparisonResult.key_changes?.length > 0}
						<div>
							<div class="section-divider-label">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
								Report Modifications
							</div>

							<div class="space-y-4">
								{#each comparisonResult.key_changes as change}
									<div>
										{#if change.reason}
											<div class="flex items-center gap-1.5 text-[11px] text-gray-500 font-medium mb-2">
												<svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><path stroke-linecap="round" stroke-width="2" d="M12 16v-4M12 8h.01"/></svg>
												{change.reason}
											</div>
										{/if}
										<div class="grid grid-cols-2 gap-2">
											<div>
												<div class="text-[9.5px] font-bold tracking-widest uppercase text-red-400/70 mb-1.5">Original</div>
												<div class="px-3 py-2.5 rounded-lg bg-red-500/6 border border-red-500/18 text-[11.5px] text-red-300 line-through decoration-red-400/40 leading-relaxed">{change.original}</div>
											</div>
											<div>
												<div class="text-[9.5px] font-bold tracking-widest uppercase text-green-400/70 mb-1.5">Revised</div>
												<div class="px-3 py-2.5 rounded-lg bg-green-500/5 border border-green-500/18 text-[11.5px] text-green-200 leading-relaxed">{change.revised}</div>
											</div>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}

				{/if}
			</div>
		</div>

		<!-- ── Sticky action bar (only when results exist) ── -->
		{#if comparisonResult}
			<div class="shrink-0 border-t border-white/8 px-4 py-2.5 flex items-center gap-2 bg-[#070710]/80 backdrop-blur-sm">
				<div class="flex-1 flex items-center gap-1.5 text-[10.5px] text-gray-600">
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
					Applying creates a new version in report history
				</div>
				<button
					type="button"
					class="action-bar-btn action-bar-btn--danger"
					onclick={clearComparison}
					disabled={applyRevisedReportLoading}
				>
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polyline stroke-linecap="round" stroke-linejoin="round" stroke-width="2" points="23 4 23 10 17 10"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
					Start Over
				</button>
				{#if comparisonResult?.revised_report}
					<button
						type="button"
						class="action-bar-btn"
						onclick={openPreviewModal}
						disabled={applyRevisedReportLoading}
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3" stroke-width="2"/></svg>
						Preview Report
					</button>
					<button
						type="button"
						class="action-bar-btn action-bar-btn--primary"
						onclick={applyRevisedReport}
						disabled={applyRevisedReportLoading || revisedReportApplied}
					>
						{#if applyRevisedReportLoading}
							<svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
							Applying…
						{:else if revisedReportApplied}
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20 6L9 17l-5-5"/></svg>
							Applied
						{:else}
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20 6L9 17l-5-5"/></svg>
							Apply Revised Report
						{/if}
					</button>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<!-- ── Add / Edit Prior Report Modal ── -->
{#if showAddPriorModal}
	<div
		class="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center z-[10600]"
		onclick={cancelEdit}
		role="presentation"
	>
		<div
			class="bg-black/80 backdrop-blur-2xl rounded-2xl border border-white/10 shadow-2xl shadow-purple-500/20 w-[600px] max-h-[80vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
			role="dialog"
		>
			<div class="p-4 border-b border-white/10 flex items-center justify-between">
				<h3 class="text-base font-semibold text-white">
					{editingPriorIndex !== null ? 'Edit Prior Report' : 'Add Prior Report'}
				</h3>
				<button type="button" onclick={cancelEdit} class="text-gray-400 hover:text-white text-xl leading-none">×</button>
			</div>
			<div class="p-4 space-y-4">
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Study Date *</label>
					<div class="relative">
						<input
							type="date"
							bind:value={newPrior.date}
							bind:this={studyDateInput}
							class="input-dark w-full date-input pr-10"
							required
							style="color-scheme: dark;"
						/>
						<button
							type="button"
							onclick={() => { if (studyDateInput?.showPicker) { studyDateInput.showPicker(); } else { studyDateInput?.click(); } }}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-white hover:text-gray-200 transition-colors cursor-pointer z-10"
							aria-label="Open calendar"
							tabindex="-1"
						>
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
							</svg>
						</button>
					</div>
				</div>
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Scan Type *</label>
					<input
						type="text"
						bind:value={newPrior.scan_type}
						placeholder="e.g., CT Abdomen and Pelvis with IV contrast"
						class="input-dark w-full"
						required
					/>
				</div>
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Report Text *</label>
					<textarea bind:value={newPrior.text} placeholder="Paste prior report here…" class="input-dark w-full" rows="12"></textarea>
					<span class="text-xs text-gray-500">{newPrior.text.length} characters</span>
				</div>
			</div>
			<div class="p-4 border-t border-white/10 flex gap-3 justify-end">
				<button type="button" class="btn-secondary" onclick={cancelEdit}>Cancel</button>
				<button
					type="button"
					class="btn-primary"
					onclick={addPriorReport}
					disabled={!newPrior.text.trim() || !newPrior.date || !newPrior.scan_type.trim()}
				>
					{editingPriorIndex !== null ? 'Update Report' : 'Add Report'}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Preview Revised Report Modal ── -->
{#if showRevisedReportPreview && comparisonResult?.revised_report}
	<div
		class="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center z-[10600]"
		onclick={() => (showRevisedReportPreview = false)}
		role="presentation"
	>
		<div
			class="bg-[#0a0a14]/95 backdrop-blur-2xl rounded-2xl border border-white/10 shadow-2xl shadow-purple-500/15 w-[80vw] max-w-3xl max-h-[78vh] overflow-hidden flex flex-col"
			onclick={(e) => e.stopPropagation()}
			role="dialog"
		>
			<!-- Modal header -->
			<div class="px-4 py-3 border-b border-white/8 flex items-center gap-3">
				<div class="flex items-center gap-2 text-sm font-semibold text-white">
					<svg class="w-3.5 h-3.5 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
					Revised Report
				</div>

				<!-- Mode toggle -->
				<div class="flex items-center rounded-lg border border-white/10 bg-white/[0.04] p-0.5 gap-0.5">
					<button
						type="button"
						class="preview-toggle {previewMode === 'diff' ? 'preview-toggle--active' : ''}"
						onclick={() => (previewMode = 'diff')}
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
						Changes
					</button>
					<button
						type="button"
						class="preview-toggle {previewMode === 'revised' ? 'preview-toggle--active' : ''}"
						onclick={() => (previewMode = 'revised')}
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h12"/></svg>
						Full
					</button>
				</div>

				<div class="flex-1"></div>
				<button
					type="button"
					onclick={() => (showRevisedReportPreview = false)}
					class="p-1.5 text-gray-500 hover:text-white hover:bg-white/6 rounded-lg transition-colors"
					aria-label="Close modal"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<!-- Modal body -->
			<div class="flex-1 overflow-y-auto p-4">
				{#if previewMode === 'revised'}
					<div class="text-[12.5px] leading-relaxed text-gray-300 whitespace-pre-wrap font-mono">
						{comparisonResult.revised_report}
					</div>
				{:else}
					<!-- Diff legend -->
					<div class="flex items-center gap-4 text-[10.5px] text-gray-500 mb-3">
						<span class="flex items-center gap-1.5">
							<span class="inline-block w-2.5 h-2.5 rounded-sm bg-red-500/30 border border-red-500/40"></span>
							Removed
						</span>
						<span class="flex items-center gap-1.5">
							<span class="inline-block w-2.5 h-2.5 rounded-sm bg-green-500/25 border border-green-500/35"></span>
							Added
						</span>
					</div>
					<div class="diff-output font-mono text-[12.5px] leading-relaxed text-gray-400">
						{@html cachedDiffHtml}
					</div>
				{/if}
			</div>

			<!-- Modal footer -->
			<div class="px-4 py-3 border-t border-white/8 flex gap-2 justify-end">
				<button
					type="button"
					class="action-bar-btn"
					onclick={() => (showRevisedReportPreview = false)}
				>Close</button>
				<button
					type="button"
					onclick={() => { showRevisedReportPreview = false; applyRevisedReport(); }}
					disabled={applyRevisedReportLoading || revisedReportApplied}
					class="action-bar-btn action-bar-btn--primary"
				>
					{#if applyRevisedReportLoading}
						<svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
						Applying…
					{:else if revisedReportApplied}
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20 6L9 17l-5-5"/></svg>
						Applied
					{:else}
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M20 6L9 17l-5-5"/></svg>
						Apply This Report
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
/* ── Finding cards ── */
.finding-card {
	border-radius: 10px;
	padding: 10px 11px 10px 14px;
	border: 1px solid;
	position: relative;
	overflow: hidden;
}
.finding-card::before {
	content: '';
	position: absolute;
	left: 0; top: 0; bottom: 0;
	width: 3px;
	border-radius: 3px 0 0 3px;
}
.finding-card--new {
	background: rgba(248,113,113,0.06);
	border-color: rgba(248,113,113,0.2);
}
.finding-card--new::before  { background: #f87171; }
.finding-card--changed {
	background: rgba(251,146,60,0.06);
	border-color: rgba(251,146,60,0.2);
}
.finding-card--changed::before { background: #fb923c; }

/* ── Location chip ── */
.location-chip {
	display: inline-block;
	font-size: 10px;
	font-weight: 500;
	padding: 2px 7px;
	border-radius: 4px;
	background: rgba(255,255,255,0.07);
	color: #6b7280;
}

/* ── Measurement pills ── */
.meas-pill {
	font-size: 10.5px;
	font-weight: 500;
	padding: 2px 7px;
	border-radius: 5px;
	font-family: ui-monospace, 'JetBrains Mono', monospace;
}
.meas-pill--prior   { background: rgba(255,255,255,0.07); color: #6b7280; text-decoration: line-through; }
.meas-pill--current { background: rgba(251,146,60,0.18);  color: #fed7aa; }
.meas-pill--new     { background: rgba(248,113,113,0.18); color: #fca5a5; }

/* ── Stable finding rows ── */
.stable-item {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 7px 11px 7px 14px;
	background: rgba(74,222,128,0.04);
	border: 1px solid rgba(74,222,128,0.13);
	border-radius: 9px;
	position: relative;
	overflow: hidden;
}
.stable-item::before {
	content: '';
	position: absolute;
	left: 0; top: 0; bottom: 0;
	width: 3px;
	background: #4ade80;
	border-radius: 3px 0 0 3px;
}

/* ── Action bar buttons — consistent height/size across all three ── */
.action-bar-btn {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	padding: 0 12px;
	height: 30px;
	border-radius: 8px;
	font-size: 11.5px;
	font-weight: 500;
	white-space: nowrap;
	cursor: pointer;
	transition: background 0.15s ease, color 0.15s ease;
	/* default: ghost */
	background: rgba(255,255,255,0.05);
	border: 1px solid rgba(255,255,255,0.10);
	color: #d1d5db;
}
.action-bar-btn:hover:not(:disabled) {
	background: rgba(255,255,255,0.09);
	color: #fff;
}
.action-bar-btn:disabled {
	opacity: 0.45;
	cursor: not-allowed;
}
.action-bar-btn--danger {
	background: rgba(248,113,113,0.08);
	border-color: rgba(248,113,113,0.20);
	color: #f87171;
}
.action-bar-btn--danger:hover:not(:disabled) {
	background: rgba(248,113,113,0.15);
	color: #fca5a5;
}
.action-bar-btn--primary {
	background: #6d28d9;
	border-color: transparent;
	color: #fff;
	box-shadow: 0 0 14px rgba(109,40,217,0.35);
}
.action-bar-btn--primary:hover:not(:disabled) {
	background: #7c3aed;
	box-shadow: 0 0 18px rgba(124,58,237,0.45);
}

/* ── Section divider label ── */
.section-divider-label {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.1em;
	text-transform: uppercase;
	color: #4b5563;
	margin-bottom: 10px;
}
.section-divider-label::after {
	content: '';
	flex: 1;
	height: 1px;
	background: rgba(255,255,255,0.06);
}


/* ── Preview mode toggle ── */
.preview-toggle {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	padding: 4px 10px;
	border-radius: 6px;
	font-size: 11.5px;
	font-weight: 500;
	color: #6b7280;
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
}
.preview-toggle:hover { color: #d1d5db; }
.preview-toggle--active {
	background: rgba(139,92,246,0.18);
	color: #c4b5fd;
}

/* ── Diff output ── */
:global(.diff-ins) {
	background: rgba(74,222,128,0.15);
	color: #bbf7d0;
	border-radius: 2px;
	text-decoration: none;
}
:global(.diff-del) {
	background: rgba(248,113,113,0.15);
	color: #fca5a5;
	border-radius: 2px;
	text-decoration: line-through;
	text-decoration-color: rgba(248,113,113,0.5);
}
:global(.diff-eq) {
	color: #9ca3af;
}

:global(.katex-block-container) {
	overflow-x: auto;
	overflow-y: hidden;
	max-width: 100%;
	margin: 1rem 0;
	padding: 0.5rem 0;
}
</style>
