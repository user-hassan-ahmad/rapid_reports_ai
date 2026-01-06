<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	function selectMethod(method: string) {
		dispatch('methodSelected', method);
	}
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">How would you like to create this template?</h3>
	<p class="text-gray-400 text-sm mb-6">
		Choose your preferred method for creating the template.
	</p>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
		<!-- Wizard Method -->
		<div
			class="card-dark cursor-pointer transition-all hover:border-purple-500/50 hover:shadow-lg hover:shadow-purple-500/20"
			onclick={() => selectMethod('wizard')}
			role="button"
			tabindex="0"
			onkeydown={(e) => e.key === 'Enter' && selectMethod('wizard')}
		>
			<div class="flex items-start gap-4">
				<div class="text-3xl">🔧</div>
				<div class="flex-1">
					<h4 class="text-lg font-semibold text-white mb-2">Build with Wizard</h4>
					<p class="text-gray-400 text-sm mb-3">
						Configure sections step by step
					</p>
					<ul class="text-sm text-gray-400 space-y-1 mb-4">
						<li>✓ Choose which sections to include</li>
						<li>✓ Design FINDINGS structure</li>
						<li>✓ Customize styling</li>
					</ul>
					<button class="btn-primary w-full">
						Select →
					</button>
				</div>
			</div>
		</div>

		<!-- From Reports Method -->
		<div
			class="card-dark transition-all relative opacity-60 cursor-not-allowed"
			role="button"
			aria-disabled="true"
		>
			<!-- Coming Soon Banner -->
			<div class="absolute top-0 right-0 -mt-2 -mr-2">
				<div class="bg-gradient-to-r from-purple-600 to-pink-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-lg flex items-center gap-1.5">
					<svg class="w-3 h-3 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
						<path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z"/>
					</svg>
					<span>Coming Soon</span>
				</div>
			</div>
			<div class="flex items-start gap-4">
				<div class="text-3xl">📄</div>
				<div class="flex-1">
					<h4 class="text-lg font-semibold text-white mb-2">From Past Reports</h4>
					<p class="text-gray-400 text-sm mb-3">
						Paste examples and AI analyzes
					</p>
					<ul class="text-sm text-gray-400 space-y-1 mb-4">
						<li>✓ Paste 2-10 example reports</li>
						<li>✓ AI extracts your style</li>
						<li>✓ Review and refine</li>
					</ul>
					<button class="btn-primary w-full opacity-50 cursor-not-allowed" disabled>
						Select →
					</button>
				</div>
			</div>
		</div>
	</div>
</div>

