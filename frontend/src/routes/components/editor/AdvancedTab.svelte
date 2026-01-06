<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	function handleChange() {
		dispatch('change');
	}
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">Advanced Configuration</h3>
	<p class="text-gray-400 text-sm mb-6">
		Advanced template settings and configuration options.
	</p>

	<div class="space-y-6">
		<!-- Placeholder for future advanced settings -->
		<div class="card-dark p-4 bg-blue-600/10 border-blue-600/30">
			<p class="text-sm text-gray-400 text-center py-4">
				Section configuration has been moved to the Quick Edit tab for easier access.
			</p>
		</div>
	</div>
</div>

