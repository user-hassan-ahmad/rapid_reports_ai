<script>
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { fetchCustomPresets } from '$lib/stores/presets';
	import StylePresetCards from './StylePresetCards.svelte';
	import StyleGranularControls from './StyleGranularControls.svelte';

	const dispatch = createEventDispatcher();

	export let impressionConfig = {
		display_name: 'IMPRESSION',
		advanced: {
			instructions: '',
			verbosity_style: 'standard',
			impression_format: 'prose',
			differential_style: 'if_needed',
			comparison_terminology: 'measured',
			measurement_inclusion: 'key_only',
			incidental_handling: 'action_threshold',
		recommendations: {
			specialist_referral: true,
			further_workup: true,
			imaging_followup: false,
			clinical_correlation: false
		}
		}
	};

	let selectedImpressionPreset = 'standard_summary';

	function handlePresetChange(event) {
		selectedImpressionPreset = event.detail.presetId;
	}

	function resetToDefaults() {
		selectedImpressionPreset = 'standard_summary';
		impressionConfig.advanced = {
			instructions: '',
			verbosity_style: 'standard',
			impression_format: 'prose',
			differential_style: 'if_needed',
			comparison_terminology: 'measured',
			measurement_inclusion: 'key_only',
			incidental_handling: 'action_threshold',
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
		fetchCustomPresets('impression');
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
			
			<!-- Preset Cards -->
			<StylePresetCards 
				section="impression"
				bind:selectedPresetId={selectedImpressionPreset}
				bind:advanced={impressionConfig.advanced}
				on:presetChange={handlePresetChange}
			/>
			
			<!-- Granular Controls -->
			<div class="mt-6">
				<StyleGranularControls 
					section="impression"
					bind:advanced={impressionConfig.advanced}
					impressionContentStyle={impressionConfig.content_style}
					on:fieldChange={() => selectedImpressionPreset = 'custom'}
				/>
			</div>
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

