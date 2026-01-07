<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	export let reports = [];
	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';

	const reportTypes = [
		{ value: '', label: '-- Select type --' },
		{ value: 'normal', label: 'Normal study' },
		{ value: 'single_abnormality', label: 'Single abnormality' },
		{ value: 'multiple_findings', label: 'Multiple findings' },
		{ value: 'complex', label: 'Complex case' },
		{ value: 'postop', label: 'Post-operative' },
		{ value: 'emergency', label: 'Emergency/acute' },
		{ value: 'followup', label: 'Follow-up' }
	];

	function addReport() {
		if (reports.length < 10) {
			reports = [...reports, { type: '', context: '', content: '' }];
		}
	}

	function removeReport(index) {
		reports = reports.filter((_, i) => i !== index);
	}

	function handleNext() {
		if (reports.length < 2) {
			alert('Please provide at least 2 example reports.');
			return;
		}
		
		// Validate all reports have type and content
		for (let i = 0; i < reports.length; i++) {
			if (!reports[i].type || !reports[i].content.trim()) {
				alert(`Report ${i + 1} is missing type or content.`);
				return;
			}
		}
		
		dispatch('next');
	}

	$: canProceed = reports.length >= 2 && reports.every(r => r.type && r.content.trim());
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">Paste Your Example Reports</h3>
	<p class="text-gray-400 text-sm mb-6">
		Provide 2-10 examples with descriptions (more is better). The AI will analyze your style and structure.
	</p>

	<div class="space-y-4">
		{#each reports as report, i}
			<div class="card-dark p-4">
				<div class="flex items-center justify-between mb-4">
					<h4 class="font-semibold text-white">Report {i + 1}</h4>
					<button
						onclick={() => removeReport(i)}
						class="btn-sm text-red-400 hover:text-red-300"
					>
						× Remove
					</button>
				</div>

				<div class="space-y-3">
					<div>
						<label class="block text-sm font-medium text-gray-300 mb-2">
							What is this report? <span class="text-red-400">*</span>
						</label>
						<select
							bind:value={report.type}
							class="select-dark"
						>
							{#each reportTypes as rt}
								<option value={rt.value}>{rt.label}</option>
							{/each}
						</select>
					</div>

					<div>
						<label class="block text-sm font-medium text-gray-300 mb-2">
							Additional context <span class="text-gray-500 text-xs">(optional)</span>
						</label>
						<input
							type="text"
							bind:value={report.context}
							placeholder="e.g., Routine screening, no findings"
							class="input-dark"
						/>
					</div>

					<div>
						<label class="block text-sm font-medium text-gray-300 mb-2">
							Report Content <span class="text-red-400">*</span>
						</label>
						<textarea
							bind:value={report.content}
							rows="12"
							placeholder="Paste complete report here..."
							class="input-dark font-mono text-sm"
							onkeydown={(e) => {
								// Allow Enter to create new lines in textarea
								if (e.key === 'Enter') {
									e.stopPropagation();
								}
							}}
						></textarea>
					</div>
				</div>
			</div>
		{/each}

		<button
			onclick={addReport}
			disabled={reports.length >= 10}
			class="btn-secondary w-full"
			class:opacity-50={reports.length >= 10}
		>
			+ Add Another Report ({reports.length}/10)
		</button>
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
			Analyze Reports →
		</button>
	</div>
</div>

