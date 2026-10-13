<script lang="ts" module>
	export type IconName = 'check' | 'clock' | 'search' | 'alert' | 'slash' | 'open' | 'dot' | 'exam' | 'warn' | 'info' | 'chev';
</script>

<script lang="ts">
	/** The card's small stroke icons (12–14 px, currentColor): one per action category plus the value marks.
	 *  Decorative: the text beside each icon carries the meaning. */
	let { name, size = 13 }: { name: IconName; size?: number } = $props();
</script>

<svg class="cp-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
	{#if name === 'check'}
		<path d="M5 12.5l4.5 4.5L19 7.5" />
	{:else if name === 'clock'}
		<circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" />
	{:else if name === 'search'}
		<circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5" />
	{:else if name === 'alert'}
		<path d="M12 3.5l9 16H3z" /><path d="M12 10v4" /><path d="M12 17.2v.1" />
	{:else if name === 'slash'}
		<circle cx="12" cy="12" r="8.5" /><path d="M6 18L18 6" />
	{:else if name === 'open'}
		<circle cx="12" cy="12" r="8.5" stroke-dasharray="3 3" />
	{:else if name === 'exam'}
		<rect x="4" y="5" width="16" height="14" rx="2" /><path d="M8 10h8M8 14h5" />
	{:else if name === 'chev'}
		<path d="M9 6l6 6-6 6" />
	{:else if name === 'info'}
		<circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5" /><path d="M12 7.6v.1" />
	{:else if name === 'warn'}
		<path d="M12 3.5l9 16H3z" /><path d="M12 10v4" /><path d="M12 17.2v.1" />
	{:else}
		<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />
	{/if}
</svg>

<style>
	.cp-icon {
		flex-shrink: 0;
		display: inline-block;
		vertical-align: -2px;
	}
</style>
