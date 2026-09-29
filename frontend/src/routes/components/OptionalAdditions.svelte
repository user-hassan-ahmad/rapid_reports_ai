<script lang="ts">
	// Reporter-choice additions below a quick report: items the classifier judged could go
	// either way. Ticking one inserts its sentence into the IMPRESSION; unticking removes it.
	// Ticked state is read from the report text, so manual edits keep the boxes honest.
	import { createEventDispatcher } from 'svelte';
	import { isApplied, type ReportOption } from '$lib/utils/impressionOptions';

	export let options: ReportOption[] = [];
	export let content = '';
	export let disabled = false;

	const dispatch = createEventDispatcher<{ toggle: { option: ReportOption; checked: boolean } }>();

	$: groups = [
		{ label: 'Recommendations', items: options.filter((o) => o.kind === 'recommendation') },
		{ label: 'Impression', items: options.filter((o) => o.kind === 'impression') }
	].filter((g) => g.items.length);
</script>

{#if options.length}
	<div class="mt-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
		<div class="mb-2 flex items-baseline justify-between gap-2">
			<span class="text-xs font-semibold uppercase tracking-wide text-gray-300">Optional additions</span>
			<span class="text-[11px] text-gray-500">Reporter's choice — tick to add to the impression</span>
		</div>
		{#each groups as group (group.label)}
			<div class="mt-2">
				<div class="mb-1 text-[11px] font-medium text-gray-400">{group.label}</div>
				{#each group.items as option (option.id)}
					{@const checked = isApplied(content, option)}
					<label class="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-white/[0.05]" class:opacity-50={disabled}>
						<input
							type="checkbox"
							class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-purple-500"
							{checked}
							{disabled}
							onchange={(e) => dispatch('toggle', { option, checked: (e.currentTarget as HTMLInputElement).checked })}
						/>
						<span class="text-sm leading-snug text-gray-200">
							{option.sentence}
							{#if option.reason}<span class="block text-[11px] text-gray-500">{option.reason}</span>{/if}
						</span>
					</label>
				{/each}
			</div>
		{/each}
	</div>
{/if}
