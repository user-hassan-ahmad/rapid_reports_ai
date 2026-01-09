<script>
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import StyleGranularControls from '../wizard/StyleGranularControls.svelte';

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
		handleChange();
	}

	let suggesting = false;
	let showAdvanced = true; // Default to expanded

	// Update range slider background based on value
	function updateRangeBackground(value, min, max, element) {
		const percentage = ((value - min) / (max - min)) * 100;
		element.style.background = `linear-gradient(to right, rgba(168, 85, 247, 0.8) 0%, rgba(168, 85, 247, 0.8) ${percentage}%, rgba(255, 255, 255, 0.1) ${percentage}%, rgba(255, 255, 255, 0.1) 100%)`;
	}

	// Removed handleVerbosityChange - no longer using slider

	// Svelte action to initialize range slider
	function initRangeSlider(node, { value, min, max }) {
		updateRangeBackground(value, min, max, node);
		return {
			update({ value, min, max }) {
				updateRangeBackground(value, min, max, node);
			}
		};
	}

	function handleChange() {
		dispatch('change');
	}

	onMount(() => {
		// No preset loading needed
	});

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
				handleChange();
			}
		} catch (error) {
			console.error('Error suggesting instructions:', error);
		} finally {
			suggesting = false;
		}
	}
</script>

<style>
	.range-slider {
		-webkit-appearance: none;
		appearance: none;
		background: linear-gradient(to right, rgba(168, 85, 247, 0.8) 0%, rgba(168, 85, 247, 0.8) 0%, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0.1) 100%);
		outline: none;
		border-radius: 8px;
		height: 8px;
	}

	.range-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: linear-gradient(135deg, #a855f7, #8b5cf6);
		cursor: pointer;
		border: 2px solid rgba(255, 255, 255, 0.2);
		box-shadow: 0 2px 8px rgba(168, 85, 247, 0.4);
		transition: all 0.2s ease;
	}

	.range-slider::-webkit-slider-thumb:hover {
		transform: scale(1.1);
		box-shadow: 0 4px 12px rgba(168, 85, 247, 0.6);
	}

	.range-slider::-moz-range-thumb {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: linear-gradient(135deg, #a855f7, #8b5cf6);
		cursor: pointer;
		border: 2px solid rgba(255, 255, 255, 0.2);
		box-shadow: 0 2px 8px rgba(168, 85, 247, 0.4);
		transition: all 0.2s ease;
	}

	.range-slider::-moz-range-thumb:hover {
		transform: scale(1.1);
		box-shadow: 0 4px 12px rgba(168, 85, 247, 0.6);
	}

	.range-slider::-moz-range-track {
		background: rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		height: 8px;
	}

	.range-slider::-moz-range-progress {
		background: rgba(168, 85, 247, 0.8);
		border-radius: 8px;
		height: 8px;
	}
</style>

<div class="max-w-6xl mx-auto space-y-6 py-2">
	<!-- Header with gradient -->
	<div class="flex items-center justify-between mb-6">
		<div>
			<h2 class="text-3xl font-bold bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent">IMPRESSION Configuration</h2>
			<p class="text-sm text-gray-400 mt-2 flex items-center gap-2">
				<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				Configure how the IMPRESSION section should be generated
			</p>
		</div>
	</div>

	<div class="space-y-6">
		<!-- Section Name -->
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-blue-500/30 transition-all duration-300">
			<div class="flex items-center gap-3 mb-6">
				<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 shadow-lg shadow-blue-500/30">
					<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
					</svg>
				</div>
				<h3 class="text-lg font-bold text-white uppercase tracking-wider">Section Name</h3>
			</div>
			<input
				type="text"
				bind:value={impressionConfig.display_name}
				oninput={handleChange}
				placeholder="IMPRESSION"
				class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 transition-all hover:border-white/20"
			/>
			<div class="mt-3 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
				<p class="text-xs text-blue-200 flex items-start gap-2">
					<svg class="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
					<span>You can rename this to "CONCLUSION" or any other name</span>
				</p>
			</div>
		</section>

		<!-- Writing Style Section (always visible) -->
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-purple-500/30 transition-all duration-300">
			<div class="flex items-center justify-between mb-6">
				<div class="flex items-center gap-3">
					<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-purple-600 shadow-lg shadow-purple-500/30">
						<span class="text-xl">✨</span>
					</div>
					<h3 class="text-lg font-bold text-white uppercase tracking-wider">Writing Style</h3>
				</div>
				<button 
					type="button"
					onclick={resetToDefaults}
					class="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-all"
				>
					Reset to Defaults
				</button>
			</div>
			
			<!-- Style Controls -->
			<StyleGranularControls 
				section="impression"
				bind:advanced={impressionConfig.advanced}
				on:fieldChange={handleChange}
			/>
		</section>
	</div>
</div>

