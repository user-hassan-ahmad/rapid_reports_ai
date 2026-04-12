<script>
	import { createEventDispatcher } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { templatesStore } from '$lib/stores/templates';

	const dispatch = createEventDispatcher();

	export let template = null;

	let skillSheet = '';
	let chatHistory = [];
	let chatInput = '';
	let loading = false;
	let error = '';
	let saving = false;
	let hasChanges = false;

	$: if (template) {
		skillSheet = template.template_config?.skill_sheet || '';
		chatHistory = [];
		hasChanges = false;
		error = '';
	}

	async function postJson(path, body) {
		const headers = { 'Content-Type': 'application/json' };
		if ($token) headers['Authorization'] = `Bearer ${$token}`;
		const res = await fetch(`${API_URL}${path}`, {
			method: 'POST', headers, body: JSON.stringify(body)
		});
		const data = await res.json();
		if (!res.ok) throw new Error(data?.detail || `${res.status} ${res.statusText}`);
		return data;
	}

	async function sendMessage() {
		if (!chatInput.trim() || !skillSheet || loading) return;
		const msg = chatInput.trim();
		chatInput = '';

		chatHistory = [...chatHistory, { role: 'user', content: msg }];
		loading = true;
		error = '';

		try {
			const data = await postJson('/api/templates/skill-sheet/refine', {
				skill_sheet: skillSheet,
				message: msg,
				chat_history: chatHistory.slice(0, -1)
			});
			if (!data.success) throw new Error(data.error);
			skillSheet = data.skill_sheet;
			chatHistory = [...chatHistory, { role: 'assistant', content: data.response }];
			hasChanges = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			chatHistory = chatHistory.slice(0, -1);
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	async function saveChanges() {
		if (!hasChanges || !template?.id) return;
		saving = true;
		error = '';
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;

			const updatedConfig = { ...template.template_config, skill_sheet: skillSheet };

			// Re-extract coverage sections
			try {
				const covData = await postJson('/api/templates/skill-sheet/extract-coverage', {
					skill_sheet: skillSheet
				});
				if (covData.success && covData.sections) {
					updatedConfig.coverage_sections = covData.sections;
				}
			} catch { /* keep existing coverage_sections */ }

			const res = await fetch(`${API_URL}/api/templates/${template.id}`, {
				method: 'PUT',
				headers,
				body: JSON.stringify({
					name: template.name,
					tags: template.tags,
					template_config: updatedConfig
				})
			});
			const data = await res.json();
			if (data.success) {
				hasChanges = false;
				await templatesStore.refreshTemplates();
				dispatch('saved');
			} else {
				throw new Error(data.error || 'Save failed');
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	function handleClose() {
		if (hasChanges && !confirm('You have unsaved refinements. Discard?')) return;
		dispatch('close');
	}
</script>

{#if template}
	<div class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center"
		transition:fade={{ duration: 150 }}>
		<div class="bg-gray-950 border border-white/10 rounded-2xl shadow-2xl w-full max-w-xl mx-4 flex flex-col"
			style="max-height: 80vh;"
			transition:fly={{ y: 20, duration: 200 }}>

			<!-- Header -->
			<div class="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] shrink-0">
				<div class="min-w-0">
					<h2 class="text-base font-semibold text-white truncate">Refine: {template.name}</h2>
					<p class="text-xs text-gray-500 mt-0.5">Describe what you'd like to change about your template</p>
				</div>
				<button class="text-gray-500 hover:text-gray-300 transition-colors p-1" on:click={handleClose}>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<!-- Chat messages -->
			<div class="flex-1 overflow-y-auto px-5 py-4 space-y-3 min-h-[200px]">
				{#if chatHistory.length === 0}
					<div class="text-center py-8">
						<p class="text-sm text-gray-500">Tell me what to change — a rule to add, terminology to adjust, a convention to encode.</p>
						<div class="flex flex-wrap justify-center gap-2 mt-4">
							{#each [
								'Always include Clinical Correlation in the impression',
								'Use "thrombus" not "filling defect"',
								'Single sentence impression for normal studies'
							] as hint}
								<button class="text-xs px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:text-white hover:border-purple-500/30 transition-all"
									on:click={() => { chatInput = hint; }}>
									{hint}
								</button>
							{/each}
						</div>
					</div>
				{/if}

				{#each chatHistory as msg}
					<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
						<div class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm
							{msg.role === 'user'
								? 'bg-purple-600/20 border border-purple-500/20 text-purple-100'
								: 'bg-white/[0.04] border border-white/[0.06] text-gray-300'}">
							{msg.content}
						</div>
					</div>
				{/each}

				{#if loading}
					<div class="flex justify-start">
						<div class="bg-white/[0.04] border border-white/[0.06] rounded-xl px-3.5 py-2.5">
							<div class="flex items-center gap-1.5">
								<div class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-bounce" style="animation-delay: 0ms"></div>
								<div class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-bounce" style="animation-delay: 150ms"></div>
								<div class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-bounce" style="animation-delay: 300ms"></div>
							</div>
						</div>
					</div>
				{/if}
			</div>

			{#if error}
				<div class="px-5 pb-2">
					<p class="text-xs text-red-400">{error}</p>
				</div>
			{/if}

			<!-- Input + actions -->
			<div class="px-5 pb-4 pt-2 border-t border-white/[0.06] shrink-0 space-y-3">
				<div class="flex items-end gap-2">
					<textarea
						class="input-dark flex-1 resize-none text-sm"
						rows="2"
						bind:value={chatInput}
						on:keydown={handleKeydown}
						placeholder="e.g. Always mention lymph node stations by name..."
						disabled={loading}
					></textarea>
					<button
						class="px-4 py-2 rounded-lg text-sm font-medium bg-purple-600/80 hover:bg-purple-600 text-white transition-colors disabled:opacity-40"
						on:click={sendMessage}
						disabled={loading || !chatInput.trim()}>
						Send
					</button>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-[11px] text-gray-600">
						{#if hasChanges}Unsaved changes{:else}No changes{/if}
					</span>
					<div class="flex items-center gap-2">
						<button class="text-xs text-gray-500 hover:text-gray-300 transition-colors" on:click={handleClose}>
							{hasChanges ? 'Discard' : 'Close'}
						</button>
						{#if hasChanges}
							<button
								class="px-4 py-1.5 rounded-lg text-xs font-medium bg-purple-600/80 hover:bg-purple-600 text-white transition-colors disabled:opacity-40 flex items-center gap-1.5"
								on:click={saveChanges}
								disabled={saving}>
								{#if saving}
									<div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
								{/if}
								Save to template
							</button>
						{/if}
					</div>
				</div>
			</div>
		</div>
	</div>
{/if}
