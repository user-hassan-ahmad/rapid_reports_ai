<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { UnfilledItems, UnfilledItem } from '$lib/utils/placeholderDetection';
	import type { UnfilledEdit } from '$lib/stores/unfilledEditor';
	import { extractUnit, parseAlternatives, generateItemId } from '$lib/utils/reportEditing';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	const dispatch = createEventDispatcher();

	export let visible = false;
	export let items: UnfilledItems;
	export let reportContent = '';
	export let onSave: (edits: Map<string, UnfilledEdit>) => void;
	export let onCancel: () => void;

	// Flatten all items
	let allItems: Array<UnfilledItem & { id: string }> = [];
	let edits = new Map<string, UnfilledEdit>();
	let filter: 'all' | 'measurements' | 'variables' | 'alternatives' | 'instructions' = 'all';
	let searchQuery = '';

	// Initialize items when visible
	$: if (visible && items.total > 0) {
		allItems = [];
		items.measurements.forEach((item, idx) => {
			allItems.push({ ...item, id: generateItemId(item, idx) });
		});
		items.variables.forEach((item, idx) => {
			allItems.push({ ...item, id: generateItemId(item, idx) });
		});
		items.alternatives.forEach((item, idx) => {
			allItems.push({ ...item, id: generateItemId(item, idx) });
		});
		items.instructions.forEach((item, idx) => {
			allItems.push({ ...item, id: generateItemId(item, idx) });
		});
		allItems.sort((a, b) => a.index - b.index);
		edits = new Map();
	}

	// Filter items
	$: filteredItems = allItems.filter(item => {
		if (filter !== 'all' && item.type !== filter.slice(0, -1)) return false; // Remove 's' from filter
		if (searchQuery) {
			const query = searchQuery.toLowerCase();
			return item.text.toLowerCase().includes(query) || 
			       item.surroundingContext.toLowerCase().includes(query);
		}
		return true;
	});

	$: filledCount = Array.from(edits.values()).filter(e => e.newValue && e.newValue.trim() !== '').length;
	$: totalItems = allItems.length;

	function updateEdit(itemId: string, value: string) {
		const item = allItems.find(i => i.id === itemId);
		if (!item) return;

		const edit: UnfilledEdit = {
			itemId: item.id,
			originalText: item.text,
			newValue: value,
			type: item.type,
			context: item.surroundingContext,
			position: item.index
		};
		edits.set(itemId, edit);
	}

	function removeEdit(itemId: string) {
		edits.delete(itemId);
	}


	function jumpToItem(item: UnfilledItem & { id: string }) {
		// Scroll to item in report (this will be handled by parent)
		dispatch('jumpToItem', { item });
	}

	function handleSave() {
		onSave(edits);
	}

	function getEditValue(itemId: string): string {
		return edits.get(itemId)?.newValue || '';
	}
</script>

