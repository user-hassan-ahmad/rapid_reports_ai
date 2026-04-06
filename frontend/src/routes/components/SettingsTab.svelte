<script>
	import { onMount, createEventDispatcher } from 'svelte';
	import { token, user } from '$lib/stores/auth';
	import { settingsStore } from '$lib/stores/settings';
	import { API_URL } from '$lib/config';
	
	const dispatch = createEventDispatcher();
	
	let fullName = '';
	let signature = '';
	let autoSave;      // Don't initialize - let it be undefined initially
	/** When true, Copilot opens automatically after report analysis (localStorage key copilotAutoOpen). */
	let copilotAutoOpen = true;
	let loading = false;
	let message = '';
	let messageType = ''; // 'success' or 'error'
	
	// Subscribe to settings store
	$: settingsLoading = $settingsStore ? $settingsStore.loading : true;
	
	// Update local state from store
	$: {
		const settings = $settingsStore.settings;
		if (settings) {
			fullName = settings.full_name || '';
			signature = settings.signature || '';
			autoSave = settings.auto_save !== undefined ? settings.auto_save : true;
		}
	}

	async function saveSettings() {
		loading = true;
		message = '';
		messageType = '';
		
		try {
			const payload = {
				full_name: fullName,
				signature: signature,
				auto_save: autoSave
			};
			
			const result = await settingsStore.updateSettings(payload);
			
			if (result.success) {
				message = 'Settings saved successfully!';
				messageType = 'success';
				dispatch('settingsUpdated', {
					auto_save: autoSave
				});
				setTimeout(() => {
					message = '';
					messageType = '';
				}, 3000);
			} else {
				message = result.error || 'Failed to save settings';
				messageType = 'error';
			}
		} catch (err) {
			message = 'Failed to save settings. Please try again.';
			messageType = 'error';
		} finally {
			loading = false;
		}
	}

	function handleFormKeyDown(e) {
		// Allow Enter to create new lines in textareas - don't interfere at all
		if (e.key === 'Enter' && e.target.tagName === 'TEXTAREA') {
			// Stop the event from bubbling to prevent form submission, but let textarea handle it
			e.stopPropagation();
			return;
		}
		// For other elements, prevent form submission on Enter
		if (e.key === 'Enter' && e.target.tagName !== 'BUTTON' && e.target.tagName !== 'TEXTAREA') {
			e.preventDefault();
		}
	}

	function readCopilotAutoOpen() {
		try {
			return typeof localStorage !== 'undefined' && localStorage.getItem('copilotAutoOpen') !== 'false';
		} catch {
			return true;
		}
	}

	function setCopilotAutoOpen(enabled) {
		copilotAutoOpen = enabled;
		try {
			if (enabled) localStorage.removeItem('copilotAutoOpen');
			else localStorage.setItem('copilotAutoOpen', 'false');
		} catch {
			/* ignore */
		}
	}

	onMount(async () => {
		copilotAutoOpen = readCopilotAutoOpen();
		// Load settings if empty
		if (!$settingsStore.settings) {
			await settingsStore.loadSettings();
		}
	});
</script>

<div class="p-6">
	<div class="flex items-center gap-3 mb-6">
		<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
		</svg>
		<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Settings</h1>
	</div>
	
	{#if settingsLoading}
		<div class="flex items-center justify-center py-12">
			<div class="text-gray-400">Loading settings...</div>
		</div>
	{:else}
		{#if message}
			<div class="mb-6 p-4 rounded-lg border {messageType === 'success' ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}">
				{message}
			</div>
		{/if}

	<form onsubmit={(e) => { e.preventDefault(); saveSettings(); }} onkeydown={handleFormKeyDown} class="space-y-6 max-w-2xl">
		<!-- User Information -->
		<div class="card-dark">
			<h2 class="text-xl font-bold text-white mb-4">User Information</h2>
			<div class="space-y-4">
				<div>
					<label for="fullName" class="block text-sm font-medium text-gray-300 mb-2">
						Full Name
					</label>
					<input
						id="fullName"
						type="text"
						bind:value={fullName}
						placeholder="Enter your full name"
						class="input-dark w-full"
					/>
				</div>

				<div>
					<label for="signature" class="block text-sm font-medium text-gray-300 mb-2">
						Signature for Reports
					</label>
					<p class="text-sm text-gray-400 mb-2">
						This signature will be automatically added to all generated reports. You can include credentials, GMC number, etc.
					</p>
					<textarea
						id="signature"
						bind:value={signature}
						placeholder="e.g., Dr John Smith (FRCR, GMC 1234567)"
						rows="3"
						class="input-dark w-full"
					></textarea>
				</div>
			</div>
		</div>

		<!-- Application Preferences -->
		<div class="card-dark">
			<h2 class="text-xl font-bold text-white mb-4">Application Preferences</h2>
			<div class="space-y-4">
				<div class="flex items-start space-x-3">
					<input
						type="checkbox"
						id="autoSave"
						bind:checked={autoSave}
						disabled={settingsLoading}
						class="mt-1 w-5 h-5 rounded border-white/20 bg-black/50 text-purple-600 focus:ring-purple-500"
					/>
					<div>
						<label for="autoSave" class="block text-sm font-medium text-gray-300">
							Auto-save Reports
						</label>
						<p class="text-sm text-gray-400 mt-1">
							Automatically save generated reports to your history
						</p>
					</div>
				</div>

				<div class="flex items-start space-x-3 pt-2 border-t border-white/10">
					<input
						type="checkbox"
						id="copilotAutoOpen"
						checked={copilotAutoOpen}
						onchange={(e) => setCopilotAutoOpen(e.currentTarget.checked)}
						disabled={settingsLoading}
						class="mt-1 w-5 h-5 rounded border-white/20 bg-black/50 text-purple-600 focus:ring-purple-500"
					/>
					<div>
						<label for="copilotAutoOpen" class="block text-sm font-medium text-gray-300">
							Auto-open Copilot after report analysis
						</label>
						<p class="text-sm text-gray-400 mt-1">
							Opens the Copilot panel when guidelines finish loading for a new report
						</p>
					</div>
				</div>
			</div>
		</div>

		<!-- About -->
		<div class="card-dark">
			<h2 class="text-xl font-bold text-white mb-4">About</h2>
			<div class="space-y-3">
				<div class="text-sm text-gray-300">
					<p class="mb-2">© 2026 H&A LABS LTD | Company No. 16114480</p>
					<p class="text-gray-400">RadFlow is a product of H&A LABS LTD</p>
				</div>
			</div>
		</div>

		<div class="flex justify-end gap-3">
			<button
				type="submit"
				disabled={loading}
				class="btn-primary"
			>
				{loading ? 'Saving...' : 'Save Settings'}
			</button>
		</div>
	</form>
	{/if}
</div>
