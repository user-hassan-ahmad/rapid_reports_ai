<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { highlightSyntax } from '$lib/utils/templateSyntaxHighlighting';

	const dispatch = createEventDispatcher();

	export let show: boolean = false;
	export let templateContent: string = '';

	function handleClose() {
		show = false;
		dispatch('close');
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			handleClose();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if show}
	<div 
		class="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
		onclick={handleClose}
		role="dialog"
		aria-modal="true"
		aria-labelledby="preview-title"
	>
	<div 
		class="bg-black/80 backdrop-blur-2xl rounded-xl border border-white/10 shadow-2xl shadow-purple-500/20 max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col"
		onclick={(e) => e.stopPropagation()}
	>
		<!-- Header -->
		<div class="flex items-center justify-between p-6 border-b border-white/10">
				<div>
					<h3 id="preview-title" class="text-xl font-bold text-white">Template Syntax Preview</h3>
					<p class="text-sm text-gray-400 mt-1">Color-coded to help you visualize placeholders</p>
				</div>
				<button 
					onclick={handleClose}
					class="text-gray-400 hover:text-white text-2xl leading-none"
					aria-label="Close preview"
				>
					×
				</button>
			</div>
			
		<!-- Legend -->
		<div class="px-6 py-4 border-b border-white/10">
				<h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">Legend:</h4>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
					<div class="flex items-center gap-2">
						<span class="highlight-measurement font-mono">xxx</span>
						<span class="text-gray-400">Measurements</span>
					</div>
					<div class="flex items-center gap-2">
						<span class="highlight-variable font-mono">{'{VAR}'}</span>
						<span class="text-gray-400">Variables</span>
					</div>
					<div class="flex items-center gap-2">
						<span class="highlight-instruction font-mono">//</span>
						<span class="text-gray-400">Actionable instructions for AI</span>
					</div>
					<div class="flex items-center gap-2">
						<span class="highlight-alternative font-mono">[opt1/opt2]</span>
						<span class="text-gray-400">Alternatives</span>
					</div>
				</div>
			</div>
			
			<!-- Preview Content -->
			<div class="flex-1 overflow-auto p-6">
				<pre class="font-mono text-sm leading-relaxed text-white whitespace-pre-wrap break-words">{@html highlightSyntax(templateContent)}</pre>
			</div>
			
		<!-- Footer -->
		<div class="px-6 py-4 border-t border-white/10 flex justify-end">
			<button 
				onclick={handleClose}
				class="px-4 py-2 bg-white/10 backdrop-blur-xl hover:bg-white/20 border border-white/10 text-white rounded-lg transition-all duration-200"
			>
					Close
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Syntax colors for preview modal */
	:global(.highlight-measurement) { color: #fbbf24; } /* Amber - xxx */
	:global(.highlight-variable) { color: #34d399; } /* Green - {VAR} */
	:global(.highlight-instruction) { color: #60a5fa; } /* Blue - // instruction */
	:global(.highlight-alternative) { color: #c084fc; } /* Purple - [opt1/opt2] */
</style>

