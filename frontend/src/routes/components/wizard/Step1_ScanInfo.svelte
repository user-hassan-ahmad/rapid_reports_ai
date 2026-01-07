<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	export let scanType = '';
	export let contrast = '';
	export let contrastOther = '';
	export let contrastPhases = [];
	export let protocolDetails = '';

	function handleNext() {
		if (!scanType || !contrast) {
			return; // Validation handled by disabled button
		}
		dispatch('next');
	}

	function handleContrastChange() {
		// Clear phases when switching to no_contrast
		if (contrast === 'no_contrast') {
			contrastPhases = [];
		}
	}

	$: canProceed = scanType.trim() !== '' && contrast !== '';
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">Scan Information</h3>
	<p class="text-gray-400 text-sm mb-6">
		Provide basic information about the scan type and protocol. This will be used to generate appropriate templates.
	</p>

	<div class="space-y-4">
		<!-- Scan Type -->
		<div>
			<label class="block text-sm font-medium text-gray-300 mb-2">
				Scan Type <span class="text-red-400">*</span>
			</label>
			<input
				type="text"
				bind:value={scanType}
				placeholder="e.g., Chest CT, MRI Brain, CT Abdomen Pelvis"
				class="input-dark"
				required
			/>
		</div>

		<!-- Contrast -->
		<div class="bg-black/40 border border-white/10 rounded-lg p-4 hover:border-blue-400/30 hover:shadow-lg hover:shadow-blue-500/10 transition-all">
			<label class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
				<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
				</svg>
				Contrast Administration <span class="text-red-400">*</span>
			</label>
			
			<!-- Contrast Status -->
			<div class="flex gap-2 mb-3">
				{#each [
					{ value: 'no_contrast', label: 'Non-contrast', icon: '⭕' },
					{ value: 'with_contrast', label: 'With Contrast', icon: '💉' }
				] as option}
					<label class="contrast-pill cursor-pointer flex-1">
						<input
							type="radio"
							bind:group={contrast}
							value={option.value}
							onchange={handleContrastChange}
							class="hidden"
						/>
						<span class="pill-btn {contrast === option.value ? 'selected' : ''} justify-center">
							<span class="pill-icon">{option.icon}</span>
							<span class="pill-label">{option.label}</span>
						</span>
					</label>
				{/each}
			</div>

			<!-- Phase Selection (only if contrast is used) -->
			{#if contrast === 'with_contrast'}
				<div class="mt-3 pt-3 border-t border-white/10">
					<label class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 block">
						Phases (select all that apply)
					</label>
					<div class="flex flex-wrap gap-2">
						{#each [
							{ value: 'pre', label: 'Pre-contrast', icon: '⚪' },
							{ value: 'arterial', label: 'Arterial', icon: '🔴' },
							{ value: 'portal_venous', label: 'Portal venous', icon: '🟣' },
							{ value: 'delayed', label: 'Delayed', icon: '🔵' },
							{ value: 'oral', label: 'Oral', icon: '🥤' }
						] as phase}
							<label class="phase-pill cursor-pointer">
								<input
									type="checkbox"
									bind:group={contrastPhases}
									value={phase.value}
									class="hidden"
								/>
								<span class="pill-btn-small {contrastPhases.includes(phase.value) ? 'selected' : ''}">
									<span class="pill-icon">{phase.icon}</span>
									<span class="pill-label">{phase.label}</span>
								</span>
							</label>
						{/each}
					</div>
				</div>
			{/if}
		</div>

		<!-- Protocol Details -->
		<div>
			<label class="block text-sm font-medium text-gray-300 mb-2">
				Additional protocol details <span class="text-gray-500 text-xs">(optional)</span>
			</label>
			<textarea
				bind:value={protocolDetails}
				placeholder="e.g., 3mm slices, delayed phase, DWI sequences"
				rows="3"
				class="input-dark"
				onkeydown={(e) => {
					// Allow Enter to create new lines in textarea
					if (e.key === 'Enter') {
						e.stopPropagation();
					}
				}}
			></textarea>
		</div>
	</div>

	<!-- Next Button -->
	<div class="flex justify-end mt-6">
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

<style>
	/* Contrast Pills */
	.contrast-pill,
	.phase-pill {
		display: inline-block;
	}

	.pill-btn {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.875rem;
		font-size: 0.8125rem;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		color: rgba(255, 255, 255, 0.7);
		transition: all 0.2s ease;
		white-space: nowrap;
	}

	.pill-btn:hover {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(139, 92, 246, 0.4);
		color: white;
		transform: translateY(-1px);
		box-shadow: 0 4px 8px rgba(139, 92, 246, 0.2);
	}

	.pill-btn.selected {
		background: rgba(139, 92, 246, 0.3);
		border-color: rgb(139, 92, 246);
		color: white;
		font-weight: 500;
		box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
	}

	/* Smaller pills for phases */
	.pill-btn-small {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.375rem 0.625rem;
		font-size: 0.75rem;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.375rem;
		color: rgba(255, 255, 255, 0.7);
		transition: all 0.2s ease;
		white-space: nowrap;
	}

	.pill-btn-small:hover {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(59, 130, 246, 0.4);
		color: white;
		transform: translateY(-1px);
		box-shadow: 0 4px 8px rgba(59, 130, 246, 0.2);
	}

	.pill-btn-small.selected {
		background: rgba(59, 130, 246, 0.3);
		border-color: rgb(59, 130, 246);
		color: white;
		font-weight: 500;
		box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
	}

	.pill-icon {
		font-size: 1rem;
		line-height: 1;
	}

	.pill-label {
		font-size: 0.8125rem;
		line-height: 1;
	}
</style>

