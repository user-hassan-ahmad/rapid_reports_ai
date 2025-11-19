<script>
	export let lines = 3;
	export let width = 'full';
	export let height = 'h-4';
	export let className = '';
</script>

<div class="space-y-2 {className}">
	{#each Array(lines) as _, i}
		<div 
			class="bg-gray-700/50 rounded animate-pulse {height}"
			style={width !== 'full' ? `width: ${width}` : 'width: 100%'}
		></div>
	{/each}
</div>

