<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	export let scanType = '';
	export let contrast = '';
	export let contrastPhases = [];
	export let protocolDetails = '';
	export let creationMethod = '';
	export let sections = {};
	export let findingsConfig = {};
	export let impressionConfig = {};
	export let analysisResult = null;

	let showFullFindingsTemplate = false;

	function getStyleLabel(styleId) {
		const labels = {
			'structured_template': 'Structured Fill-In',
			'normal_template': 'Normal Report',
			'guided_template': 'Guided Template',
			'checklist': 'Checklist'
		};
		return labels[styleId] || styleId;
	}

	function getContrastLabel(contrastValue) {
		const labels = {
			'no_contrast': 'Non-contrast',
			'with_contrast': 'With contrast',
			'with_iv': 'With IV contrast', // Legacy support
			'arterial': 'Arterial phase', // Legacy support
			'portal_venous': 'Portal venous phase', // Legacy support
			'other': 'Other (custom)'
		};
		
		// If it's already a natural language string (from saved templates), return as-is
		if (contrastValue && !labels[contrastValue] && !contrastValue.includes('_')) {
			return contrastValue;
		}
		
		// Handle new format with phases
		if (contrastValue === 'with_contrast' && contrastPhases && contrastPhases.length > 0) {
			const phaseLabels = {
				'pre': 'Pre-contrast',
				'arterial': 'Arterial',
				'portal_venous': 'Portal venous',
				'delayed': 'Delayed',
				'oral': 'Oral'
			};
			const phases = contrastPhases.map(p => phaseLabels[p] || p).join(', ');
			return `With contrast (${phases})`;
		}
		
		return labels[contrastValue] || contrastValue || 'Not specified';
	}
</script>

