<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	const dispatch = createEventDispatcher();

	export let reports = [];
	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';

	let analyzing = false;
	let analysisResult = null;
	let error = null;
	let generatedTemplate = '';

	const styleDescriptions = {
		structured_template: 'Pre-written template with measurement placeholders',
		guided_template: 'Template with embedded guidance and instructions',
		checklist: 'Bullet-point list of structures to assess',
		normal_template: 'Complete normal report template'
	};

	async function analyzeReports() {
		analyzing = true;
		error = null;

		try {
			const response = await fetch(`${API_URL}/api/templates/analyze-reports`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({
					scan_type: scanType,
					contrast: contrast,
					protocol_details: protocolDetails || '',
					reports: reports
				})
			});

			const data = await response.json();
			if (data.success) {
				analysisResult = {
					template_config: data.template_config,
					detected_profile: data.detected_profile
				};
				// Extract findings template
				if (data.template_config && data.template_config.sections) {
					const findingsSection = data.template_config.sections.find(s => s.name === 'FINDINGS');
					if (findingsSection) {
						generatedTemplate = findingsSection.template_content || '';
					}
				}
			} else {
				error = data.error || 'Failed to analyze reports';
			}
		} catch (err) {
			console.error('Error analyzing reports:', err);
			error = 'Error analyzing reports. Please try again.';
		} finally {
			analyzing = false;
		}
	}

	function handleContinue() {
		if (analysisResult) {
			dispatch('analysisComplete', analysisResult);
		}
	}

	function getStyleDescription(style) {
		return styleDescriptions[style] || style;
	}

	// Auto-analyze on mount
	onMount(() => {
		analyzeReports();
	});
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">Analysis Results</h3>

	{#if analyzing}
		<div class="text-center py-12">
			<div class="text-4xl mb-4">🔍</div>
			<p class="text-gray-400">Analyzing your {reports.length} reports...</p>
			<p class="text-sm text-gray-500 mt-2">This may take a moment</p>
		</div>
	{:else if error}
		<div class="p-4 bg-red-600/20 border border-red-600/50 rounded text-red-300">
			{error}
		</div>
		<button
			onclick={analyzeReports}
			class="btn-primary"
		>
			Try Again
		</button>
	{:else if analysisResult}
		<div class="space-y-4">
			<div class="card-dark p-4 bg-green-600/10 border-green-600/30">
				<div class="flex items-center gap-2 mb-2">
					<span class="text-2xl">✓</span>
					<h4 class="font-semibold text-white">Analysis Complete</h4>
				</div>
				<p class="text-sm text-gray-400">We analyzed your {reports.length} reports</p>
			</div>

			<!-- Detected Profile -->
			{#if analysisResult.detected_profile}
				<div class="card-dark p-4">
					<h4 class="font-semibold text-white mb-3">Detected Profile:</h4>
					<div class="space-y-3 text-sm">
						<div>
							<strong class="text-gray-300">📝 Template Style:</strong>
							<span class="text-gray-400 ml-2">{analysisResult.detected_profile.template_style}</span>
							<p class="text-gray-500 text-xs mt-1">{getStyleDescription(analysisResult.detected_profile.template_style)}</p>
						</div>
						<div>
							<strong class="text-gray-300">📊 Verbosity:</strong>
							<span class="text-gray-400 ml-2">{analysisResult.detected_profile.verbosity}</span>
						</div>
						{#if analysisResult.detected_profile.sections}
							<div>
								<strong class="text-gray-300">📑 Sections Detected:</strong>
								<ul class="list-disc list-inside text-gray-400 mt-1">
									{#each analysisResult.detected_profile.sections as section}
										<li>✓ {section}</li>
									{/each}
								</ul>
							</div>
						{/if}
						{#if analysisResult.detected_profile.organization}
							<div>
								<strong class="text-gray-300">🎯 Organization:</strong>
								<span class="text-gray-400 ml-2">{analysisResult.detected_profile.organization}</span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<hr class="border-white/10" />

			<!-- Generated Template -->
			<div>
				<h4 class="font-semibold text-white mb-2">Generated FINDINGS Template:</h4>
				<textarea
					bind:value={generatedTemplate}
					rows="15"
					class="input-dark font-mono text-sm"
				></textarea>
				<div class="flex gap-2 mt-2">
					<button
						onclick={() => analyzeReports()}
						class="btn-secondary"
					>
						🔄 Regenerate
					</button>
				</div>
			</div>

			<hr class="border-white/10" />

			<!-- Continue Button -->
			<div class="flex justify-end">
				<button
					onclick={handleContinue}
					class="btn-primary"
				>
					Continue →
				</button>
			</div>
		</div>
	{/if}
</div>

