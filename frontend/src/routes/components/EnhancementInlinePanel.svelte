<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import pilotIcon from '$lib/assets/pilot.png';
	import { API_URL } from '$lib/config';

	const dispatch = createEventDispatcher();

	export let reportId: string | null = null;
	export let reportContent: string = '';
	export let visible: boolean = false;
	export let activeTab: 'guidelines' | 'comparison' | 'chat' = 'guidelines';

	interface ClassificationSystem {
		name: string;
		description?: string;
		categories?: string[];
		clinical_significance?: string;
	}
	interface MeasurementProtocol {
		measurement: string;
		threshold?: string;
		significance?: string;
		protocol?: string;
	}
	interface ImagingCharacteristic {
		feature: string;
		description?: string;
		significance?: string;
		modality?: string;
	}
	interface DifferentialDiagnosis {
		diagnosis: string;
		distinguishing_features?: string;
	}
	interface FollowUpImaging {
		modality: string;
		timing?: string;
		indication?: string;
		protocol?: string;
	}
	interface SourceLink {
		url: string;
		title?: string;
		snippet?: string;
		domain?: string;
	}
	interface GuidelineEntry {
		finding: { finding: string };
		diagnostic_overview?: string;
		guideline_summary?: string;
		classification_systems?: ClassificationSystem[];
		measurement_protocols?: MeasurementProtocol[];
		imaging_characteristics?: ImagingCharacteristic[];
		differential_diagnoses?: DifferentialDiagnosis[];
		follow_up_imaging?: FollowUpImaging[];
		sources?: SourceLink[];
	}

	let loading = false;
	let error: string | null = null;
	let guidelinesData: GuidelineEntry[] = [];
	// Track which guideline cards are expanded; first is open by default
	let expandedCards = new Set<number>([0]);
	// Track source expansion per card
	let expandedSources = new Set<number>();
	// Clear stale data when the report being viewed changes
	let _prevReportId: string | null = null;
	$: if (reportId !== _prevReportId) {
		_prevReportId = reportId;
		guidelinesData = [];
		expandedCards = new Set([0]);
		expandedSources = new Set();
		error = null;
	}

	let chatMessages: Array<{
		role: 'user' | 'assistant';
		content: string;
		sources?: SourceLink[];
		error?: boolean;
	}> = [];
	let chatInput = '';
	let chatLoading = false;

	marked.setOptions({ breaks: true, gfm: true });

	function renderMarkdown(md: string) {
		if (!md) return '';
		let p = md.replace(/\\n/g, '\n');
		p = p.replace(/\.\s*•\s*/g, '.\n- ');
		p = p.replace(/(^|[\n\r])•\s*/g, '$1- ');
		p = p.replace(/([.!?])\s+•\s+/g, '$1\n- ');
		p = p.replace(/\s+•\s+/g, '\n- ');
		p = p.replace(/^[\s]*-[\s]+-[\s]+/gm, '- ');
		p = p.replace(/^[\s]{2,}-[\s]+/gm, '- ');
		return marked.parse(p);
	}

	function toggleCard(i: number) {
		const n = new Set(expandedCards);
		if (n.has(i)) n.delete(i); else n.add(i);
		expandedCards = n;
	}

	function toggleSources(i: number) {
		const n = new Set(expandedSources);
		if (n.has(i)) n.delete(i); else n.add(i);
		expandedSources = n;
	}

	function domainFromUrl(url: string): string {
		try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
	}

	function sectionCount(g: GuidelineEntry): number {
		let n = 0;
		if (g.classification_systems?.length) n++;
		if (g.measurement_protocols?.length) n++;
		if (g.imaging_characteristics?.length) n++;
		if (g.differential_diagnoses?.length) n++;
		if (g.follow_up_imaging?.length) n++;
		return n;
	}

	async function loadEnhancements() {
		if (!reportId || loading) return;
		loading = true;
		error = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const response = await fetch(`${API_URL}/api/reports/${reportId}/enhance`, {
				method: 'POST', headers
			});
			if (!response.ok) { error = 'Something went wrong. Please try again.'; return; }
			const data = await response.json();
			if (data?.success) {
				guidelinesData = [...(data.guidelines || [])];
				expandedCards = new Set([0]);
				error = null;
				dispatch('enhancementState', {
					guidelinesCount: guidelinesData.length,
					isLoading: false,
					hasError: false
				});
			} else {
				error = 'Failed to load enhancements. Please try again.';
			}
		} catch {
			error = 'Failed to connect. Please try again.';
		} finally {
			loading = false;
		}
	}

	async function sendChatMessage() {
		if (!chatInput.trim() || !reportId) return;
		const userMessage = chatInput.trim();
		chatInput = '';
		chatMessages = [...chatMessages, { role: 'user', content: userMessage }];
		chatLoading = true;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const response = await fetch(`${API_URL}/api/reports/${reportId}/chat`, {
				method: 'POST', headers,
				body: JSON.stringify({ message: userMessage, history: chatMessages.slice(0, -1) })
			});
			const data: any = await response.json();
			if (data.success) {
				chatMessages = [...chatMessages, { role: 'assistant', content: data.response, sources: data.sources || [] }];
			} else {
				chatMessages = [...chatMessages, { role: 'assistant', content: 'Something went wrong. Please try again.', error: true }];
			}
		} catch (err) {
			chatMessages = [...chatMessages, { role: 'assistant', content: `Error: ${err instanceof Error ? err.message : String(err)}`, error: true }];
		} finally {
			chatLoading = false;
		}
	}

	function handleKeyPress(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
	}

	$: if (visible && reportId && activeTab === 'guidelines' && guidelinesData.length === 0 && !loading) {
		loadEnhancements();
	}
