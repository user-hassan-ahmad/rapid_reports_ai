<script>
	import { createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	export let section = 'findings';
	export let advanced = {};

	let hoveredExample = null;

	// Ensure defaults
	$: if (section === 'findings') {
		if (!advanced.writing_style) advanced.writing_style = 'standard';
		if (!advanced.organization) advanced.organization = 'clinical_priority';
		if (!advanced.format) advanced.format = 'prose';
		if (advanced.use_subsection_headers === undefined) advanced.use_subsection_headers = false;
		if (!advanced.instructions) advanced.instructions = '';
	}

	$: if (section === 'impression') {
		if (!advanced.verbosity_style) advanced.verbosity_style = 'standard';
		if (!advanced.format) advanced.format = 'prose';
		if (!advanced.differential_approach) {
			if (advanced.differential_style) {
				if (advanced.differential_style === 'none') {
					advanced.differential_approach = 'none';
				} else if (advanced.differential_style === 'if_needed') {
					advanced.differential_approach = 'if_needed';
				} else {
					advanced.differential_approach = 'always';
				}
			} else {
				advanced.differential_approach = 'if_needed';
			}
		}
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

	const examples = {
		findings: {
			concise: {
				text: "Large filling defects in the right pulmonary artery extending to segmental branches. Additional defect in the left lower lobe. Right ventricle dilated, RV/LV ratio 1.3. Mild IVC reflux. Small right effusion.",
				desc: "Essentials only • Strip non-clinical words • Consultant-to-consultant style"
			},
			standard: {
				text: "Large filling defects are present in the right main pulmonary artery, extending into segmental branches. An additional filling defect is identified in the left lower lobe. The right ventricle is moderately dilated with an RV/LV ratio of 1.3. Mild IVC reflux suggests right heart strain. A small right pleural effusion is present.",
				desc: "Clinically relevant details • Balanced readability • Natural flow"
			},
			detailed: {
				text: "Multiple large filling defects are identified within the right main pulmonary artery, extending distally into the segmental branches of the right upper and lower lobes. An additional filling defect is present in the posterior basal segmental artery of the left lower lobe. The right ventricle demonstrates moderate dilatation with an RV/LV ratio of 1.3. Associated mild reflux of contrast material into the IVC and hepatic veins is observed. A small right-sided pleural effusion is noted.",
				desc: "Complete characterization • Full precision • Rich descriptive language"
			}
		},
		impression: {
			brief: {
				text: "Bilateral pulmonary emboli with right heart strain.",
				desc: "Essential diagnosis only • Corridor conversation style"
			},
			standard: {
				text: "Bilateral pulmonary emboli are present with right heart strain. A small right pleural effusion and right lower lobe infarction are noted.",
				desc: "Clinically relevant findings • Balanced professional summary • Actionable incidentals only"
			},
			detailed: {
				text: "Bilateral pulmonary emboli are present with RV dilatation (RV/LV 1.3) and contrast reflux. Additional findings include a small right pleural effusion and wedge-shaped consolidation in the RLL consistent with infarction.",
				desc: "Comprehensive documentation • Full characterization • Actionable incidentals only"
			}
		}
	};

	function handleFieldChange() {
		dispatch('fieldChange');
	}
</script>

<div class="space-y-6">
	{#if section === 'findings'}
		<!-- Writing Style -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">✍️</span>
				<span class="label-text">Writing Style</span>
			</div>
			
			<div class="option-grid">
				{#each [
					{ value: 'concise', icon: '⚡', label: 'Concise', desc: 'Brief, essential details only' },
					{ value: 'standard', icon: '⚖️', label: 'Standard', desc: 'Balanced NHS style' },
					{ value: 'detailed', icon: '📚', label: 'Detailed', desc: 'Comprehensive with precision' }
				] as opt}
					<label class="option-card {advanced.writing_style === opt.value ? 'selected' : ''}">
						<input type="radio" bind:group={advanced.writing_style} value={opt.value} onchange={handleFieldChange} />
						<div class="option-icon">{opt.icon}</div>
						<div class="option-content">
							<div class="option-title">{opt.label}</div>
							<div class="option-desc">{opt.desc}</div>
						</div>
					</label>
				{/each}
			</div>

			<div 
				class="example-container"
				onmouseenter={() => hoveredExample = 'findings-writing'}
				onmouseleave={() => hoveredExample = null}
			>
				<div class="example-header">
					<span class="example-icon">💡</span>
					<span class="example-label">EXAMPLE</span>
					<span class="example-hint">{hoveredExample === 'findings-writing' ? advanced.writing_style : 'Hover to view'}</span>
				</div>
				{#if hoveredExample === 'findings-writing'}
					<p class="example-desc">{examples.findings[advanced.writing_style].desc}</p>
					<div class="example-text">{examples.findings[advanced.writing_style].text}</div>
				{/if}
			</div>
		</div>

		<!-- Organization -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">📋</span>
				<span class="label-text">Finding Sequence</span>
			</div>
			
			<select bind:value={advanced.organization} onchange={handleFieldChange} class="select-input">
				<option value="clinical_priority">Clinical Priority (lead with critical)</option>
				<option value="template_order">Template Order (exact structure)</option>
			</select>
		</div>

		<!-- Format -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">📝</span>
				<span class="label-text">Format</span>
			</div>
			
			<div class="toggle-group">
				{#each [
					{ value: 'prose', icon: '📄', label: 'Prose' },
					{ value: 'bullets', icon: '•', label: 'Bullets' }
				] as opt}
					<label class="toggle-option {advanced.format === opt.value ? 'selected' : ''}">
						<input type="radio" bind:group={advanced.format} value={opt.value} onchange={handleFieldChange} />
						<span class="toggle-icon">{opt.icon}</span>
						<span class="toggle-label">{opt.label}</span>
					</label>
				{/each}
			</div>
		</div>

		<!-- Subsection Headers -->
		<div class="control-group">
			<label class="checkbox-option">
				<input type="checkbox" bind:checked={advanced.use_subsection_headers} onchange={handleFieldChange} />
				<div class="checkbox-box">
					{#if advanced.use_subsection_headers}
						<svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
							<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
						</svg>
					{/if}
				</div>
				<div class="checkbox-content">
					<div class="checkbox-label">Use Subsection Headers</div>
					<div class="checkbox-desc">Add anatomical headers (CHEST:, ABDOMEN:)</div>
				</div>
			</label>
		</div>

		<!-- Custom Instructions -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">💬</span>
				<span class="label-text">Custom Instructions</span>
			</div>
			<textarea 
				bind:value={advanced.instructions} 
				onchange={handleFieldChange} 
				placeholder="Optional custom guidance..." 
				rows="3" 
				class="textarea-input"
			/>
		</div>

	{:else}
		<!-- Impression Section -->
		
		<!-- Verbosity Style -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">✍️</span>
				<span class="label-text">Verbosity Style</span>
			</div>
			
			<div class="option-grid">
				{#each [
					{ value: 'brief', icon: '⚡', label: 'Brief', desc: 'Direct diagnosis only' },
					{ value: 'standard', icon: '⚖️', label: 'Standard', desc: 'Main diagnosis with key details' },
					{ value: 'detailed', icon: '📚', label: 'Detailed', desc: 'Comprehensive descriptions' }
				] as opt}
					<label class="option-card {advanced.verbosity_style === opt.value ? 'selected' : ''}">
						<input type="radio" bind:group={advanced.verbosity_style} value={opt.value} onchange={handleFieldChange} />
						<div class="option-icon">{opt.icon}</div>
						<div class="option-content">
							<div class="option-title">{opt.label}</div>
							<div class="option-desc">{opt.desc}</div>
						</div>
					</label>
				{/each}
			</div>

			<div 
				class="example-container"
				onmouseenter={() => hoveredExample = 'impression-verbosity'}
				onmouseleave={() => hoveredExample = null}
			>
				<div class="example-header">
					<span class="example-icon">💡</span>
					<span class="example-label">EXAMPLE</span>
					<span class="example-hint">{hoveredExample === 'impression-verbosity' ? advanced.verbosity_style : 'Hover to view'}</span>
				</div>
				{#if hoveredExample === 'impression-verbosity'}
					<p class="example-desc">{examples.impression[advanced.verbosity_style].desc}</p>
					<div class="example-text">{examples.impression[advanced.verbosity_style].text}</div>
				{/if}
			</div>
		</div>

		<!-- Format -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">📝</span>
				<span class="label-text">Format</span>
			</div>
			
			<div class="toggle-group">
				{#each [
					{ value: 'prose', icon: '📄', label: 'Prose' },
					{ value: 'bullets', icon: '•', label: 'Bullets' },
					{ value: 'numbered', icon: '1', label: 'Numbered' }
				] as opt}
					<label class="toggle-option {advanced.format === opt.value ? 'selected' : ''}">
						<input type="radio" bind:group={advanced.format} value={opt.value} onchange={handleFieldChange} />
						<span class="toggle-icon">{opt.icon}</span>
						<span class="toggle-label">{opt.label}</span>
					</label>
				{/each}
			</div>
		</div>

		<!-- Differential Diagnosis -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">🔍</span>
				<span class="label-text">Differential Diagnosis</span>
			</div>
			
			<select bind:value={advanced.differential_approach} onchange={handleFieldChange} class="select-input">
				<option value="none">None</option>
				<option value="if_needed">If Needed (uncertain cases)</option>
				<option value="always">Always</option>
			</select>
		</div>

		<!-- Recommendations -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">💡</span>
				<span class="label-text">Include Recommendations</span>
			</div>
			
			<div class="checkbox-grid">
				<label class="checkbox-item">
					<input type="checkbox" bind:checked={advanced.recommendations.specialist_referral} onchange={handleFieldChange} />
					<div class="checkbox-box-small">
						{#if advanced.recommendations.specialist_referral}
							<svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
							</svg>
						{/if}
					</div>
					<span>Specialist Referral</span>
				</label>
				<label class="checkbox-item">
					<input type="checkbox" bind:checked={advanced.recommendations.further_workup} onchange={handleFieldChange} />
					<div class="checkbox-box-small">
						{#if advanced.recommendations.further_workup}
							<svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
							</svg>
						{/if}
					</div>
					<span>Further Workup</span>
				</label>
				<label class="checkbox-item">
					<input type="checkbox" bind:checked={advanced.recommendations.imaging_followup} onchange={handleFieldChange} />
					<div class="checkbox-box-small">
						{#if advanced.recommendations.imaging_followup}
							<svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
							</svg>
						{/if}
					</div>
					<span>Imaging Follow-up</span>
				</label>
				<label class="checkbox-item">
					<input type="checkbox" bind:checked={advanced.recommendations.clinical_correlation} onchange={handleFieldChange} />
					<div class="checkbox-box-small">
						{#if advanced.recommendations.clinical_correlation}
							<svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
							</svg>
						{/if}
					</div>
					<span>Clinical Correlation</span>
				</label>
			</div>
		</div>

		<!-- Custom Instructions -->
		<div class="control-group">
			<div class="control-label">
				<span class="label-icon">💬</span>
				<span class="label-text">Custom Instructions</span>
			</div>
			<textarea 
				bind:value={advanced.instructions} 
				onchange={handleFieldChange} 
				placeholder="Optional custom guidance..." 
				rows="3" 
				class="textarea-input"
			/>
		</div>
	{/if}
</div>

<style>
	/* Control Groups */
	.control-group {
		margin-bottom: 1.5rem;
	}

	.control-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		font-size: 0.9rem;
		font-weight: 600;
		color: #e5e7eb;
	}

	.label-icon {
		font-size: 1.1rem;
	}

	.label-text {
		letter-spacing: 0.025em;
	}

	/* Option Cards Grid */
	.option-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.75rem;
		margin-bottom: 1rem;
	}

	.option-card {
		position: relative;
		padding: 1.25rem 1rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		cursor: pointer;
		transition: all 0.2s ease;
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 0.75rem;
	}

	.option-card input {
		position: absolute;
		opacity: 0;
		width: 0;
		height: 0;
	}

	.option-card:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
		transform: translateY(-1px);
	}

	.option-card.selected {
		background: rgba(139, 92, 246, 0.1);
		border-color: rgb(139, 92, 246);
	}

	.option-icon {
		font-size: 2rem;
		line-height: 1;
	}

	.option-content {
		flex: 1;
	}

	.option-title {
		font-size: 0.875rem;
		font-weight: 600;
		color: #e5e7eb;
		margin-bottom: 0.25rem;
	}

	.option-desc {
		font-size: 0.75rem;
		color: #9ca3af;
		line-height: 1.3;
	}

	/* Example Container */
	.example-container {
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		padding: 1rem;
		transition: all 0.2s ease;
		cursor: default;
	}

	.example-container:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.3);
	}

	.example-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.example-icon {
		font-size: 0.875rem;
	}

	.example-label {
		color: #a78bfa;
	}

	.example-hint {
		margin-left: auto;
		color: #6b7280;
		font-style: italic;
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
	}

	.example-desc {
		margin-top: 0.5rem;
		font-size: 0.75rem;
		color: #9ca3af;
		line-height: 1.4;
	}

	.example-text {
		margin-top: 0.75rem;
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.2);
		border-radius: 0.375rem;
		font-size: 0.8125rem;
		line-height: 1.6;
		color: #d1d5db;
		animation: fadeIn 0.2s ease-out;
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* Select Input */
	.select-input {
		width: 100%;
		padding: 0.75rem 1rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		color: #e5e7eb;
		font-size: 0.875rem;
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.select-input:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.select-input:focus {
		outline: none;
		border-color: rgb(139, 92, 246);
		background: rgba(255, 255, 255, 0.04);
	}

	/* Toggle Group */
	.toggle-group {
		display: flex;
		gap: 0.5rem;
	}

	.toggle-option {
		flex: 1;
		padding: 0.75rem 1rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		cursor: pointer;
		transition: all 0.2s ease;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
	}

	.toggle-option input {
		display: none;
	}

	.toggle-option:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.toggle-option.selected {
		background: rgba(139, 92, 246, 0.15);
		border-color: rgb(139, 92, 246);
	}

	.toggle-icon {
		font-size: 1rem;
	}

	.toggle-label {
		font-size: 0.875rem;
		font-weight: 500;
		color: #e5e7eb;
	}

	/* Checkbox Option (large) */
	.checkbox-option {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 1rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.checkbox-option input {
		display: none;
	}

	.checkbox-option:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.checkbox-box {
		flex-shrink: 0;
		width: 1.25rem;
		height: 1.25rem;
		border: 1px solid rgba(255, 255, 255, 0.3);
		border-radius: 0.25rem;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all 0.2s ease;
	}

	.checkbox-option input:checked + .checkbox-box {
		background: rgb(139, 92, 246);
		border-color: rgb(139, 92, 246);
	}

	.checkbox-content {
		flex: 1;
	}

	.checkbox-label {
		font-size: 0.875rem;
		font-weight: 500;
		color: #e5e7eb;
		margin-bottom: 0.125rem;
	}

	.checkbox-desc {
		font-size: 0.75rem;
		color: #9ca3af;
	}

	/* Checkbox Grid (small items) */
	.checkbox-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.5rem;
	}

	.checkbox-item {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.75rem 0.875rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		cursor: pointer;
		transition: all 0.2s ease;
		font-size: 0.8125rem;
		color: #e5e7eb;
	}

	.checkbox-item input {
		display: none;
	}

	.checkbox-item:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.checkbox-box-small {
		flex-shrink: 0;
		width: 1rem;
		height: 1rem;
		border: 1px solid rgba(255, 255, 255, 0.3);
		border-radius: 0.25rem;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all 0.2s ease;
	}

	.checkbox-item input:checked + .checkbox-box-small {
		background: rgb(139, 92, 246);
		border-color: rgb(139, 92, 246);
	}

	/* Textarea Input */
	.textarea-input {
		width: 100%;
		padding: 0.75rem 1rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		color: #e5e7eb;
		font-size: 0.875rem;
		font-family: inherit;
		resize: vertical;
		transition: all 0.2s ease;
	}

	.textarea-input:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(139, 92, 246, 0.4);
	}

	.textarea-input:focus {
		outline: none;
		border-color: rgb(139, 92, 246);
		background: rgba(255, 255, 255, 0.04);
	}

	.textarea-input::placeholder {
		color: #6b7280;
	}
</style>
