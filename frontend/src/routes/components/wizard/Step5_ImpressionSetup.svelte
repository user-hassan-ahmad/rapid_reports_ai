<script>
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import StyleGranularControls from './StyleGranularControls.svelte';

	const dispatch = createEventDispatcher();

	export let impressionConfig = {
		display_name: 'IMPRESSION',
		advanced: {
			instructions: '',
			verbosity_style: 'prose',
			format: 'prose',
			differential_approach: 'if_needed',
			recommendations: {
				specialist_referral: true,
				further_workup: true,
				imaging_followup: false,
				clinical_correlation: false
			}
		}
	};

	function resetToDefaults() {
		impressionConfig.advanced = {
			instructions: '',
			verbosity_style: 'prose',
			format: 'prose',
			differential_approach: 'if_needed',
			recommendations: {
				specialist_referral: true,
				further_workup: true,
				imaging_followup: false,
				clinical_correlation: false
			}
		};
	}

	let suggesting = false;

	async function suggestInstructions() {
		suggesting = true;
		try {
			const response = await fetch(`${API_URL}/api/templates/suggest-instructions`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({
					section: 'IMPRESSION',
					scan_type: ''
				})
			});

			const data = await response.json();
			if (data.success && data.suggestions && data.suggestions.length > 0) {
				impressionConfig.advanced.instructions = data.suggestions[0];
			}
		} catch (error) {
			console.error('Error suggesting instructions:', error);
		} finally {
			suggesting = false;
		}
	}

	function handleNext() {
		dispatch('next');
	}

	onMount(() => {
		// No preset loading needed
	});
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">IMPRESSION Configuration</h3>
	<p class="text-gray-400 text-sm mb-6">
		Configure how the IMPRESSION section should be generated.
	</p>

	<div class="space-y-4">
		<!-- Section Name -->
		<div>
			<label class="block text-sm font-medium text-gray-300 mb-2">
				Section Name:
			</label>
			<input
				type="text"
				bind:value={impressionConfig.display_name}
				placeholder="IMPRESSION"
				class="input-dark"
			/>
			<p class="text-xs text-gray-500 mt-1">Or rename to CONCLUSION</p>
		</div>

		<!-- Writing Style Section (always visible) -->
		<div class="writing-style-section mt-6">
			<div class="flex items-center justify-between mb-4">
				<h4 class="text-lg font-semibold text-white flex items-center gap-2">
					<span>✨</span>
					<span>Writing Style</span>
				</h4>
				<button 
					onclick={resetToDefaults}
					class="btn-sm text-xs"
				>
					Reset to Defaults
				</button>
			</div>
			
			<!-- Style Controls -->
			<StyleGranularControls 
				section="impression"
				bind:advanced={impressionConfig.advanced}
				on:fieldChange={() => {}}
			/>
		</div>
	</div>

	<!-- Next Button -->
	<div class="flex justify-end mt-6">
		<button
			onclick={handleNext}
			class="btn-primary"
		>
			Next →
		</button>
	</div>
</div>

