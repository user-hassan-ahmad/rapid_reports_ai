<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import pilotIcon from '$lib/assets/pilot.png';
	import { API_URL } from '$lib/config';
	import { logger } from '$lib/utils/logger';
	
	const dispatch = createEventDispatcher();
	
	export let reportId: string | null = null;
	export let reportContent: string = '';
	export let visible: boolean = false;
	export let activeTab: 'guidelines' | 'comparison' | 'chat' = 'guidelines';
	
	// Reuse types from ReportEnhancementSidebar
	interface Finding {
		finding: string;
		[key: string]: unknown;
	}
	
	interface GuidelineEntry {
		finding: Finding;
		diagnostic_overview?: string;
		guideline_summary?: string;
		[key: string]: unknown;
	}
	
	let loading = false;
	let error: string | null = null;
	let guidelinesData: GuidelineEntry[] = [];
	let chatMessages: Array<{ role: 'user' | 'assistant'; content: string; sources?: string[]; error?: boolean }> = [];
	let chatInput = '';
	let chatLoading = false;
	
	marked.setOptions({
		breaks: true,
		gfm: true
	});
	
	function renderMarkdown(md: string) {
		if (!md) return '';
		let processed = md.replace(/\\n/g, '\n');
		processed = processed.replace(/\.\s*•\s*/g, '.\n- ');
		processed = processed.replace(/(^|[\n\r])•\s*/g, '$1- ');
		processed = processed.replace(/([.!?])\s+•\s+/g, '$1\n- ');
		processed = processed.replace(/\s+•\s+/g, '\n- ');
		processed = processed.replace(/^[\s]*-[\s]+-[\s]+/gm, '- ');
		processed = processed.replace(/^[\s]{2,}-[\s]+/gm, '- ');
		return marked.parse(processed);
	}
	
	async function loadEnhancements() {
		if (!reportId || loading) return;
		
		loading = true;
		error = null;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			const response = await fetch(`${API_URL}/api/reports/${reportId}/enhance?skip_completeness=true`, {
				method: 'POST',
				headers
			});
			
			if (!response.ok) {
				const errorText = await response.text();
				error = `HTTP ${response.status}: ${errorText}`;
				return;
			}
			
			const data = await response.json();
			
			if (data && data.success) {
				guidelinesData = [...(data.guidelines || [])];
				error = null;
				dispatch('enhancementState', {
					guidelinesCount: guidelinesData.length,
					isLoading: false,
					hasError: false
				});
			} else {
				error = data.error || 'Failed to load enhancements';
			}
		} catch (err) {
			error = `Failed to connect: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			loading = false;
		}
	}
	
	async function sendChatMessage() {
		if (!chatInput.trim() || !reportId) return;
		
		const userMessage = chatInput.trim();
		chatInput = '';
		chatMessages.push({ role: 'user', content: userMessage });
		chatMessages = [...chatMessages];
		
		chatLoading = true;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			const response = await fetch(`${API_URL}/api/reports/${reportId}/chat`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					message: userMessage,
					history: chatMessages.slice(0, -1)
				})
			});
			
			const data: any = await response.json();
			
			if (data.success) {
				chatMessages.push({
					role: 'assistant',
					content: data.response,
					sources: data.sources || []
				});
				chatMessages = [...chatMessages];
			} else {
				chatMessages.push({
					role: 'assistant',
					content: `Error: ${data.error || 'Failed to get response'}`,
					error: true
				});
				chatMessages = [...chatMessages];
			}
		} catch (err) {
			chatMessages.push({
				role: 'assistant',
				content: `Error: ${err instanceof Error ? err.message : String(err)}`,
				error: true
			});
			chatMessages = [...chatMessages];
		} finally {
			chatLoading = false;
		}
	}
	
	function handleKeyPress(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendChatMessage();
		}
	}
	
	// Load enhancements when panel opens
	$: if (visible && reportId && activeTab === 'guidelines' && guidelinesData.length === 0 && !loading) {
		loadEnhancements();
	}
</script>

{#if visible}
	<div class="absolute right-0 top-0 h-full w-96 bg-gray-900/95 backdrop-blur-xl border-l border-gray-700 shadow-2xl flex flex-col transition-all duration-300 ease-in-out z-20">
		<!-- Header -->
		<div class="p-4 border-b border-gray-700">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-2">
					<img src={pilotIcon} alt="Copilot" class="w-6 h-6 brightness-0 invert" />
					<h2 class="text-lg font-bold text-white">Copilot</h2>
				</div>
				<button
					onclick={() => dispatch('close')}
					class="p-1 text-gray-400 hover:text-white transition-colors"
					aria-label="Close panel"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			
			<!-- Tabs -->
			<div class="flex gap-2">
				<button
					onclick={() => activeTab = 'guidelines'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'guidelines' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Guidelines
				</button>
				<button
					onclick={() => activeTab = 'comparison'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'comparison' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Comparison
				</button>
				<button
					onclick={() => activeTab = 'chat'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'chat' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Chat
				</button>
			</div>
		</div>
		
		<!-- Content -->
		<div class="flex-1 overflow-y-auto p-4">
			{#if activeTab === 'guidelines'}
				{#if loading}
					<div class="flex items-center justify-center h-full">
						<div class="text-gray-400">Loading guidelines...</div>
					</div>
				{:else if error}
					<div class="border border-red-500/30 bg-red-500/10 rounded-lg p-4">
						<p class="text-red-400 font-medium mb-1">Error</p>
						<p class="text-red-300 text-sm">{error}</p>
						<button
							onclick={loadEnhancements}
							class="mt-2 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg transition-colors"
						>
							Retry
						</button>
					</div>
				{:else if guidelinesData.length === 0}
					<div class="text-gray-400 text-center py-8">
						No guidelines found for this report.
					</div>
				{:else}
					<div class="space-y-4">
						{#each guidelinesData as guideline, idx}
							<div class="border border-gray-700 rounded-lg bg-gray-800/50 overflow-hidden">
								<div class="p-4">
									<h3 class="text-lg font-semibold text-white mb-2">
										{guideline.finding.finding}
									</h3>
									{#if guideline.diagnostic_overview}
										<div class="prose prose-invert prose-sm max-w-none
											prose-headings:text-white prose-headings:font-semibold
											prose-p:text-gray-300 prose-p:leading-relaxed
											prose-strong:text-white prose-strong:font-semibold
											prose-ul:my-2 prose-ul:pl-5 prose-ul:space-y-1.5 prose-ul:list-disc
											prose-li:text-gray-300 prose-li:leading-relaxed">
											{@html renderMarkdown(guideline.diagnostic_overview)}
										</div>
									{:else if guideline.guideline_summary}
										<div class="prose prose-invert prose-sm max-w-none
											prose-headings:text-white prose-headings:font-semibold
											prose-p:text-gray-300 prose-p:leading-relaxed
											prose-strong:text-white prose-strong:font-semibold
											prose-ul:my-2 prose-ul:pl-5 prose-ul:space-y-1.5 prose-ul:list-disc
											prose-li:text-gray-300 prose-li:leading-relaxed">
											{@html renderMarkdown(guideline.guideline_summary)}
										</div>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			{:else if activeTab === 'comparison'}
				<div class="text-gray-400 text-center py-8">
					Comparison feature - coming soon
				</div>
			{:else if activeTab === 'chat'}
				<div class="flex flex-col h-full">
					<div class="flex-1 overflow-y-auto mb-4 space-y-4">
						{#if chatMessages.length === 0}
							<div class="text-gray-400 text-center py-8">
								Ask questions about the report or request improvements.
							</div>
						{:else}
							{#each chatMessages as msg}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									<div class="max-w-[80%] {msg.role === 'user' ? 'bg-purple-600' : msg.error ? 'bg-red-500/20 border border-red-500/30' : 'bg-gray-800'} rounded-lg p-3">
										<div class="prose prose-invert max-w-none text-sm {msg.error ? 'text-red-300' : 'text-gray-100'}">
											{@html renderMarkdown(msg.content)}
										</div>
										{#if msg.sources && msg.sources.length > 0}
											<div class="mt-2 pt-2 border-t border-gray-700">
												<p class="text-xs font-medium text-gray-400 mb-1">Sources:</p>
												<ul class="space-y-1">
													{#each msg.sources as source}
														<li>
															<a
																href={source}
																target="_blank"
																rel="noopener noreferrer"
																class="text-xs text-purple-400 hover:text-purple-300 underline truncate block"
															>
																{source}
															</a>
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
								<div class="bg-gray-800 rounded-lg p-3">
									<div class="text-sm text-gray-400">Thinking...</div>
								</div>
							</div>
						{/if}
					</div>
					
					<div class="border-t border-gray-700 pt-4">
						<div class="flex gap-2">
							<textarea
								bind:value={chatInput}
								onkeypress={handleKeyPress}
								placeholder="Ask about the report..."
								class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 resize-none"
								rows="2"
								disabled={chatLoading || !reportId}
							></textarea>
							<button
								onclick={sendChatMessage}
								disabled={!chatInput.trim() || chatLoading || !reportId}
								class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
							>
								Send
							</button>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

