<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	export let section = 'findings';
	export let advanced = {};
	export let findingsContentStyle = null; // 'structured_template', 'guided_template', 'normal_template', 'checklist', 'headers'
	export let impressionContentStyle = null; // 'structured_template', 'guided_template', 'normal_template', 'checklist', 'headers'

	let expandedExamples = {};

	// Track expanded state for subsections - default to all collapsed (false)
	let expandedSubsections = {
		// Findings subsections
		writing_style: false,
		measurements_descriptors: false,
		format_organization: false,
		custom_instructions_findings: false,
		// Impression subsections
		format_style: false,
		content_inclusion: false,
		recommendations: false,
		custom_instructions_impression: false
	};

	function handleFieldChange() {
		dispatch('fieldChange');
	}

	function toggleExample(key) {
		expandedExamples[key] = !expandedExamples[key];
	}

	function toggleSubsection(key) {
		expandedSubsections[key] = !expandedSubsections[key];
	}

	// Ensure defaults exist
	$: if (section === 'findings') {
		if (!advanced.writing_style) advanced.writing_style = 'standard';
		if (!advanced.measurement_style) advanced.measurement_style = 'inline';
		if (!advanced.negative_findings_style) advanced.negative_findings_style = 'grouped';
		if (!advanced.organization) advanced.organization = 'clinical_priority';
		if (!advanced.descriptor_density) advanced.descriptor_density = 'standard';
		if (!advanced.paragraph_grouping) advanced.paragraph_grouping = 'by_finding';
		if (!advanced.format) advanced.format = 'prose';
		if (advanced.use_subsection_headers === undefined) advanced.use_subsection_headers = false;
		if (!advanced.instructions) advanced.instructions = '';
	}

	$: if (section === 'impression') {
		if (!advanced.comparison_terminology) advanced.comparison_terminology = 'measured';
		if (!advanced.measurement_inclusion) advanced.measurement_inclusion = 'key_only';
		if (!advanced.incidental_handling) advanced.incidental_handling = 'action_threshold';
		if (!advanced.verbosity_style) advanced.verbosity_style = 'standard';
		if (!advanced.impression_format) advanced.impression_format = 'prose';
		if (!advanced.differential_style) advanced.differential_style = 'if_needed';
		if (!advanced.recommendations) {
			advanced.recommendations = {
				specialist_referral: true,
				further_workup: true,
				imaging_followup: false,
				clinical_correlation: false
			};
		}
		if (!advanced.instructions) advanced.instructions = '';
	}

	// Example content for FINDINGS
	const findingsExamples = {
		writing_style: {
			concise: 'Right upper lobe mass, 4cm, spiculated. Small pleural effusion present.',
			standard:
				'There is a 4cm spiculated mass in the right upper lobe. A small right pleural effusion is noted.',
			detailed:
				'A well-defined 4cm spiculated mass is identified in the right upper lobe, demonstrating heterogeneous enhancement. An associated small right pleural effusion is noted, measuring approximately 1cm in depth.'
		},
		measurement_style: {
			inline: 'There is a 4cm mass in the liver.',
			separate: 'There is a mass in the liver, measuring 4cm in maximum diameter.'
		},
		descriptor_density: {
			sparse: 'Mass in liver.',
			standard: '4cm well-defined mass in liver.',
			rich: 'Well-defined 4cm ovoid mass in segment 7 of the liver with smooth margins and homogeneous enhancement.'
		},
		negative_findings: {
			minimal: 'No mediastinal lymphadenopathy. No pleural effusion.',
			grouped: 'The liver, spleen and pancreas are unremarkable. No lymphadenopathy.',
			comprehensive:
				'No consolidation, effusion, or pneumothorax. Normal cardiac size and contour. No mediastinal lymphadenopathy. Liver normal. Spleen normal. Kidneys demonstrate no focal abnormality.'
		},
		paragraph_grouping: {
			continuous:
				'There is a 4cm mass in the right upper lobe. No mediastinal lymphadenopathy. No pleural effusion. Normal cardiac size and contour. Old fibrotic changes in the left lower lobe. Small right upper lobe bulla noted.',
			by_finding:
				'There is a 4cm spiculated mass in the right upper lobe, highly suspicious for malignancy. No mediastinal lymphadenopathy is identified.\n\nNo pleural effusion. Normal cardiac size and contour.\n\nOld fibrotic changes in the left lower lobe. Small right upper lobe bulla noted.',
			by_region:
				'Clear lung fields bilaterally. There is a 4cm spiculated mass in the right upper lobe. Old fibrotic changes in the left lower lobe. Small right upper lobe bulla.\n\nNo pleural effusion. Normal cardiac size and contour.\n\nNo mediastinal lymphadenopathy.'
		}
	};

	// Example content for IMPRESSION (UK English, natural sounding)
	const impressionExamples = {
		// Combined examples showing verbosity + format
		combined: {
			brief_prose: 'Right upper lobe lung mass.',
			brief_bullets: '• Right upper lobe lung mass',
			brief_numbered: '1. Right upper lobe lung mass',
			standard_prose:
				'There is a 4cm spiculated mass in the right upper lobe which is highly suspicious for primary lung malignancy. A small right-sided pleural effusion is also present.',
			standard_bullets:
				'• 4cm spiculated right upper lobe mass, highly suspicious for primary lung malignancy\n• Small right pleural effusion',
			standard_numbered:
				'1. 4cm spiculated right upper lobe mass, highly suspicious for primary lung malignancy\n2. Small right pleural effusion',
			detailed_prose:
				'There is a 4.2cm spiculated mass within the right upper lobe demonstrating irregular margins, heterogeneous enhancement and central areas of low attenuation, highly suspicious for primary bronchogenic carcinoma. Associated mediastinal lymphadenopathy is present, with an enlarged subcarinal node measuring 1.5cm in short axis. A small right pleural effusion is also noted.',
			detailed_bullets:
				'• 4.2cm spiculated right upper lobe mass with irregular margins and central low attenuation, highly suspicious for primary bronchogenic carcinoma\n• Associated mediastinal lymphadenopathy, largest subcarinal node 1.5cm in short axis\n• Small right pleural effusion noted',
			detailed_numbered:
				'1. 4.2cm spiculated right upper lobe mass with irregular margins and central low attenuation, highly suspicious for primary bronchogenic carcinoma\n2. Associated mediastinal lymphadenopathy, largest subcarinal node 1.5cm in short axis\n3. Small right pleural effusion noted'
		},
		differential_style: {
			none: 'There is a 4cm spiculated mass in the right upper lobe which is highly suspicious for primary lung malignancy.',
			if_needed:
				'There is a 4cm spiculated mass in the right upper lobe. Differential diagnosis includes primary lung carcinoma (most likely given the spiculated morphology), solitary metastasis, or organising pneumonia.',
			always_brief:
				'There is a 4cm spiculated mass in the right upper lobe. Differential diagnosis: primary bronchogenic carcinoma (most likely), solitary metastasis, or organising pneumonia.',
			always_detailed:
				'There is a 4cm spiculated mass in the right upper lobe demonstrating irregular margins and central low attenuation. Differential diagnosis: (1) Primary bronchogenic carcinoma - most likely given the spiculated morphology, size and presence of central necrosis. (2) Solitary metastasis - less likely in the absence of a known primary malignancy. (3) Organising pneumonia - possible but the morphological features favour malignancy.'
		},
		measurement_inclusion: {
			none: 'Spiculated right upper lobe mass, highly suspicious for primary lung malignancy.',
			key_only:
				'There is a 4cm spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy.',
			full: 'There is a 4.2 x 3.8 x 3.5cm spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy. The right pleural effusion measures 8mm in maximum depth.'
		},
		comparison_terminology: {
			simple: 'Right upper lobe mass, larger than previously.',
			measured: 'Right upper lobe mass, increased from 3.2cm to 4cm.',
			dated: 'Right upper lobe mass, increased from 3.2cm (15/01/2025) to 4cm on the current study.'
		},
		incidental_handling: {
			omit: 'There is a 4cm spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy.',
			action_threshold:
				'There is a 4cm spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy. Incidental note is made of a 6mm left thyroid nodule which may warrant ultrasound correlation.',
			comprehensive:
				'There is a 4cm spiculated mass in the right upper lobe, highly suspicious for primary lung malignancy. Incidental findings include a 6mm left thyroid nodule, mild degenerative changes in the thoracic spine, and a small hiatus hernia.'
		}
	};
