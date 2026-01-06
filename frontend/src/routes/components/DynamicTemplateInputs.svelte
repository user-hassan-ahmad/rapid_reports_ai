<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	export let templateConfig = null;
	export let userInputs = {};

	let variableSections = [];

	$: if (templateConfig && templateConfig.sections) {
		variableSections = templateConfig.sections
			.filter(s => s.has_input_field && s.included)
			.sort((a, b) => a.order - b.order);
	}

	function handleGenerate() {
		dispatch('generate', userInputs);
	}

	function getPlaceholder(section) {
		return 'Enter value';
	}
</script>

<div class="space-y-4">
	{#if templateConfig}
		{#each variableSections as section}
			<div class="space-y-2">
				{#if section.name === 'CLINICAL_HISTORY'}
					<div class="field required">
						<label class="block text-sm font-medium text-gray-300 mb-2">
							Clinical History <span class="text-red-400">*</span>
						</label>
						<textarea
							bind:value={userInputs.CLINICAL_HISTORY}
							required
							rows="3"
							class="input-dark"
							placeholder="Enter clinical history"
						></textarea>
						<small class="text-xs text-gray-500">
							Used as context {templateConfig.clinical_history?.include_in_output ? '(included in output)' : '(not included in output)'}
						</small>
					</div>
				{:else if section.name === 'FINDINGS'}
					<div class="field required">
						<label class="block text-sm font-medium text-gray-300 mb-2">
							Findings <span class="text-red-400">*</span>
						</label>
						<textarea
							bind:value={userInputs.FINDINGS}
							required
							rows="8"
							class="input-dark"
							placeholder="Enter findings"
						></textarea>
					</div>
				{:else}
					<div class="field optional">
						<label class="block text-sm font-medium text-gray-300 mb-2">
							{section.name} <span class="text-gray-500 text-xs">(optional)</span>
						</label>
						<textarea
							bind:value={userInputs[section.name]}
							rows="2"
							class="input-dark"
							placeholder={getPlaceholder(section)}
						></textarea>
					</div>
				{/if}
			</div>
		{/each}

		<div class="flex justify-end mt-6">
			<button
				on:click={handleGenerate}
				disabled={!userInputs.CLINICAL_HISTORY || !userInputs.FINDINGS}
				class="btn-primary"
				class:opacity-50={!userInputs.CLINICAL_HISTORY || !userInputs.FINDINGS}
			>
				Generate Report
			</button>
		</div>
	{:else}
		<div class="text-center py-8 text-gray-400">
			No template configuration available
		</div>
	{/if}
</div>