</script>

{#if visible}
<div class="absolute right-0 top-0 h-full w-96 bg-gray-900/97 backdrop-blur-xl border-l border-gray-700/60 shadow-2xl flex flex-col z-20 transition-all duration-300 ease-in-out">

	<!-- Header -->
	<div class="flex-shrink-0 p-4 border-b border-gray-700/60">
		<div class="flex items-center justify-between mb-3">
			<div class="flex items-center gap-2">
				<img src={pilotIcon} alt="Copilot" class="w-5 h-5 brightness-0 invert opacity-80" />
				<h2 class="text-base font-semibold text-white">Copilot</h2>
			</div>
			<button onclick={() => dispatch('close')} class="p-1 text-gray-500 hover:text-white transition-colors rounded" aria-label="Close panel">
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>
		<div class="flex gap-1">
			{#each [['guidelines','Guidelines'], ['comparison','Compare'], ['chat','Chat']] as [id, label]}
				<button
					onclick={() => activeTab = id as any}
					class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {activeTab === id ? 'bg-violet-600 text-white' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'}"
				>{label}</button>
			{/each}
		</div>
	</div>

	<!-- Content -->
	<div class="flex-1 overflow-y-auto">

		<!-- ── GUIDELINES TAB ── -->
		{#if activeTab === 'guidelines'}

			{#if loading}
				<!-- Skeleton loading state -->
				<div class="p-4 space-y-3">
					<div class="flex items-center gap-2 mb-4">
						<div class="w-4 h-4 rounded-full bg-violet-500/30 animate-pulse"></div>
						<div class="h-3 w-48 bg-gray-700 rounded animate-pulse"></div>
					</div>

					{#each [0, 1] as sk}
						<div class="rounded-lg border border-gray-700/50 bg-gray-800/40 overflow-hidden animate-pulse">
							<!-- Card header skeleton -->
							<div class="p-3.5 flex items-center justify-between border-b border-gray-700/30">
								<div class="flex-1 space-y-2">
									<div class="h-3.5 bg-gray-600/60 rounded w-3/5"></div>
									<div class="flex gap-1.5">
										{#each [0, 1, 2] as _}
											<div class="h-2 bg-gray-700/50 rounded-full w-14"></div>
										{/each}
									</div>
								</div>
								<div class="w-4 h-4 bg-gray-700/40 rounded ml-3"></div>
							</div>
							<!-- Card body skeleton (only for first card) -->
							{#if sk === 0}
								<div class="p-3.5 space-y-3">
									<div class="space-y-1.5">
										<div class="h-2.5 bg-gray-700/50 rounded w-full"></div>
										<div class="h-2.5 bg-gray-700/50 rounded w-5/6"></div>
										<div class="h-2.5 bg-gray-700/50 rounded w-4/6"></div>
									</div>
									<div class="h-px bg-gray-700/40 rounded"></div>
									<div class="space-y-1.5">
										<div class="h-2 bg-gray-700/40 rounded-full w-28"></div>
										{#each [0,1] as _}
											<div class="flex gap-2 items-start pl-1">
												<div class="w-1.5 h-1.5 rounded-full bg-violet-500/30 mt-1 flex-shrink-0"></div>
												<div class="h-2.5 bg-gray-700/40 rounded flex-1"></div>
											</div>
										{/each}
									</div>
									<div class="h-px bg-gray-700/40 rounded"></div>
									<div class="space-y-1.5">
										<div class="h-2 bg-gray-700/40 rounded-full w-24"></div>
										{#each [0,1] as _}
											<div class="h-8 bg-gray-700/30 rounded-md"></div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					{/each}

					<p class="text-xs text-gray-500 text-center pt-1 animate-pulse">Searching guidelines…</p>
				</div>

			{:else if error}
				<div class="p-4">
					<div class="border border-red-500/25 bg-red-500/8 rounded-lg p-4">
						<p class="text-red-400 text-sm font-medium mb-1">Error loading guidelines</p>
						<p class="text-red-300/80 text-xs mb-3">{error}</p>
						<button onclick={loadEnhancements} class="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs rounded-md transition-colors">
							Retry
						</button>
					</div>
				</div>

			{:else if guidelinesData.length === 0}
				<div class="flex flex-col items-center justify-center h-full px-6 text-center gap-3">
					<svg class="w-8 h-8 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
					</svg>
					<p class="text-gray-500 text-sm">No guidelines found for this report.</p>
				</div>

			{:else}
				<div class="p-3 space-y-2">
					<!-- Finding count badge -->
					<div class="flex items-center gap-2 px-1 pb-1">
						<span class="text-xs text-gray-500">{guidelinesData.length} finding{guidelinesData.length !== 1 ? 's' : ''} analysed</span>
						<div class="flex-1 h-px bg-gray-800"></div>
					</div>

					{#each guidelinesData as g, i}
						{@const isOpen = expandedCards.has(i)}
						{@const hasFollowUp = (g.follow_up_imaging?.length ?? 0) > 0}
						{@const sc = sectionCount(g)}

						<div class="rounded-lg border {isOpen ? 'border-violet-600/30 bg-gray-800/60' : 'border-gray-700/40 bg-gray-800/30'} overflow-hidden transition-colors duration-150">

							<!-- Card Header (always visible) -->
							<button
								onclick={() => toggleCard(i)}
								class="w-full p-3.5 flex items-start gap-3 text-left hover:bg-white/3 transition-colors group"
							>
								<!-- Chevron -->
								<svg class="w-4 h-4 text-gray-500 group-hover:text-gray-300 flex-shrink-0 mt-0.5 transition-transform duration-200 {isOpen ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
								</svg>
								<div class="flex-1 min-w-0">
									<p class="text-sm font-medium text-white leading-snug capitalize">{g.finding.finding}</p>
									{#if !isOpen}
										<div class="flex flex-wrap gap-1 mt-1.5">
											{#if g.classification_systems?.length}
												<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-violet-300/80 bg-violet-500/10 border border-violet-500/15">
													{g.classification_systems.length} classification{g.classification_systems.length > 1 ? 's' : ''}
												</span>
											{/if}
											{#if g.imaging_characteristics?.length}
												<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-blue-300/80 bg-blue-500/10 border border-blue-500/15">
													{g.imaging_characteristics.length} imaging criteria
												</span>
											{/if}
											{#if hasFollowUp}
												<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-emerald-300/80 bg-emerald-500/10 border border-emerald-500/15">
													{g.follow_up_imaging!.length} follow-up
												</span>
											{/if}
											{#if !g.classification_systems?.length && !g.imaging_characteristics?.length && !hasFollowUp}
												<span class="text-[10px] text-gray-600">{sc} section{sc !== 1 ? 's' : ''}</span>
											{/if}
										</div>
									{/if}
								</div>
							</button>

							<!-- Card Body (expanded) -->
							{#if isOpen}
								<div class="border-t border-gray-700/40 divide-y divide-gray-700/30">

									<!-- Diagnostic Overview -->
									{#if g.diagnostic_overview}
										<div class="p-3.5">
											<div class="prose prose-invert prose-xs max-w-none
												prose-p:text-gray-300 prose-p:text-xs prose-p:leading-relaxed prose-p:my-1
												prose-strong:text-white prose-strong:font-medium
												prose-ul:my-1 prose-ul:pl-4 prose-ul:space-y-0.5
												prose-li:text-gray-300 prose-li:text-xs prose-li:leading-relaxed">
												{@html renderMarkdown(g.diagnostic_overview)}
											</div>
										</div>
									{/if}

									<!-- Classification Systems -->
									{#if g.classification_systems?.length}
										<div class="p-3.5">
											<div class="flex items-center gap-1.5 mb-2">
												<svg class="w-3.5 h-3.5 text-violet-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
												</svg>
												<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Classification</p>
											</div>
											<div class="space-y-2">
												{#each g.classification_systems as cs}
													<div class="rounded-md bg-violet-500/8 border border-violet-500/12 px-3 py-2">
														<p class="text-xs font-medium text-violet-200">{cs.name}</p>
														{#if cs.description}
															<p class="text-xs text-gray-400 mt-0.5 leading-relaxed">{cs.description}</p>
														{/if}
														{#if cs.categories?.length}
															<div class="flex flex-wrap gap-1 mt-1.5">
																{#each cs.categories as cat}
																	<span class="px-1.5 py-0.5 rounded-sm text-[10px] bg-violet-600/20 text-violet-300/90 border border-violet-500/15">{cat}</span>
																{/each}
															</div>
														{/if}
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<!-- Imaging Characteristics -->
									{#if g.imaging_characteristics?.length}
										<div class="p-3.5">
											<div class="flex items-center gap-1.5 mb-2">
												<svg class="w-3.5 h-3.5 text-blue-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
												</svg>
												<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Imaging Criteria</p>
											</div>
											<ul class="space-y-1.5">
												{#each g.imaging_characteristics as ic}
													<li class="flex gap-2 items-start">
														<span class="w-1 h-1 rounded-full bg-blue-400/60 flex-shrink-0 mt-1.5"></span>
														<div class="min-w-0">
															<span class="text-xs text-gray-200">{ic.feature}</span>
															{#if ic.description}
																<span class="text-xs text-gray-500"> — {ic.description}</span>
															{/if}
														</div>
													</li>
												{/each}
											</ul>
										</div>
									{/if}

									<!-- Measurement Protocols -->
									{#if g.measurement_protocols?.length}
										<div class="p-3.5">
											<div class="flex items-center gap-1.5 mb-2">
												<svg class="w-3.5 h-3.5 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
												</svg>
												<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Measurements & Thresholds</p>
											</div>
											<div class="space-y-1.5">
												{#each g.measurement_protocols as mp}
													<div class="flex items-start gap-2">
														<span class="w-1 h-1 rounded-full bg-amber-400/60 flex-shrink-0 mt-1.5"></span>
														<div class="min-w-0">
															<span class="text-xs text-gray-200">{mp.measurement}</span>
															{#if mp.threshold}
																<span class="ml-1 px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-300/90 border border-amber-500/15">{mp.threshold}</span>
															{/if}
															{#if mp.significance}
																<p class="text-[11px] text-gray-500 mt-0.5">{mp.significance}</p>
															{/if}
														</div>
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<!-- Differential Diagnoses -->
									{#if g.differential_diagnoses?.length}
										<div class="p-3.5">
											<div class="flex items-center gap-1.5 mb-2">
												<svg class="w-3.5 h-3.5 text-rose-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
												</svg>
												<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Differentials</p>
											</div>
											<div class="flex flex-wrap gap-1.5">
												{#each g.differential_diagnoses as dd}
													<div class="rounded-md px-2 py-1 bg-rose-500/8 border border-rose-500/12">
														<p class="text-xs text-rose-200/80">{dd.diagnosis}</p>
														{#if dd.distinguishing_features}
															<p class="text-[10px] text-gray-500 mt-0.5 leading-snug">{dd.distinguishing_features}</p>
														{/if}
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<!-- Follow-up Imaging -->
									{#if hasFollowUp}
										<div class="p-3.5">
											<div class="flex items-center gap-1.5 mb-2">
												<svg class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
												</svg>
												<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Follow-up Imaging</p>
											</div>
											<div class="space-y-1.5">
												{#each g.follow_up_imaging! as fi}
													<div class="rounded-md bg-emerald-500/8 border border-emerald-500/12 px-3 py-2">
														<div class="flex items-start justify-between gap-2">
															<p class="text-xs font-medium text-emerald-200 leading-snug">{fi.modality}</p>
															{#if fi.timing}
																<span class="text-[10px] text-emerald-400/70 flex-shrink-0 font-medium">{fi.timing}</span>
															{/if}
														</div>
														{#if fi.indication}
															<p class="text-[11px] text-gray-400 mt-0.5 leading-snug">{fi.indication}</p>
														{/if}
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<!-- Sources -->
									{#if g.sources?.length}
										<div class="p-3.5">
											<button
												onclick={() => toggleSources(i)}
												class="flex items-center gap-1.5 text-[10px] font-medium text-gray-500 hover:text-gray-300 transition-colors"
											>
												<svg class="w-3 h-3 transition-transform duration-150 {expandedSources.has(i) ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
												</svg>
												{g.sources.length} source{g.sources.length !== 1 ? 's' : ''}
											</button>
											{#if expandedSources.has(i)}
												<ul class="mt-2 space-y-1.5">
													{#each g.sources as src}
														<li class="flex items-start gap-1.5 group/src">
															<span class="w-1 h-1 rounded-full bg-gray-600 flex-shrink-0 mt-1.5"></span>
															<a href={src.url} target="_blank" rel="noopener noreferrer"
																class="text-[11px] text-blue-400/80 hover:text-blue-300 truncate leading-snug transition-colors">
																{src.title?.trim() || domainFromUrl(src.url)}
															</a>
														</li>
													{/each}
												</ul>
											{/if}
										</div>
									{/if}

								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

		<!-- ── COMPARISON TAB ── -->
		{:else if activeTab === 'comparison'}
			<div class="flex flex-col items-center justify-center h-full px-6 text-center gap-3">
				<svg class="w-8 h-8 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
				</svg>
				<p class="text-gray-500 text-sm">Comparison — coming soon</p>
			</div>

		<!-- ── CHAT TAB ── -->
		{:else if activeTab === 'chat'}
			<div class="flex flex-col h-full">
				<div class="flex-1 overflow-y-auto p-4 space-y-3">
					{#if chatMessages.length === 0}
						<div class="flex flex-col items-center justify-center h-full gap-3 text-center px-4">
							<div class="w-8 h-8 rounded-full bg-violet-600/20 flex items-center justify-center">
								<svg class="w-4 h-4 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
								</svg>
							</div>
							<p class="text-gray-500 text-sm">Ask anything about this report or request edits.</p>
						</div>
					{:else}
						{#each chatMessages as msg}
							<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
								<div class="max-w-[85%] {msg.role === 'user' ? 'bg-violet-600' : msg.error ? 'bg-red-500/15 border border-red-500/25' : 'bg-gray-800'} rounded-xl px-3 py-2.5">
									<div class="prose prose-invert max-w-none text-xs prose-p:leading-relaxed prose-p:my-0.5 prose-strong:text-white prose-li:text-gray-200 {msg.error ? 'text-red-300' : 'text-gray-100'}">
										{@html renderMarkdown(msg.content)}
									</div>
									{#if msg.sources?.length}
										<div class="mt-2 pt-2 border-t border-gray-700/50">
											<p class="text-[10px] font-medium text-gray-500 mb-1">Sources</p>
											<ul class="space-y-1">
												{#each msg.sources as src}
													<li class="src-ref-item text-[11px]">
														<a href={src.url} target="_blank" rel="noopener noreferrer"
															class="text-violet-400/80 hover:text-violet-300 truncate block">
															{src.title?.trim() || domainFromUrl(src.url)}
														</a>
														{#if src.snippet?.trim()}
															<div class="src-snippet">{src.snippet}</div>
														{/if}
													</li>
												{/each}
											</ul>
										</div>
									{/if}
								</div>
							</div>
						{/each}
					{/if}

					{#if chatLoading}
						<div class="flex justify-start">
							<div class="bg-gray-800 rounded-xl px-3 py-2.5">
								<div class="flex gap-1 items-center">
									{#each [0,1,2] as d}
										<div class="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce" style="animation-delay: {d * 150}ms"></div>
									{/each}
								</div>
							</div>
						</div>
					{/if}
				</div>

				<div class="flex-shrink-0 border-t border-gray-700/50 p-3">
					<div class="flex gap-2">
						<textarea
							bind:value={chatInput}
							onkeypress={handleKeyPress}
							placeholder="Ask about the report…"
							class="flex-1 bg-gray-800 border border-gray-700/60 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 resize-none focus:outline-none focus:border-violet-500/50 transition-colors"
							rows="2"
							disabled={chatLoading || !reportId}
						></textarea>
						<button
							onclick={sendChatMessage}
							disabled={!chatInput.trim() || chatLoading || !reportId}
							class="px-3 py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center"
						>
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
							</svg>
						</button>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
{/if}

<style>
	.src-ref-item .src-snippet {
		max-height: 0;
		overflow: hidden;
		opacity: 0;
		font-size: 0.67rem;
		line-height: 1.45;
		color: rgb(107, 114, 128);
		margin-top: 0;
		transition: max-height 0.2s ease, opacity 0.18s ease, margin-top 0.15s ease;
	}
	.src-ref-item:hover .src-snippet {
		max-height: 5rem;
		opacity: 1;
		margin-top: 2px;
	}
</style>