</script>

<div class="space-y-4">
	{#if section === 'findings'}
		<!-- Section 1: Writing Style -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('writing_style')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">✍️</span>
					<h4>Writing Style</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.writing_style ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.writing_style}
				<div class="subsection">
					<label class="subsection-label">Detail Level</label>
					<div class="radio-pills-row">
						{#each [{ value: 'concise', label: 'Concise', icon: '📋', desc: 'Brief, essential details' }, { value: 'standard', label: 'Standard', icon: '📝', desc: 'Balanced NHS style' }, { value: 'detailed', label: 'Detailed', icon: '📚', desc: 'Comprehensive with precision' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.writing_style}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>
				</div>

				<!-- Example for Writing Style (hover to expand) -->
				{#if advanced.writing_style}
					<div class="example-preview hover-expand">
						<div class="example-header">
							<span class="example-icon">💡</span>
							<span class="example-label">EXAMPLE</span>
							<span class="example-badge">{advanced.writing_style}</span>
							<span class="hover-hint">Hover to view</span>
						</div>
						<div class="example-content">
							<p class="example-text">"{findingsExamples.writing_style[advanced.writing_style]}"</p>
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Section 2: Measurements & Descriptors -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('measurements_descriptors')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">📊</span>
					<h4>Measurements & Descriptors</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.measurements_descriptors ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.measurements_descriptors}
				<div class="subsection">
					<label class="subsection-label">Measurement Style</label>
					<div class="radio-pills-row">
						{#each [{ value: 'inline', label: 'Inline', icon: '📐', desc: '4cm mass' }, { value: 'separate', label: 'Separate', icon: '📏', desc: 'mass, measuring 4cm' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.measurement_style}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>

					<!-- Measurement Example (hover to expand) -->
					{#if advanced.measurement_style}
						<div class="example-preview hover-expand">
							<div class="example-header">
								<span class="example-icon">💡</span>
								<span class="example-label">EXAMPLE</span>
								<span class="hover-hint">Hover to view</span>
							</div>
							<div class="example-content">
								<p class="example-text">
									"{findingsExamples.measurement_style[advanced.measurement_style]}"
								</p>
							</div>
						</div>
					{/if}
				</div>

				<div class="subsection">
					<label class="subsection-label">Descriptor Density</label>
					<div class="radio-pills-row" style="grid-template-columns: repeat(3, 1fr);">
						{#each [{ value: 'sparse', label: 'Minimal Adjectives', icon: '▫️', desc: "Essential only (e.g., 'mass')" }, { value: 'standard', label: 'Balanced Adjectives', icon: '▪️', desc: "Key characteristics (e.g., 'well-defined mass')" }, { value: 'rich', label: 'Rich Adjectives', icon: '◾', desc: "Full detail (e.g., 'well-defined ovoid mass with smooth margins')" }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.descriptor_density}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>

					<!-- Descriptor Example (hover to expand) -->
					{#if advanced.descriptor_density}
						<div class="example-preview hover-expand">
							<div class="example-header">
								<span class="example-icon">💡</span>
								<span class="example-label">EXAMPLE</span>
								<span class="hover-hint">Hover to view</span>
							</div>
							<div class="example-content">
								<p class="example-text">
									"{findingsExamples.descriptor_density[advanced.descriptor_density]}"
								</p>
							</div>
						</div>
					{/if}

					<div class="recommendation-note" style="margin-top: 1rem;">
						<svg class="info-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
							/>
						</svg>
						<span class="hint-label">HINT</span>
						<span class="hint-content"
							>Controls adjectives/descriptors for positive findings only. Independent of sentence
							structure.</span
						>
					</div>
				</div>
			{/if}
		</div>

		<!-- Section 3: Format & Organization -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('format_organization')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">📄</span>
					<h4>Format & Organization</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.format_organization ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.format_organization}
				<div class="subsection">
					<label class="subsection-label">Report Format</label>
					<div class="radio-pills-row">
						{#each [{ value: 'prose', label: 'Prose', icon: '📄', desc: 'Flowing paragraphs' }, { value: 'bullets', label: 'Bullets', icon: '•', desc: 'Bullet point list' }, { value: 'mixed', label: 'Mixed', icon: '📝', desc: 'Prose + bullets' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.format}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>

					<!-- Subsection Headers Toggle -->
					<div class="mt-3">
						<label
							class="flex cursor-pointer items-center gap-3 rounded-lg border border-transparent bg-black/20 p-2 transition-all hover:border-purple-500/30 {advanced.use_subsection_headers
								? 'border-purple-500/50 bg-purple-900/10'
								: ''}"
						>
							<input
								type="checkbox"
								bind:checked={advanced.use_subsection_headers}
								onchange={handleFieldChange}
								class="h-4 w-4 cursor-pointer rounded border-gray-600 text-purple-500 focus:ring-purple-500 focus:ring-offset-0"
							/>
							<div class="flex-1">
								<div class="text-xs font-medium text-gray-300">Use Subsection Headers</div>
								<div class="text-xs text-gray-500">Add CHEST:, ABDOMEN: headers</div>
							</div>
						</label>
					</div>
				</div>

				<div class="subsection">
					<label class="subsection-label">Finding Organization</label>

					<!-- Finding Organization - Hero Layout -->
					<div class="org-layout">
						<!-- Hero Option: Clinical Priority -->
						<div class="org-hero">
							<label
								class="radio-pill-hero {advanced.organization === 'clinical_priority'
									? 'selected'
									: ''}"
							>
								<input
									type="radio"
									bind:group={advanced.organization}
									value="clinical_priority"
									onchange={handleFieldChange}
								/>
								<div class="hero-content">
									<div class="hero-icon-wrapper">
										<span class="hero-icon">⚡</span>
									</div>
									<div class="hero-text">
										<div class="hero-header">
											<span class="hero-label">Clinical Priority</span>
											<span class="hero-badge">Recommended</span>
										</div>
										<span class="hero-desc"
											>Intelligent ordering based on clinical significance + regional context. Puts
											the most critical findings first.</span
										>
									</div>
									<div class="hero-check">
										<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"
											><path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M5 13l4 4L19 7"
											></path></svg
										>
									</div>
								</div>
							</label>
						</div>

						<!-- Secondary Options: Grid -->
						<div class="org-secondary-grid">
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.organization}
									value="systematic"
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">📋</span>
									<div class="pill-text">
										<span class="pill-label">Systematic Review</span>
										<span class="pill-desc">Head-to-toe anatomical order</span>
									</div>
								</div>
							</label>

							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.organization}
									value="template_order"
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">📐</span>
									<div class="pill-text">
										<span class="pill-label">Template Order</span>
										<span class="pill-desc">Follow template structure</span>
									</div>
								</div>
							</label>
						</div>
					</div>
				</div>

				<div class="subsection">
					<label class="subsection-label">Negative Findings</label>
					<div class="radio-pills-row">
						{#each [{ value: 'minimal', label: 'Pertinent Only', icon: '⚡', desc: 'Only clinically relevant negatives' }, { value: 'grouped', label: 'Grouped', icon: '📦', desc: 'Efficient grouping of normals' }, { value: 'comprehensive', label: 'Comprehensive', icon: '📋', desc: 'All systems documented' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.negative_findings_style}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>

					<!-- Negative Findings Example (hover to expand) -->
					{#if advanced.negative_findings_style}
						<div class="example-preview hover-expand">
							<div class="example-header">
								<span class="example-icon">💡</span>
								<span class="example-label">EXAMPLE</span>
								<span class="hover-hint">Hover to view</span>
							</div>
							<div class="example-content">
								<p class="example-text">
									"{findingsExamples.negative_findings[advanced.negative_findings_style]}"
								</p>
							</div>
						</div>
					{/if}
				</div>

				<div class="subsection">
					<label class="subsection-label">Paragraph Grouping</label>
					<div class="radio-pills-row">
						{#each [{ value: 'continuous', label: 'Continuous', icon: '━', desc: 'Single flowing paragraph(s)' }, { value: 'by_finding', label: 'By Finding', icon: '•', desc: 'Paragraph per finding/group' }, { value: 'by_region', label: 'By Region', icon: '🗺️', desc: 'Paragraph per anatomical region' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.paragraph_grouping}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>

					<!-- Paragraph Grouping Example (hover to expand) -->
					{#if advanced.paragraph_grouping}
						<div class="example-preview hover-expand">
							<div class="example-header">
								<span class="example-icon">💡</span>
								<span class="example-label">EXAMPLE</span>
								<span class="hover-hint">Hover to view</span>
							</div>
							<div class="example-content">
								<p class="example-text" style="white-space: pre-line;">
									"{findingsExamples.paragraph_grouping[advanced.paragraph_grouping]}"
								</p>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Section 4: Fine-Tuning Instructions -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('custom_instructions_findings')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">🎯</span>
					<h4>Fine-Tuning Instructions</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.custom_instructions_findings ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.custom_instructions_findings}
				<textarea
					bind:value={advanced.instructions}
					oninput={handleFieldChange}
					rows="3"
					placeholder="e.g., Always measure lymph node short axis. Comment on pleural surfaces even if normal..."
					class="instructions-textarea"
					onkeydown={(e) => {
						// Allow Enter to create new lines in textarea
						if (e.key === 'Enter') {
							e.stopPropagation();
						}
					}}
				></textarea>

				<!-- Fine-Tuning Instructions Hint Box -->
				<div class="recommendation-note" style="margin-top: 1rem;">
					<svg class="info-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
					<span class="hint-label">HINT</span>
					<div class="hint-content" style="display: flex; flex-direction: column; gap: 0.5rem;">
						<span
							>Fine-tune how findings are described and structured. Write natural language instructions for anatomical descriptions, measurement reporting, or specific anatomical commentary not covered by settings above.</span
						>
						<span
							><strong>Examples:</strong> "Always measure lymph node short axis", "Comment on pleural surfaces even if normal", "Use WHO criteria for tumour response assessment", or "Include vessel relationship for masses >2cm".
						</span>
					</div>
				</div>
			{/if}
		</div>
	{:else}
		<!-- IMPRESSION Controls -->

		<!-- Section 1: Format & Style -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('format_style')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">✨</span>
					<h4>Format & Style</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.format_style ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.format_style}
				<div class="subsection">
					<label class="subsection-label">Summary Length</label>
					<div class="radio-pills-row">
						{#each [{ value: 'brief', label: 'Brief', icon: '⚡', desc: '1-2 lines, essential only' }, { value: 'standard', label: 'Standard', icon: '📝', desc: '2-3 lines, balanced' }, { value: 'detailed', label: 'Detailed', icon: '📚', desc: '3-4 lines, comprehensive' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.verbosity_style}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>
				</div>

				<div class="subsection">
					<label class="subsection-label">Presentation Format</label>
					<div class="radio-pills-row">
						{#each [{ value: 'prose', label: 'Prose', icon: '📄', desc: 'Flowing sentences' }, { value: 'bullets', label: 'Bullets', icon: '•', desc: 'Bullet points' }, { value: 'numbered', label: 'Numbered', icon: '1.', desc: 'Numbered list' }] as option}
							<label class="radio-pill-wide">
								<input
									type="radio"
									bind:group={advanced.impression_format}
									value={option.value}
									onchange={handleFieldChange}
								/>
								<div class="pill-content">
									<span class="pill-icon">{option.icon}</span>
									<div class="pill-text">
										<span class="pill-label">{option.label}</span>
										<span class="pill-desc">{option.desc}</span>
									</div>
								</div>
							</label>
						{/each}
					</div>
				</div>

				<!-- Example for Format & Style (hover to expand) -->
				{#if advanced.verbosity_style && advanced.impression_format}
					<div class="example-preview hover-expand">
						<div class="example-header">
							<span class="example-icon">💡</span>
							<span class="example-label">EXAMPLE</span>
							<span class="example-badge"
								>{advanced.verbosity_style} + {advanced.impression_format}</span
							>
							<span class="hover-hint">Hover to view</span>
						</div>
						<div class="example-content">
							<pre class="example-text whitespace-pre-line">{impressionExamples.combined[
									`${advanced.verbosity_style}_${advanced.impression_format}`
								]}</pre>
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Section 2: Content Inclusion -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('content_inclusion')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">📋</span>
					<h4>Content Inclusion</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.content_inclusion ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.content_inclusion}
				<div class="content-cards-grid">
					<!-- Differential -->
					<div class="content-card hover-expand-mini">
						<div class="content-card-header">
							<span class="icon">🧠</span>
							<span class="label">Differential Diagnosis</span>
						</div>
						<div class="radio-compact">
							{#each [{ value: 'none', label: 'Never' }, { value: 'if_needed', label: 'Only if Uncertain' }, { value: 'always_brief', label: 'Always Brief' }, { value: 'always_detailed', label: 'Always Detailed' }] as option}
								<label class="radio-pill">
									<input
										type="radio"
										bind:group={advanced.differential_style}
										value={option.value}
										onchange={handleFieldChange}
									/>
									<span>{option.label}</span>
								</label>
							{/each}
						</div>

						<!-- Differential Example -->
						{#if advanced.differential_style}
							<div class="content-card-example">
								<div class="example-mini-label">Example</div>
								<div class="example-mini-text">
									{impressionExamples.differential_style[advanced.differential_style]}
								</div>
							</div>
						{/if}
					</div>

					<!-- Measurements -->
					<div class="content-card hover-expand-mini">
						<div class="content-card-header">
							<span class="icon">📐</span>
							<span class="label">Measurements</span>
						</div>
						<div class="radio-compact">
							{#each [{ value: 'none', label: 'None' }, { value: 'key_only', label: 'Key Only' }, { value: 'full', label: 'All' }] as option}
								<label class="radio-pill">
									<input
										type="radio"
										bind:group={advanced.measurement_inclusion}
										value={option.value}
										onchange={handleFieldChange}
									/>
									<span>{option.label}</span>
								</label>
							{/each}
						</div>

						{#if advanced.measurement_inclusion}
							<div class="content-card-example">
								<div class="example-mini-label">Example</div>
								<div class="example-mini-text">
									{impressionExamples.measurement_inclusion[advanced.measurement_inclusion]}
								</div>
							</div>
						{/if}
					</div>

					<!-- Incidentals -->
					<div class="content-card hover-expand-mini">
						<div class="content-card-header">
							<span class="icon">🔍</span>
							<span class="label">Incidental Findings</span>
						</div>
						<div class="radio-compact">
							{#each [{ value: 'omit', label: 'Omit' }, { value: 'action_threshold', label: 'If Actionable' }, { value: 'comprehensive', label: 'All' }] as option}
								<label class="radio-pill">
									<input
										type="radio"
										bind:group={advanced.incidental_handling}
										value={option.value}
										onchange={handleFieldChange}
									/>
									<span>{option.label}</span>
								</label>
							{/each}
						</div>

						{#if advanced.incidental_handling}
							<div class="content-card-example">
								<div class="example-mini-label">Example</div>
								<div class="example-mini-text">
									{impressionExamples.incidental_handling[advanced.incidental_handling]}
								</div>
							</div>
						{/if}
					</div>

					<!-- Comparison -->
					<div class="content-card hover-expand-mini">
						<div class="content-card-header">
							<span class="icon">📅</span>
							<span class="label">Comparison Detail</span>
						</div>
						<div class="radio-compact">
							{#each [{ value: 'simple', label: 'Simple' }, { value: 'measured', label: 'Measured' }, { value: 'dated', label: 'Dated' }] as option}
								<label class="radio-pill">
									<input
										type="radio"
										bind:group={advanced.comparison_terminology}
										value={option.value}
										onchange={handleFieldChange}
									/>
									<span>{option.label}</span>
								</label>
							{/each}
						</div>

						{#if advanced.comparison_terminology}
							<div class="content-card-example">
								<div class="example-mini-label">Example</div>
								<div class="example-mini-text">
									{impressionExamples.comparison_terminology[advanced.comparison_terminology]}
								</div>
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>

		<!-- Section 3: Recommendations (Multi-checkbox) -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('recommendations')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">💡</span>
					<h4>Recommendations</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.recommendations ? 'expanded' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.recommendations}
				<p class="section-description">
					Select which types of recommendations to consider when appropriate
				</p>

				<div class="recommendations-list">
					<!-- Specialist Referral -->
					<label
						class="recommendation-item"
						class:checked={advanced.recommendations?.specialist_referral}
					>
						<input
							type="checkbox"
							bind:checked={advanced.recommendations.specialist_referral}
							onchange={handleFieldChange}
						/>
						<div class="rec-content">
							<div class="rec-header">
								<span class="rec-icon">👨‍⚕️</span>
								<span class="rec-title">Specialist Referral</span>
								<span class="rec-checkmark">✓</span>
							</div>
							<p class="rec-description">Appropriate referral with urgency when needed</p>
						</div>
					</label>

					<!-- Further Work-up -->
					<label
						class="recommendation-item"
						class:checked={advanced.recommendations?.further_workup}
					>
						<input
							type="checkbox"
							bind:checked={advanced.recommendations.further_workup}
							onchange={handleFieldChange}
						/>
						<div class="rec-content">
							<div class="rec-header">
								<span class="rec-icon">🔬</span>
								<span class="rec-title">Further Work-up</span>
								<span class="rec-checkmark">✓</span>
							</div>
							<p class="rec-description">Additional imaging, biopsies, procedures</p>
						</div>
					</label>

					<!-- Imaging Follow-up -->
					<label
						class="recommendation-item"
						class:checked={advanced.recommendations?.imaging_followup}
					>
						<input
							type="checkbox"
							bind:checked={advanced.recommendations.imaging_followup}
							onchange={handleFieldChange}
						/>
						<div class="rec-content">
							<div class="rec-header">
								<span class="rec-icon">📷</span>
								<span class="rec-title">Imaging Follow-up</span>
								<span class="rec-checkmark">✓</span>
							</div>
							<p class="rec-description">Follow-up scans with timeframes (e.g., CT in 3 months)</p>
						</div>
					</label>

					<!-- Clinical Correlation -->
					<label
						class="recommendation-item"
						class:checked={advanced.recommendations?.clinical_correlation}
					>
						<input
							type="checkbox"
							bind:checked={advanced.recommendations.clinical_correlation}
							onchange={handleFieldChange}
						/>
						<div class="rec-content">
							<div class="rec-header">
								<span class="rec-icon">🩺</span>
								<span class="rec-title">Clinical Correlation</span>
								<span class="rec-checkmark">✓</span>
							</div>
							<p class="rec-description">Specific tests/assessments (e.g., correlate with LFTs)</p>
						</div>
					</label>
				</div>

				<div class="recommendation-note">
					<svg class="info-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
					<span class="hint-label">HINT</span>
					<span class="hint-content"
						>Only included when clinically appropriate for the findings</span
					>
				</div>
			{/if}
		</div>

		<!-- Fine-Tuning Instructions -->
		<div class="config-section">
			<button
				type="button"
				onclick={() => toggleSubsection('custom_instructions_impression')}
				class="section-header-collapsible"
			>
				<div class="section-header">
					<span class="icon">🎯</span>
					<h4>Fine-Tuning Instructions</h4>
				</div>
				<svg
					class="chevron-icon {expandedSubsections.custom_instructions_impression
						? 'expanded'
						: ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M19 9l-7 7-7-7"
					/>
				</svg>
			</button>

			{#if expandedSubsections.custom_instructions_impression}
				<textarea
					bind:value={advanced.instructions}
					oninput={handleFieldChange}
					rows="3"
					placeholder="e.g., Lead with most clinically significant finding. Recommend follow-up for nodules >6mm..."
					class="instructions-textarea"
					onkeydown={(e) => {
						// Allow Enter to create new lines in textarea
						if (e.key === 'Enter') {
							e.stopPropagation();
						}
					}}
				></textarea>

				<!-- Fine-Tuning Instructions Hint Box -->
				<div class="recommendation-note" style="margin-top: 1rem;">
					<svg class="info-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
					<span class="hint-label">HINT</span>
					<div class="hint-content" style="display: flex; flex-direction: column; gap: 0.5rem;">
						<span
							>Fine-tune how clinical conclusions are presented. Write natural language instructions for synthesis, recommendations, or conclusion prioritization not covered by settings above.</span
						>
						<span
							><strong>Examples:</strong> "Lead with most clinically significant finding", "Recommend follow-up for incidental nodules >6mm", "Include actionable next steps when abnormalities detected", or "Prioritise oncologic staging in known cancer patients".
						</span>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	/* Impression section styles */
	.config-section {
		margin-bottom: 1.5rem;
		padding: 1.5rem;
		background: linear-gradient(to br, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.04));
		border: 1px solid rgba(139, 92, 246, 0.2);
		border-radius: 12px;
	}

	.section-header-collapsible {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		margin-bottom: 1.25rem;
		transition: opacity 0.2s;
	}

	.section-header-collapsible:hover {
		opacity: 0.8;
	}

	.section-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex: 1;
	}

	.chevron-icon {
		width: 1.25rem;
		height: 1.25rem;
		color: rgba(255, 255, 255, 0.6);
		transition: transform 0.3s ease;
		flex-shrink: 0;
	}

	.chevron-icon.expanded {
		transform: rotate(180deg);
	}

	.section-header h4 {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: white;
	}

	.section-header .icon {
		font-size: 1.25rem;
	}

	.header-hint {
		margin-left: auto;
		font-size: 0.75rem;
		color: rgba(255, 255, 255, 0.5);
		font-weight: 400;
	}

	.subsection {
		margin-bottom: 1.5rem;
		padding: 1.25rem;
		background: rgba(0, 0, 0, 0.15);
		border: 1px solid rgba(139, 92, 246, 0.2);
		border-radius: 8px;
		transition: all 0.2s;
	}

	.subsection:hover {
		background: rgba(0, 0, 0, 0.2);
		border-color: rgba(139, 92, 246, 0.3);
	}

	.subsection:last-child {
		margin-bottom: 0;
	}

	.subsection-label {
		display: block;
		font-size: 0.875rem;
		font-weight: 600;
		color: rgba(255, 255, 255, 0.9);
		margin-bottom: 0.75rem;
	}

	.section-description {
		font-size: 0.875rem;
		color: rgba(255, 255, 255, 0.6);
		margin-bottom: 1rem;
	}

	/* Format pills (wider) */
	.radio-pills-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.75rem;
		align-items: stretch;
	}

	.radio-pill-wide {
		display: flex;
		height: 100%;
	}

	.radio-pill-wide input {
		display: none;
	}

	.radio-pill-wide .pill-content {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: rgba(0, 0, 0, 0.2);
		border: 2px solid rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		cursor: pointer;
		transition: all 0.2s;
		width: 100%;
		height: 100%;
	}

	.radio-pill-wide:hover .pill-content {
		background: rgba(255, 255, 255, 0.05);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.radio-pill-wide input:checked + .pill-content {
		background: rgba(139, 92, 246, 0.2);
		border-color: rgb(139, 92, 246);
	}

	.pill-icon {
		font-size: 1.25rem;
	}

	.pill-text {
		display: flex;
		flex-direction: column;
	}

	.pill-label {
		font-size: 0.875rem;
		font-weight: 500;
		color: white;
	}

	.pill-desc {
		font-size: 0.75rem;
		color: rgba(255, 255, 255, 0.6);
	}

	/* Organization grouping (2x2 grid) */
	.org-group {
		margin-bottom: 1.5rem;
	}

	.org-group-header {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.org-group-label {
		font-weight: 600;
		font-size: 0.875rem;
		color: rgba(255, 255, 255, 0.9);
	}

	.org-group-desc {
		font-size: 0.75rem;
		color: rgba(255, 255, 255, 0.5);
	}

	.org-grid-2x2 {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}

	.org-divider {
		height: 1px;
		background: rgba(255, 255, 255, 0.1);
		margin: 1.5rem 0;
		opacity: 0.3;
	}

	@media (max-width: 768px) {
		.org-grid-2x2 {
			grid-template-columns: 1fr;
		}
	}

	/* Content inclusion cards */
	.content-cards-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}

	.content-card {
		background: rgba(0, 0, 0, 0.2);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		padding: 1rem;
	}

	.content-card-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		padding-bottom: 0.75rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
	}

	.content-card-header .icon {
		font-size: 1.125rem;
	}

	.content-card-header .label {
		font-size: 0.875rem;
		font-weight: 600;
		color: white;
	}

	.radio-compact {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.radio-pill {
		cursor: pointer;
	}

	.radio-pill input {
		display: none;
	}

	.radio-pill span {
		display: block;
		padding: 0.4rem 0.75rem;
		font-size: 0.8125rem;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 6px;
		color: rgba(255, 255, 255, 0.7);
		transition: all 0.2s;
		white-space: nowrap;
	}

	.radio-pill:hover span {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.radio-pill input:checked + span {
		background: rgba(139, 92, 246, 0.3);
		border-color: rgb(139, 92, 246);
		color: white;
		font-weight: 500;
	}

	/* Recommendations list */
	.recommendations-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}

	.recommendation-item {
		position: relative;
		cursor: pointer;
		display: block;
	}

	.recommendation-item input {
		position: absolute;
		opacity: 0;
	}

	.rec-content {
		padding: 0.875rem 1rem;
		background: rgba(0, 0, 0, 0.2);
		border: 2px solid rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		transition: all 0.2s;
	}

	.recommendation-item:hover .rec-content {
		background: rgba(255, 255, 255, 0.05);
		border-color: rgba(139, 92, 246, 0.3);
	}

	.recommendation-item.checked .rec-content {
		background: rgba(139, 92, 246, 0.15);
		border-color: rgb(139, 92, 246);
	}

	.rec-header {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		margin-bottom: 0.375rem;
	}

	.rec-icon {
		font-size: 1.125rem;
	}

	.rec-title {
		font-size: 0.875rem;
		font-weight: 600;
		color: white;
		flex: 1;
	}

	.rec-checkmark {
		font-size: 0.875rem;
		color: rgb(139, 92, 246);
		opacity: 0;
		transition: opacity 0.2s;
		font-weight: 600;
	}

	.recommendation-item.checked .rec-checkmark {
		opacity: 1;
	}

	.rec-description {
		font-size: 0.8125rem;
		color: rgba(255, 255, 255, 0.6);
		margin: 0;
		line-height: 1.4;
		padding-left: 1.75rem;
	}

	.recommendation-note {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		background: rgba(59, 130, 246, 0.1);
		border: 1px solid rgba(59, 130, 246, 0.2);
		border-radius: 8px;
		font-size: 0.8125rem;
		color: rgba(147, 197, 253, 0.9);
		cursor: pointer;
		transition: all 0.2s ease;
		min-height: 2.5rem;
		max-height: 2.5rem;
		overflow: hidden;
	}

	.recommendation-note:hover {
		background: rgba(59, 130, 246, 0.15);
		border-color: rgba(59, 130, 246, 0.3);
		align-items: start;
		min-height: auto;
		max-height: 500px;
		transition: all 0.3s ease;
	}

	.recommendation-note .info-icon {
		width: 1rem;
		height: 1rem;
		flex-shrink: 0;
		margin-top: 0.125rem;
		transition: transform 0.2s ease;
	}

	.recommendation-note:hover .info-icon {
		transform: scale(1.1);
	}

	/* Hint label - visible by default */
	.recommendation-note .hint-label {
		font-weight: 600;
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		opacity: 1;
		transition: opacity 0.2s ease;
		flex-shrink: 0;
		white-space: nowrap;
	}

	/* Hint content - hidden by default but in normal flow */
	.recommendation-note .hint-content {
		width: 0;
		overflow: hidden;
		opacity: 0;
		transition:
			width 0.3s ease,
			opacity 0.3s ease;
		flex: 1;
		min-width: 0;
		max-height: 0;
	}

	/* Expanded state on hover */
	.recommendation-note:hover .hint-label {
		opacity: 0;
		width: 0;
		overflow: hidden;
		transition: all 0.2s ease;
		margin: 0;
		padding: 0;
		max-height: 0;
	}

	.recommendation-note:hover .hint-content {
		width: auto;
		opacity: 1;
		transition:
			width 0.3s ease,
			opacity 0.3s ease,
			max-height 0.3s ease;
		min-width: 0;
		max-height: none;
	}

	.instructions-textarea {
		width: 100%;
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.2);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		color: white;
		font-size: 0.875rem;
		resize: vertical;
	}

	.instructions-textarea:focus {
		outline: none;
		border-color: rgba(139, 92, 246, 0.5);
	}

	.instructions-textarea::placeholder {
		color: rgba(255, 255, 255, 0.3);
	}

	/* Example displays with hover-expand */
	.example-preview {
		margin-top: 1rem;
		padding: 1rem;
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid rgba(139, 92, 246, 0.3);
		border-radius: 8px;
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.example-preview:hover {
		background: rgba(0, 0, 0, 0.4);
		border-color: rgba(139, 92, 246, 0.5);
	}

	/* Collapsed state by default */
	.example-preview.hover-expand .example-content {
		max-height: 0;
		overflow: hidden;
		opacity: 0;
		padding: 0;
		margin-top: 0;
		transition: all 0.3s ease;
	}

	/* Expanded state on hover */
	.example-preview.hover-expand:hover .example-content {
		max-height: 500px;
		opacity: 1;
		padding: 0.75rem;
		margin-top: 0.75rem;
		transition: all 0.3s ease;
	}

	.example-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	/* Only show border when expanded */
	.example-preview.hover-expand:hover .example-header {
		padding-bottom: 0.5rem;
		border-bottom: 1px solid rgba(139, 92, 246, 0.2);
		margin-bottom: 0;
	}

	.example-icon {
		font-size: 1rem;
	}

	.example-label {
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: rgba(167, 139, 250, 0.9);
	}

	.example-badge {
		margin-left: auto;
		padding: 0.25rem 0.5rem;
		background: rgba(139, 92, 246, 0.2);
		border-radius: 4px;
		font-size: 0.6875rem;
		color: rgba(196, 181, 253, 0.9);
		font-weight: 500;
	}

	.hover-hint {
		font-size: 0.6875rem;
		color: rgba(156, 163, 175, 0.7);
		font-style: italic;
		margin-left: 0.5rem;
	}

	.example-preview.hover-expand:hover .hover-hint {
		opacity: 0;
	}

	.example-content {
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.2);
		border-radius: 6px;
	}

	.example-text {
		margin: 0;
		font-size: 0.8125rem;
		line-height: 1.6;
		color: rgba(229, 231, 235, 0.95);
		font-style: italic;
	}

	/* Mini examples in content cards with hover-expand */
	.hover-expand-mini .content-card-example {
		max-height: 0;
		overflow: hidden;
		opacity: 0;
		padding: 0;
		margin-top: 0;
		transition: all 0.3s ease;
	}

	.hover-expand-mini:hover .content-card-example {
		max-height: 300px;
		opacity: 1;
		margin-top: 0.75rem;
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.25);
		border-radius: 6px;
		border: 1px solid rgba(255, 255, 255, 0.05);
		transition: all 0.3s ease;
	}

	.hover-expand-mini {
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.hover-expand-mini:hover {
		background: rgba(0, 0, 0, 0.15);
	}

	.example-mini-label {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: rgba(167, 139, 250, 0.8);
		margin-bottom: 0.5rem;
	}

	.hover-hint-mini {
		font-size: 0.6875rem;
		color: rgba(156, 163, 175, 0.6);
		font-style: italic;
		font-weight: 400;
		text-transform: none;
		letter-spacing: normal;
	}

	.example-mini-text {
		font-size: 0.75rem;
		line-height: 1.5;
		color: rgba(209, 213, 219, 0.9);
		font-style: italic;
	}

	@media (max-width: 768px) {
		.content-cards-grid {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 768px) {
		.content-cards-grid {
			grid-template-columns: 1fr;
		}
	}

	/* Hero Option Styles */
	.org-layout {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.radio-pill-hero {
		display: block;
		cursor: pointer;
	}

	.radio-pill-hero input {
		display: none;
	}

	.radio-pill-hero .hero-content {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 1.25rem;
		background: rgba(0, 0, 0, 0.2);
		border: 2px solid rgba(255, 255, 255, 0.1);
		border-radius: 12px;
		transition: all 0.2s;
	}

	.radio-pill-hero:hover .hero-content {
		background: rgba(255, 255, 255, 0.05);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.radio-pill-hero input:checked + .hero-content {
		background: rgba(139, 92, 246, 0.15);
		border-color: rgb(139, 92, 246);
	}

	.hero-icon-wrapper {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 3rem;
		height: 3rem;
		background: rgba(139, 92, 246, 0.1);
		border-radius: 50%;
		font-size: 1.5rem;
	}

	.radio-pill-hero input:checked + .hero-content .hero-icon-wrapper {
		background: rgb(139, 92, 246);
		color: white;
	}

	.hero-text {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.hero-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.hero-label {
		font-size: 1rem;
		font-weight: 600;
		color: white;
	}

	.hero-badge {
		font-size: 0.625rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 700;
		padding: 0.15rem 0.5rem;
		background: rgb(139, 92, 246);
		color: white;
		border-radius: 99px;
	}

	.hero-desc {
		font-size: 0.8125rem;
		color: rgba(255, 255, 255, 0.6);
		line-height: 1.4;
	}

	.hero-check {
		opacity: 0;
		color: rgb(139, 92, 246);
		transform: scale(0.8);
		transition: all 0.2s;
	}

	.radio-pill-hero input:checked + .hero-content .hero-check {
		opacity: 1;
		transform: scale(1);
	}

	.org-secondary-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}
</style>
