<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { UnfilledItem } from '$lib/utils/placeholderDetection';
	import { extractUnit, parseAlternatives } from '$lib/utils/reportEditing';
	import { generateChatContext } from '$lib/utils/placeholderDetection';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';

	const dispatch = createEventDispatcher();

	export let visible = false;
	export let item: UnfilledItem | null = null;
	export let position: { x: number; y: number } = { x: 0, y: 0 };
	export let reportContent = '';
	export let enhancementsLoaded = false; // Whether enhancement sidebar has finished loading

	let measurementValue = '';
	let selectedAlternative = '';
	let loadingAI = false;

	$: if (item) {
		if (item.type === 'measurement') {
			measurementValue = '';
		} else if (item.type === 'variable') {
			measurementValue = ''; // Reuse measurementValue for variables
		} else if (item.type === 'alternative') {
			selectedAlternative = '';
		}
	}

	$: isBlankSection = item?.type === 'blank_section';
	$: itemTypeLabel = item?.type === 'measurement' ? 'Measurement'
		: item?.type === 'variable' ? 'Variable'
		: item?.type === 'alternative' ? 'Alternative'
		: item?.type === 'blank_section' ? 'Unfilled Section'
		: 'Item';

	function handleDeleteSection() {
		if (!item || item.type !== 'blank_section') return;
		dispatch('deleteSection', { sectionName: item.text });
	}

	function handleFillSectionWithAI() {
		if (!item || item.type !== 'blank_section') return;
		dispatch('askAI', { 
			message: `Please help me complete the ${item.text} section based on available findings.` 
		});
	}

	$: {
		console.log('UnfilledItemHoverPopup - visible:', visible, 'item:', item, 'position:', position);
	}

	$: alternatives = item && item.type === 'alternative' ? parseAlternatives(item.text) : [];
	$: unit = item && item.type === 'measurement' && reportContent ? extractUnit(reportContent, item.index, item.text) : '';

	function handleApply() {
		if (!item) return;

		let value = '';
		if (item.type === 'measurement') {
			value = measurementValue.trim();
		} else if (item.type === 'variable') {
			value = measurementValue.trim();
		} else if (item.type === 'alternative') {
			value = selectedAlternative.trim();
		}


		if (value) {
			dispatch('apply', {
				item,
				value
			});
		}
	}

	function handleAskAI() {
		if (!item) return;
		const chatPrompt = generateChatContext(item.type, item.text, item.surroundingContext);
		dispatch('askAI', { message: chatPrompt });
	}
	
	function handleClose() {
		dispatch('close');
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleApply();
		} else if (event.key === 'Escape') {
			visible = false;
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if visible && item && (item.type === 'measurement' || item.type === 'variable' || item.type === 'alternative' || item.type === 'blank_section')}
	<div
		class="unfilled-hover-popup"
		style="left: {position.x}px; top: {position.y}px;"
		role="tooltip"
		onclick={(e) => e.stopPropagation()}
		onmouseenter={() => {
			// Keep popup visible when hovering over it
			dispatch('keepVisible');
		}}
		onmouseleave={() => {
			// Small delay before hiding to allow moving back to highlight
			setTimeout(() => {
				dispatch('close');
			}, 150);
		}}
	>
		<div class="popup-header">
			<span class="popup-type-badge">
				{#if item.type === 'measurement'}
					<svg class="w-3.5 h-3.5 inline-block mr-1.5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
					</svg>
					Measurement
				{:else if item.type === 'variable'}
					<svg class="w-3.5 h-3.5 inline-block mr-1.5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
					</svg>
					Variable
				{:else if item.type === 'alternative'}
					<svg class="w-3.5 h-3.5 inline-block mr-1.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
					</svg>
					Alternative
				{:else if item.type === 'blank_section'}
					<svg class="w-3.5 h-3.5 inline-block mr-1.5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
					</svg>
					Unfilled Section
				{:else}
					<svg class="w-3.5 h-3.5 inline-block mr-1.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
					</svg>
					Item
				{/if}
			</span>
			<button
				onclick={handleClose}
				class="popup-close"
				title="Close"
				type="button"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<div class="popup-content">
			{#if item.type === 'blank_section'}
				<div class="popup-section-actions">
					<p class="popup-section-message">
						This section ({item.text}) was not addressed in your findings.
					</p>
				</div>
			{:else if item.type === 'measurement'}
				<div class="popup-input-group">
					<label class="popup-label">
						Enter value
						{#if unit}
							<span class="popup-unit">({unit})</span>
						{/if}
					</label>
					<input
						type="text"
						bind:value={measurementValue}
						placeholder="Enter measurement"
						class="popup-input"
						autofocus
					/>
				</div>
			{:else if item.type === 'variable'}
				<div class="popup-input-group">
					<label class="popup-label">
						Enter value for {item.text}
					</label>
					<input
						type="text"
						bind:value={measurementValue}
						placeholder="Enter value"
						class="popup-input"
						autofocus
					/>
				</div>
			{:else if item.type === 'alternative'}
				<div class="popup-input-group">
					<label class="popup-label">Select option</label>
					<select
						bind:value={selectedAlternative}
						class="popup-select"
					>
						<option value="">-- Select --</option>
						{#each alternatives as option}
							<option value={option}>{option}</option>
						{/each}
					</select>
				</div>
			{/if}
		</div>

		<div class="popup-actions">
			{#if item.type === 'blank_section'}
				<button
					onclick={handleDeleteSection}
					class="popup-btn popup-btn-danger"
				>
					<svg class="w-3.5 h-3.5 inline-block mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
					</svg>
					Delete Section
				</button>
				<button
					onclick={handleFillSectionWithAI}
					disabled={!enhancementsLoaded}
					class="popup-btn popup-btn-primary"
					title={enhancementsLoaded ? 'Fill section with AI' : 'Loading enhancements...'}
				>
					<svg class="w-3.5 h-3.5 inline-block mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
					</svg>
					Fill with AI
				</button>
			{:else}
				<button
					onclick={handleApply}
					disabled={
						item.type === 'measurement' ? !measurementValue.trim() 
						: item.type === 'variable' ? !measurementValue.trim()
						: item.type === 'alternative' ? !selectedAlternative
						: false
					}
					class="popup-btn popup-btn-primary"
				>
					<svg class="w-3.5 h-3.5 inline-block mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
					Apply
				</button>
				<button
					onclick={handleAskAI}
					disabled={!enhancementsLoaded}
					class="popup-btn popup-btn-secondary"
					title={enhancementsLoaded ? 'Ask AI for help' : 'Loading enhancements...'}
				>
					<svg class="w-3.5 h-3.5 inline-block mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
					</svg>
					Ask AI
				</button>
			{/if}
		</div>
	</div>
{/if}

<style>
	.unfilled-hover-popup {
		position: fixed;
		z-index: 99999;
		background: rgba(0, 0, 0, 0.7);
		backdrop-filter: blur(2rem);
		-webkit-backdrop-filter: blur(2rem);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.75rem;
		box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(139, 92, 246, 0.1);
		min-width: 280px;
		max-width: 400px;
		transform: translate(-50%, -100%);
		margin-top: -8px;
		animation: popupFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
		will-change: transform, opacity;
	}

	@keyframes popupFadeIn {
		from {
			opacity: 0;
			transform: translate(-50%, -100%) scale(0.9) translateY(4px);
		}
		to {
			opacity: 1;
			transform: translate(-50%, -100%) scale(1) translateY(0);
		}
	}

	.popup-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		background: linear-gradient(to bottom, rgba(0, 0, 0, 0.4), transparent);
	}

	.popup-type-badge {
		display: inline-flex;
		align-items: center;
		font-size: 0.75rem;
		font-weight: 600;
		color: #d1d5db;
	}

	.popup-close {
		background: none;
		border: none;
		color: #9ca3af;
		font-size: 1.25rem;
		line-height: 1;
		cursor: pointer;
		padding: 0.25rem;
		width: 1.5rem;
		height: 1.5rem;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 0.375rem;
		transition: all 0.2s;
	}

	.popup-close:hover {
		background: rgba(255, 255, 255, 0.1);
		color: white;
	}

	.popup-content {
		padding: 1rem;
	}

	.popup-input-group {
		margin-bottom: 0.75rem;
	}

	.popup-label {
		display: block;
		font-size: 0.75rem;
		font-weight: 500;
		color: #d1d5db;
		margin-bottom: 0.5rem;
	}

	.popup-unit {
		color: #9ca3af;
		font-weight: normal;
	}

	.popup-input,
	.popup-select {
		width: 100%;
		background: rgba(0, 0, 0, 0.5);
		backdrop-filter: blur(0.5rem);
		-webkit-backdrop-filter: blur(0.5rem);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 0.5rem;
		padding: 0.5rem 0.75rem;
		color: white;
		font-size: 0.875rem;
		transition: all 0.2s;
	}

	.popup-input:focus,
	.popup-select:focus {
		outline: none;
		border-color: rgba(168, 85, 247, 0.5);
		box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.1);
	}

	.popup-select {
		cursor: pointer;
	}

	.popup-actions {
		display: flex;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(0, 0, 0, 0.2);
	}

	.popup-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		padding: 0.5rem 0.75rem;
		border-radius: 0.5rem;
		font-size: 0.75rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		border: none;
	}

	.popup-btn-primary {
		background: linear-gradient(to right, rgb(147, 51, 234), rgb(168, 85, 247));
		color: white;
		box-shadow: 0 10px 15px -3px rgba(147, 51, 234, 0.3), 0 4px 6px -2px rgba(147, 51, 234, 0.2);
	}

	.popup-btn-primary:hover:not(:disabled) {
		background: linear-gradient(to right, rgb(126, 34, 206), rgb(147, 51, 234));
		box-shadow: 0 10px 15px -3px rgba(147, 51, 234, 0.5), 0 4px 6px -2px rgba(147, 51, 234, 0.4);
	}

	.popup-btn-primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
		background: rgb(55, 65, 81);
		box-shadow: none;
	}

	.popup-btn-secondary {
		background: rgba(255, 255, 255, 0.1);
		backdrop-filter: blur(0.5rem);
		-webkit-backdrop-filter: blur(0.5rem);
		border: 1px solid rgba(255, 255, 255, 0.1);
		color: #d1d5db;
	}

	.popup-btn-secondary:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.2);
		color: white;
	}
	
	.popup-btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.popup-section-actions {
		margin-bottom: 0;
	}

	.popup-section-message {
		font-size: 0.8125rem;
		color: #d1d5db;
		margin: 0;
		line-height: 1.5;
	}

	.popup-btn-danger {
		background: rgba(239, 68, 68, 0.9);
		color: white;
	}

	.popup-btn-danger:hover:not(:disabled) {
		background: rgb(220, 38, 38);
	}
</style>