<div class="space-y-6">
	<div class="text-center mb-8">
		<h3 class="text-2xl font-bold text-white mb-2">Review Configuration</h3>
		<p class="text-gray-400 text-sm max-w-2xl mx-auto">
			Review your template configuration before saving. Everything looks good? Proceed to save your template.
		</p>
	</div>

	<div class="max-w-4xl mx-auto space-y-4">
		<!-- Scan Information -->
		<div class="bg-gradient-to-br from-purple-900/20 to-blue-900/20 border border-purple-500/30 rounded-lg p-5 shadow-lg gradient-card animate-fade-in">
			<div class="flex items-start gap-4">
				<div class="flex-shrink-0">
					<div class="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center transition-transform duration-200 hover:scale-110">
						<span class="text-xl">🔬</span>
					</div>
				</div>
				<div class="flex-1">
					<h4 class="text-lg font-bold text-white mb-3 flex items-center gap-2">
						<span>Scan Information</span>
					</h4>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
						<div class="flex items-start gap-2">
							<span class="text-purple-400 font-semibold min-w-[100px]">Scan Type:</span>
							<span class="text-gray-300">{scanType || 'Not specified'}</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-purple-400 font-semibold min-w-[100px]">Contrast:</span>
							<span class="text-gray-300">{getContrastLabel(contrast)}</span>
						</div>
						{#if protocolDetails}
							<div class="flex items-start gap-2 md:col-span-2">
								<span class="text-purple-400 font-semibold min-w-[100px]">Protocol Details:</span>
								<span class="text-gray-300">{protocolDetails}</span>
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<!-- Sections -->
		<div class="bg-gradient-to-br from-blue-900/20 to-cyan-900/20 border border-blue-500/30 rounded-lg p-5 shadow-lg gradient-card animate-fade-in" style="animation-delay: 0.05s">
			<div class="flex items-start gap-4">
				<div class="flex-shrink-0">
					<div class="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center transition-transform duration-200 hover:scale-110">
						<span class="text-xl">📋</span>
					</div>
				</div>
				<div class="flex-1">
					<h4 class="text-lg font-bold text-white mb-3">Report Sections</h4>
					<div class="space-y-2">
						<div class="flex items-center gap-2 text-sm">
							<span class="text-green-400 text-lg">✓</span>
							<span class="text-gray-300">
								<strong class="text-white">CLINICAL HISTORY</strong>
								<span class="text-gray-400 ml-2">
									{sections.clinical_history?.include_in_output ? '(included in output)' : '(context only)'}
								</span>
							</span>
						</div>
						{#if sections.comparison?.included}
							<div class="flex items-center gap-2 text-sm">
								<span class="text-green-400 text-lg">✓</span>
								<span class="text-gray-300">
									<strong class="text-white">COMPARISON</strong>
									<span class="text-gray-400 ml-2">({sections.comparison.has_input_field ? 'manual input' : 'auto-generated'})</span>
								</span>
							</div>
						{/if}
						{#if sections.technique?.included}
							<div class="flex items-center gap-2 text-sm">
								<span class="text-green-400 text-lg">✓</span>
								<span class="text-gray-300">
									<strong class="text-white">TECHNIQUE</strong>
									<span class="text-gray-400 ml-2">(auto-generated)</span>
								</span>
							</div>
						{/if}
						{#if sections.limitations?.included}
							<div class="flex items-center gap-2 text-sm">
								<span class="text-green-400 text-lg">✓</span>
								<span class="text-gray-300">
									<strong class="text-white">LIMITATIONS</strong>
									<span class="text-gray-400 ml-2">({sections.limitations.has_input_field ? 'manual input' : 'auto-generated'})</span>
								</span>
							</div>
						{/if}
						<div class="flex items-center gap-2 text-sm">
							<span class="text-green-400 text-lg">✓</span>
							<span class="text-gray-300">
								<strong class="text-white">FINDINGS</strong>
								<span class="text-gray-400 ml-2">({getStyleLabel(findingsConfig.content_style) || 'Not configured'})</span>
							</span>
						</div>
						<div class="flex items-center gap-2 text-sm">
							<span class="text-green-400 text-lg">✓</span>
							<span class="text-gray-300">
								<strong class="text-white">{impressionConfig.display_name || 'IMPRESSION'}</strong>
								<span class="text-gray-400 ml-2">(auto-generated)</span>
							</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Findings Config -->
		{#if findingsConfig.content_style}
			<div class="bg-gradient-to-br from-green-900/20 to-emerald-900/20 border border-green-500/30 rounded-lg p-5 shadow-lg gradient-card animate-fade-in" style="animation-delay: 0.1s">
				<div class="flex items-start gap-4">
					<div class="flex-shrink-0">
						<div class="w-10 h-10 rounded-lg bg-green-500/20 flex items-center justify-center transition-transform duration-200 hover:scale-110">
							<span class="text-xl">📝</span>
						</div>
					</div>
					<div class="flex-1">
						<h4 class="text-lg font-bold text-white mb-4">FINDINGS Configuration</h4>
						
						<div class="space-y-4">
							<!-- Content Style -->
							<div class="flex items-center gap-2">
								<span class="text-green-400 font-semibold text-xs">Content Style:</span>
								<span class="text-white font-medium text-sm">{getStyleLabel(findingsConfig.content_style)}</span>
							</div>

							{#if findingsConfig.content_style === 'structured_template'}
								<div class="p-2 bg-purple-900/20 border border-purple-500/30 rounded text-xs text-purple-300">
									ℹ️ Structured template preserves exact format with fill-in placeholders
								</div>
							{/if}

							<!-- Custom Instructions (if present) -->
							{#if findingsConfig.advanced?.instructions}
								<div class="flex items-start gap-2">
									<span class="text-green-400 font-semibold text-xs">Custom Instructions:</span>
									<span class="text-gray-300 text-xs italic">{findingsConfig.advanced.instructions}</span>
								</div>
							{/if}

							<!-- Template Content -->
							{#if findingsConfig.template_content}
								<div>
									<span class="text-green-400 font-semibold text-xs block mb-2">Template Content:</span>
									<div class="bg-black/40 border border-green-500/20 rounded-lg p-3 font-mono text-xs text-gray-300 overflow-x-auto">
										{#if !showFullFindingsTemplate}
											<div class="max-h-32 overflow-y-auto">
												{findingsConfig.template_content.substring(0, 300)}{findingsConfig.template_content.length > 300 ? '...' : ''}
											</div>
											{#if findingsConfig.template_content.length > 300}
												<button
													onclick={() => showFullFindingsTemplate = true}
													class="mt-2 text-green-400 hover:text-green-300 text-xs font-medium flex items-center gap-1 transition-colors"
												>
													<span>▼</span>
													<span>Show full template ({findingsConfig.template_content.length} characters)</span>
												</button>
											{/if}
										{:else}
											<div class="max-h-96 overflow-y-auto whitespace-pre-wrap">
												{findingsConfig.template_content}
											</div>
											<button
												onclick={() => showFullFindingsTemplate = false}
												class="mt-2 text-green-400 hover:text-green-300 text-xs font-medium flex items-center gap-1 transition-colors"
											>
												<span>▲</span>
												<span>Show less</span>
											</button>
										{/if}
									</div>
								</div>
							{/if}

							<!-- Writing Style Settings as Pills (only for non-structured templates) -->
							{#if findingsConfig.content_style !== 'structured_template' && findingsConfig.advanced}
								<div class="space-y-3">
									<div class="flex flex-wrap items-center gap-2">
										{#if findingsConfig.advanced?.writing_style}
											<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-xs font-medium">
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
												</svg>
												<span>Style: <span class="capitalize">{findingsConfig.advanced.writing_style.replace(/_/g, ' ')}</span></span>
											</span>
										{/if}
										{#if findingsConfig.advanced?.format}
											<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-blue-500/20 border border-blue-500/30 text-blue-300 text-xs font-medium">
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
												</svg>
												<span>Format: <span class="capitalize">{findingsConfig.advanced.format}</span></span>
											</span>
										{/if}
										{#if findingsConfig.advanced?.organization}
											<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-xs font-medium">
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
												</svg>
												<span>Organization: <span class="capitalize">{findingsConfig.advanced.organization.replace(/_/g, ' ')}</span></span>
											</span>
										{/if}
										{#if findingsConfig.advanced?.use_subsection_headers}
											<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-xs font-medium">
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14" />
												</svg>
												<span>With Headers</span>
											</span>
										{/if}
									</div>

									<div class="flex flex-wrap items-center gap-2">
										<!-- Old settings removed - now part of writing_style -->
									</div>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Impression Config -->
		<div class="bg-gradient-to-br from-orange-900/20 to-amber-900/20 border border-orange-500/30 rounded-lg p-5 shadow-lg gradient-card animate-fade-in" style="animation-delay: 0.15s">
			<div class="flex items-start gap-4">
				<div class="flex-shrink-0">
					<div class="w-10 h-10 rounded-lg bg-orange-500/20 flex items-center justify-center transition-transform duration-200 hover:scale-110">
						<span class="text-xl">💡</span>
					</div>
				</div>
				<div class="flex-1">
					<h4 class="text-lg font-bold text-white mb-4">IMPRESSION Configuration</h4>
					
					<div class="space-y-4">
						<!-- Display Name -->
						<div class="flex items-center gap-2">
							<span class="text-orange-400 font-semibold text-xs">Section Name:</span>
							<span class="text-white font-medium text-sm">{impressionConfig.display_name || 'IMPRESSION'}</span>
						</div>

						<!-- Instructions (if present) -->
						{#if impressionConfig.advanced?.instructions}
							<div class="flex items-start gap-2">
								<span class="text-orange-400 font-semibold text-xs">Custom Instructions:</span>
								<span class="text-gray-300 text-xs italic">{impressionConfig.advanced.instructions}</span>
							</div>
						{/if}

						<!-- Style Settings as Pills -->
						<div class="space-y-3">
							<!-- Main Style Settings -->
							<div class="flex flex-wrap items-center gap-2">
								{#if impressionConfig.advanced?.verbosity_style}
									<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-xs font-medium">
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
										</svg>
										<span>Verbosity: <span class="capitalize">{impressionConfig.advanced.verbosity_style}</span></span>
									</span>
								{/if}
								{#if impressionConfig.advanced?.format || impressionConfig.advanced?.impression_format}
									<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-blue-500/20 border border-blue-500/30 text-blue-300 text-xs font-medium">
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
										</svg>
										<span>Format: <span class="capitalize">{impressionConfig.advanced.format || impressionConfig.advanced.impression_format}</span></span>
									</span>
								{/if}
								{#if impressionConfig.advanced?.differential_approach || impressionConfig.advanced?.differential_style}
									<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-xs font-medium">
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
										</svg>
										<span>Differential: <span class="capitalize">{(impressionConfig.advanced.differential_approach || impressionConfig.advanced.differential_style || '').replace(/_/g, ' ')}</span></span>
									</span>
								{/if}
							</div>

							<!-- Recommendations (at bottom) -->
							{#if impressionConfig.advanced?.recommendations}
								{@const hasRecs = impressionConfig.advanced.recommendations.specialist_referral || impressionConfig.advanced.recommendations.further_workup || impressionConfig.advanced.recommendations.imaging_followup || impressionConfig.advanced.recommendations.clinical_correlation}
								{#if hasRecs}
									<div class="pt-2 border-t border-orange-500/20">
										<div class="flex flex-wrap items-center gap-2">
											<span class="text-orange-400 font-semibold text-xs">Recommendations include:</span>
											{#if impressionConfig.advanced.recommendations.specialist_referral}
												<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs font-medium">
													<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5.121 17.804A13.937 13.937 0 0112 16c2.5 0 4.847.655 6.879 1.804M15 10a3 3 0 11-6 0 3 3 0 016 0zm6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
													</svg>
													<span>Specialist Referral</span>
												</span>
											{/if}
											{#if impressionConfig.advanced.recommendations.further_workup}
												<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs font-medium">
													<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
													</svg>
													<span>Further Workup</span>
												</span>
											{/if}
											{#if impressionConfig.advanced.recommendations.imaging_followup}
												<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs font-medium">
													<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
													</svg>
													<span>Imaging Follow-up</span>
												</span>
									{/if}
											{#if impressionConfig.advanced.recommendations.clinical_correlation}
												<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs font-medium">
													<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
													</svg>
													<span>Clinical Correlation</span>
												</span>
									{/if}
								</div>
							</div>
						{/if}
							{/if}
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Analysis Result (if from reports) -->
		{#if analysisResult && analysisResult.detected_profile}
			<div class="bg-gradient-to-br from-indigo-900/20 to-purple-900/20 border border-indigo-500/30 rounded-lg p-5 shadow-lg gradient-card animate-fade-in" style="animation-delay: 0.2s">
				<div class="flex items-start gap-4">
					<div class="flex-shrink-0">
						<div class="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center transition-transform duration-200 hover:scale-110">
							<span class="text-xl">🔍</span>
						</div>
					</div>
					<div class="flex-1">
						<h4 class="text-lg font-bold text-white mb-3">Detected Profile</h4>
						<div class="space-y-2 text-sm">
							<div class="flex items-start gap-2">
								<span class="text-indigo-400 font-semibold min-w-[140px]">Template Style:</span>
								<span class="text-gray-300">{analysisResult.detected_profile.template_style}</span>
							</div>
							<div class="flex items-start gap-2">
								<span class="text-indigo-400 font-semibold min-w-[140px]">Verbosity:</span>
								<span class="text-gray-300">{analysisResult.detected_profile.verbosity}</span>
							</div>
							{#if analysisResult.detected_profile.organization}
								<div class="flex items-start gap-2">
									<span class="text-indigo-400 font-semibold min-w-[140px]">Organization:</span>
									<span class="text-gray-300">{analysisResult.detected_profile.organization}</span>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<!-- Next Button -->
	<div class="flex justify-end mt-8 max-w-4xl mx-auto">
		<button
			onclick={() => dispatch('next')}
			class="btn-primary px-8 py-3 text-lg font-semibold"
		>
			Continue to Save →
		</button>
	</div>
</div>