{#if visible}
	<div 
		class="fixed inset-0 bg-black/80 z-50 flex"
		onclick={(e) => e.target === e.currentTarget && onCancel()}
		role="dialog"
		aria-modal="true"
	>
		<div 
			class="bg-gray-900 border-l border-purple-500/30 w-full max-w-2xl ml-auto h-full overflow-hidden flex flex-col shadow-2xl"
			onclick={(e) => e.stopPropagation()}
		>
			<!-- Header -->
			<div class="p-6 border-b border-gray-700">
				<div class="flex items-center justify-between mb-4">
					<h2 class="text-xl font-bold text-white">📋 Fill Unfilled Items</h2>
					<button 
						onclick={onCancel}
						class="text-gray-400 hover:text-white text-2xl leading-none"
					>
						×
					</button>
				</div>

				<!-- Filter Tabs -->
				<div class="flex items-center gap-2 mb-4 flex-wrap">
					<button
						onclick={() => filter = 'all'}
						class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {filter === 'all' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}"
					>
						All ({totalItems})
					</button>
					{#if items.measurements.length > 0}
						<button
							onclick={() => filter = 'measurements'}
							class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {filter === 'measurements' ? 'bg-yellow-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}"
						>
							🟡 Measurements ({items.measurements.length})
						</button>
					{/if}
					{#if items.variables.length > 0}
						<button
							onclick={() => filter = 'variables'}
							class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {filter === 'variables' ? 'bg-green-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}"
						>
							🟢 Variables ({items.variables.length})
						</button>
					{/if}
					{#if items.alternatives.length > 0}
						<button
							onclick={() => filter = 'alternatives'}
							class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {filter === 'alternatives' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}"
						>
							🟣 Alternatives ({items.alternatives.length})
						</button>
					{/if}
					{#if items.instructions.length > 0}
						<button
							onclick={() => filter = 'instructions'}
							class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {filter === 'instructions' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}"
						>
							🔵 Instructions ({items.instructions.length})
						</button>
					{/if}
				</div>

				<!-- Search -->
				<input
					type="text"
					bind:value={searchQuery}
					placeholder="Search items..."
					class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
				/>
			</div>

			<!-- Items List -->
			<div class="flex-1 overflow-auto p-6">
				<div class="space-y-3">
					{#each filteredItems as item, index (item.id)}
						<div class="p-4 bg-gray-800/50 rounded-lg border border-gray-700">
							<!-- Item Header -->
							<div class="flex items-start justify-between mb-3">
								<div class="flex-1">
									<div class="flex items-center gap-2 mb-2">
										{#if item.type === 'measurement'}
											<span class="px-2 py-0.5 bg-yellow-900/30 text-yellow-300 text-xs rounded border border-yellow-500/30">
												🟡 Measurement
											</span>
										{:else if item.type === 'variable'}
											<span class="px-2 py-0.5 bg-green-900/30 text-green-300 text-xs rounded border border-green-500/30">
												🟢 Variable
											</span>
										{:else if item.type === 'alternative'}
											<span class="px-2 py-0.5 bg-purple-900/30 text-purple-300 text-xs rounded border border-purple-500/30">
												🟣 Alternative
											</span>
										{:else}
											<span class="px-2 py-0.5 bg-blue-900/30 text-blue-300 text-xs rounded border border-blue-500/30">
												🔵 Instruction
											</span>
										{/if}
										<span class="text-xs text-gray-500">#{index + 1}</span>
									</div>
									
									<!-- Context Preview -->
									<div class="text-xs text-gray-400 mb-3 font-mono">
										...{item.surroundingContext.substring(0, 150)}...
									</div>
								</div>
							</div>

							<!-- Input Section -->
							<div class="space-y-2">
								{#if item.type === 'measurement'}
									<div class="flex items-center gap-2">
										<input
											type="text"
											value={getEditValue(item.id)}
											oninput={(e) => updateEdit(item.id, e.target.value)}
											placeholder={reportContent ? extractUnit(reportContent, item.index, item.text) || 'Enter value' : 'Enter value'}
											class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
										/>
										{#if reportContent && extractUnit(reportContent, item.index, item.text)}
											<span class="text-xs text-gray-400">{extractUnit(reportContent, item.index, item.text)}</span>
										{/if}
									</div>
								{:else if item.type === 'alternative'}
									<select
										value={getEditValue(item.id)}
										onchange={(e) => updateEdit(item.id, e.target.value)}
										class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
									>
										<option value="">-- Select option --</option>
										{#each parseAlternatives(item.text) as option}
											<option value={option}>{option}</option>
										{/each}
									</select>
								{:else if item.type === 'variable'}
									<input
										type="text"
										value={getEditValue(item.id)}
										oninput={(e) => updateEdit(item.id, e.target.value)}
										placeholder={`Enter value for ${item.text}`}
										class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
									/>
								{:else if item.type === 'instruction'}
									<div class="space-y-2">
										<label class="flex items-center gap-2 cursor-pointer">
											<input
												type="radio"
												name="instruction-{item.id}"
												value="remove"
												checked={getEditValue(item.id) === 'remove'}
												onchange={() => updateEdit(item.id, 'remove')}
												class="text-blue-500"
											/>
											<span class="text-sm text-white">Remove</span>
										</label>
										<label class="flex items-center gap-2 cursor-pointer">
											<input
												type="radio"
												name="instruction-{item.id}"
												value="keep"
												checked={getEditValue(item.id) === 'keep'}
												onchange={() => updateEdit(item.id, 'keep')}
												class="text-blue-500"
											/>
											<span class="text-sm text-white">Keep</span>
										</label>
									</div>
								{/if}

								<!-- Actions -->
								<div class="flex items-center gap-2 pt-2">
									<button
										onclick={() => jumpToItem(item)}
										class="px-3 py-1.5 text-xs font-medium bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors flex items-center gap-1"
									>
										📍 Jump
									</button>
									{#if getEditValue(item.id)}
										<button
											onclick={() => removeEdit(item.id)}
											class="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-red-400 transition-colors"
										>
											Clear
										</button>
									{/if}
								</div>
							</div>
						</div>
					{:else}
						<div class="text-center py-12 text-gray-400">
							<p>No items found</p>
						</div>
					{/each}
				</div>
			</div>

			<!-- Footer -->
			<div class="p-6 border-t border-gray-700 bg-gray-900">
				<div class="flex items-center justify-between mb-4">
					<div class="text-sm text-gray-400">
						<span class="font-semibold text-white">{filledCount}</span> of <span class="font-semibold text-white">{totalItems}</span> filled
					</div>
				</div>
				<div class="flex items-center justify-end gap-2">
					<button
						onclick={onCancel}
						class="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white transition-colors"
					>
						Cancel
					</button>
					<button
						onclick={handleSave}
						disabled={filledCount === 0}
						class="px-6 py-2 text-sm font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						Save {filledCount} Change{filledCount !== 1 ? 's' : ''}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	:global([role="dialog"]) {
		outline: none;
	}
</style>

