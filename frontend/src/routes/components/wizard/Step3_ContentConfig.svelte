<script>
	import { createEventDispatcher } from 'svelte';
	import Step4_FindingsSetup from './Step4_FindingsSetup.svelte';
	import Step5_ImpressionSetup from './Step5_ImpressionSetup.svelte';

	const dispatch = createEventDispatcher();

	export let findingsConfig = {};
	export let impressionConfig = {};
	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';

	// Which section is expanded (only one at a time for minimal feel)
	let activeSection = 'findings'; // 'findings' | 'impression'
	let hasViewedImpression = false;

	function switchToImpression() {
		activeSection = 'impression';
		hasViewedImpression = true;
	}

	function handleNext() {
		if (!findingsConfig.content_style || !findingsConfig.template_content?.trim()) {
			alert('Please configure FINDINGS: select a content style and provide template content.');
			return;
		}
		if (!hasViewedImpression) {
			// Switch to impression and prompt - don't allow next yet
			activeSection = 'impression';
			hasViewedImpression = true;
			return;
		}
		dispatch('next');
	}

	$: findingsComplete = findingsConfig.content_style && findingsConfig.template_content?.trim();
	$: canProceed = findingsComplete && hasViewedImpression;
</script>

<div class="space-y-4">
	<h3 class="text-xl font-semibold text-white mb-2">Content Configuration</h3>
	<p class="text-gray-400 text-sm mb-6">
		Configure FINDINGS and IMPRESSION sections. Expand each to edit.
	</p>

	<!-- Minimal dropdown-style selector -->
	<div class="flex gap-2 mb-4">
		<button
			type="button"
			onclick={() => (activeSection = 'findings')}
			class="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all
				{activeSection === 'findings'
					? 'bg-purple-500/30 border border-purple-500/50 text-white'
					: 'bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:border-white/20'}"
		>
			📝 FINDINGS
		</button>
		<button
			type="button"
			onclick={switchToImpression}
			class="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all
				{activeSection === 'impression'
					? 'bg-purple-500/30 border border-purple-500/50 text-white'
					: 'bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:border-white/20'}"
		>
			💡 IMPRESSION
		</button>
	</div>

	<!-- Content area - only show active section -->
	<div class="min-h-[320px] rounded-xl border border-white/10 bg-black/20 overflow-hidden">
		{#if activeSection === 'findings'}
			<div class="p-4 overflow-y-auto max-h-[480px]">
				<Step4_FindingsSetup
					bind:findingsConfig
					{scanType}
					{contrast}
					{protocolDetails}
					embedded={true}
				/>
			</div>
		{:else}
			<div class="p-4 overflow-y-auto max-h-[480px]">
				<Step5_ImpressionSetup
					bind:impressionConfig
					embedded={true}
				/>
			</div>
		{/if}
	</div>

	<!-- Prompt to review Impression when Findings done but not yet viewed -->
	{#if findingsComplete && !hasViewedImpression}
		<div class="flex items-center gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200/90 text-sm">
			<span class="text-lg">💡</span>
			<span>FINDINGS configured. Please review <button type="button" onclick={switchToImpression} class="font-semibold underline hover:no-underline">IMPRESSION</button> settings before continuing.</span>
		</div>
	{/if}

	<div class="flex justify-end pt-4">
		<button
			onclick={handleNext}
			disabled={!canProceed}
			class="btn-primary"
			class:opacity-50={!canProceed}
			class:cursor-not-allowed={!canProceed}
		>
			Next →
		</button>
	</div>
</div>
