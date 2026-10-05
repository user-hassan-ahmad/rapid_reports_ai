<script lang="ts">
	/**
	 * A small in-app confirmation (never window.confirm). Cancel takes focus first, Escape and a backdrop click
	 * cancel. History "Open" uses it before replacing a tab that holds unsaved work (lib/utils/confirmGate).
	 */
	import { tick } from 'svelte';

	let {
		open,
		title,
		message,
		confirmLabel = 'Continue',
		cancelLabel = 'Cancel',
		onConfirm,
		onCancel
	}: {
		open: boolean;
		title: string;
		message: string;
		confirmLabel?: string;
		cancelLabel?: string;
		onConfirm: () => void;
		onCancel: () => void;
	} = $props();

	let cancelBtn = $state<HTMLButtonElement | null>(null);

	$effect(() => {
		if (open) void tick().then(() => cancelBtn?.focus());
	});

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onCancel();
		}
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
	<div
		class="fixed inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
		style="z-index: 10050;"
		onclick={(e) => {
			if (e.target === e.currentTarget) onCancel();
		}}
		onkeydown={onKey}
	>
		<div
			role="alertdialog"
			aria-modal="true"
			aria-labelledby="confirm-dialog-title"
			aria-describedby="confirm-dialog-message"
			class="w-full max-w-sm rounded-xl border border-white/10 bg-gray-900/95 p-5 shadow-2xl"
		>
			<h2 id="confirm-dialog-title" class="text-base font-semibold text-white">{title}</h2>
			<p id="confirm-dialog-message" class="mt-2 text-sm text-gray-300">{message}</p>
			<div class="mt-4 flex justify-end gap-2">
				<button
					type="button"
					bind:this={cancelBtn}
					onclick={onCancel}
					class="rounded-lg px-3 py-1.5 text-sm text-gray-300 hover:bg-white/5">{cancelLabel}</button
				>
				<button
					type="button"
					onclick={onConfirm}
					class="rounded-lg bg-red-600/80 px-3 py-1.5 text-sm text-white hover:bg-red-500">{confirmLabel}</button
				>
			</div>
		</div>
	</div>
{/if}
