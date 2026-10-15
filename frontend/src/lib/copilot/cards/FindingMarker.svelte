<script lang="ts">
	/**
	 * The small numbered round marker that links a finding in the scratchpad to its group in the rail. The same
	 * component draws both ends. `n` is the finding's number (copilot/markers findingNumbers); `text` the full finding,
	 * kept as the title and the screen-reader name. `side` says which end it is (data attribute the connector reads).
	 */
	let { n, id, text, side, active = false, onHover = undefined }: {
		n: number;
		id: string;
		text: string;
		side: 'rail' | 'pad';
		active?: boolean;
		onHover?: (id: string | null) => void;
	} = $props();
	const data = $derived(side === 'rail' ? { 'data-finding-mark-rail': id } : { 'data-finding-mark': id });
</script>

<span
	class="fm"
	class:fm-active={active}
	role="img"
	aria-label={`Finding ${n}: ${text}`}
	title={text}
	{...data}
	onmouseenter={() => onHover?.(id)}
	onmouseleave={() => onHover?.(null)}>{n}</span
>

<style>
	.fm {
		display: inline-flex;
		flex: none;
		align-items: center;
		justify-content: center;
		box-sizing: border-box;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		border: 1px solid rgb(167 139 250 / 0.55);
		font-size: 0.625rem;
		line-height: 1;
		font-weight: 600;
		color: rgb(196 181 253);
		background: transparent;
		cursor: default;
	}
	.fm-active {
		background: rgb(167 139 250 / 0.25);
		border-color: rgb(167 139 250 / 0.9);
	}
</style>
