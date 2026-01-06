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
				{item.type === 'measurement' ? '🟡 Measurement' 
					: item.type === 'variable' ? '🟢 Variable'
					: item.type === 'alternative' ? '🟣 Alternative'
					: item.type === 'blank_section' ? '⚠️ Unfilled Section'
					: '🔍 Item'}
			</span>
			<button
				onclick={handleClose}
				class="popup-close"
				title="Close"
				type="button"
			>
				×
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
					🗑️ Delete Section
				</button>
				<button
					onclick={handleFillSectionWithAI}
					disabled={!enhancementsLoaded}
					class="popup-btn popup-btn-primary"
					title={enhancementsLoaded ? 'Fill section with AI' : 'Loading enhancements...'}
				>
					✨ Fill with AI
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
					Apply
				</button>
				<button
					onclick={handleAskAI}
					disabled={!enhancementsLoaded}
					class="popup-btn popup-btn-secondary"
					title={enhancementsLoaded ? 'Ask AI for help' : 'Loading enhancements...'}
				>
					💬 Ask AI
				</button>
			{/if}
		</div>
	</div>
{/if}

<style>
	.unfilled-hover-popup {
		position: fixed;
		z-index: 99999;
		background: #1f2937;
		border: 1px solid rgba(147, 51, 234, 0.3);
		border-radius: 8px;
		box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
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
		padding: 8px 12px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
	}

	.popup-type-badge {
		font-size: 11px;
		font-weight: 600;
		color: #d1d5db;
	}

	.popup-close {
		background: none;
		border: none;
		color: #9ca3af;
		font-size: 20px;
		line-height: 1;
		cursor: pointer;
		padding: 0;
		width: 20px;
		height: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 4px;
		transition: all 0.2s;
	}

	.popup-close:hover {
		background: rgba(255, 255, 255, 0.1);
		color: white;
	}

	.popup-content {
		padding: 12px;
	}

	.popup-input-group {
		margin-bottom: 12px;
	}

	.popup-label {
		display: block;
		font-size: 12px;
		font-weight: 500;
		color: #d1d5db;
		margin-bottom: 6px;
	}

	.popup-unit {
		color: #9ca3af;
		font-weight: normal;
	}

	.popup-input,
	.popup-select {
		width: 100%;
		background: #111827;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 6px;
		padding: 8px 12px;
		color: white;
		font-size: 14px;
		transition: all 0.2s;
	}

	.popup-input:focus,
	.popup-select:focus {
		outline: none;
		border-color: #a855f7;
		box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.1);
	}

	.popup-select {
		cursor: pointer;
	}

	.popup-actions {
		display: flex;
		gap: 6px;
		padding: 8px 12px;
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(0, 0, 0, 0.2);
	}

	.popup-btn {
		flex: 1;
		padding: 6px 12px;
		border-radius: 6px;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		border: none;
	}

	.popup-btn-primary {
		background: #10b981;
		color: white;
	}

	.popup-btn-primary:hover:not(:disabled) {
		background: #059669;
	}

	.popup-btn-primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.popup-btn-secondary {
		background: rgba(255, 255, 255, 0.1);
		color: #d1d5db;
	}

	.popup-btn-secondary:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.15);
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
		font-size: 13px;
		color: #d1d5db;
		margin: 0;
		line-height: 1.5;
	}

	.popup-btn-danger {
		background: #ef4444;
		color: white;
	}

	.popup-btn-danger:hover:not(:disabled) {
		background: #dc2626;
	}
</style>

