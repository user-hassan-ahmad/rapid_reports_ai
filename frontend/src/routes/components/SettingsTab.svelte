<script>
	import { onMount, createEventDispatcher } from 'svelte';
	import { token, user } from '$lib/stores/auth';
	import { settingsStore } from '$lib/stores/settings';
	import { streamingMode } from '$lib/stores/dictation';
	import { API_URL } from '$lib/config';
	
	const dispatch = createEventDispatcher();
	
	let fullName = '';
	let signature = '';
	let autoSave;      // Don't initialize - let it be undefined initially
	let loading = false;
	let message = '';
	let messageType = ''; // 'success' or 'error'
	
	// API Keys (don't populate from server for security) - only Deepgram is user-configurable
	let deepgramApiKey = '';
	let hasDeepgramKey = false;
	
	// Subscribe to settings store
	$: settingsLoading = $settingsStore ? $settingsStore.loading : true;
	
	// Update local state from store
	$: {
		const settings = $settingsStore.settings;
		if (settings) {
			fullName = settings.full_name || '';
			signature = settings.signature || '';
			autoSave = settings.auto_save !== undefined ? settings.auto_save : true;
			hasDeepgramKey = settings.has_deepgram_key || false;
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
				auto_save: autoSave,
				// Only send API key if user has entered a value (non-empty)
				// Omit entirely if empty to avoid deleting existing key
				deepgram_api_key: deepgramApiKey && deepgramApiKey.trim() ? deepgramApiKey.trim() : undefined
			};
			
			const result = await settingsStore.updateSettings(payload);
			
			if (result.success) {
				message = 'Settings saved successfully!';
				messageType = 'success';
				// Clear API key field after successful save (don't keep it in memory)
				deepgramApiKey = '';
				// Dispatch event to parent
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

	async function clearApiKey() {
		if (!confirm(`Are you sure you want to delete your Deepgram API key? This action cannot be undone.`)) {
			return;
		}

		loading = true;
		message = '';
		messageType = '';

		try {
			// Set the key to empty string to delete it
			const payload = {
				deepgram_api_key: ''
			};

			const result = await settingsStore.updateSettings(payload);

			if (result.success) {
				message = `Deepgram API key deleted successfully.`;
				messageType = 'success';
				// Dispatch event to parent
				dispatch('settingsUpdated', {
					auto_save: autoSave
				});
				setTimeout(() => {
					message = '';
					messageType = '';
				}, 3000);
			} else {
				message = result.error || `Failed to delete Deepgram API key`;
				messageType = 'error';
			}
		} catch (err) {
			message = `Failed to delete Deepgram API key. Please try again.`;
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

	onMount(async () => {
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

		<!-- API Keys -->
		<div class="card-dark">
			<h2 class="text-xl font-bold text-white mb-4">API Keys</h2>
			<p class="text-sm text-gray-400 mb-4">
				Configure your Deepgram API key to enable voice dictation features.
			</p>
			<div>
				<div class="flex items-center justify-between mb-2">
					<label for="deepgramApiKey" class="block text-sm font-medium text-gray-300">
						Deepgram API Key (Dictation)
						{#if hasDeepgramKey}
							<span class="ml-2 text-green-400 text-xs">✓ Configured</span>
						{/if}
					</label>
					{#if hasDeepgramKey}
						<button
							type="button"
							onclick={clearApiKey}
							disabled={loading}
							class="text-xs text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed"
							title="Delete API key"
						>
							Clear
						</button>
					{/if}
				</div>
				<input
					id="deepgramApiKey"
					type="password"
					bind:value={deepgramApiKey}
					placeholder={hasDeepgramKey ? "Enter new key to update..." : "..."}
					class="input-dark w-full"
				/>
				<p class="text-xs text-gray-500 mt-1">
					Optional: Get your API key from <a href="https://console.deepgram.com/" target="_blank" class="text-purple-400 hover:underline">Deepgram Console</a>
				</p>
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

				<!-- Dictation Mode Toggle -->
				<div class="flex items-center justify-between pt-2 border-t border-white/10">
					<div>
						<label for="streamingMode" class="block text-sm font-medium text-gray-300">
							Dictation Mode
							{#if !hasDeepgramKey}
								<span class="ml-2 text-yellow-400 text-xs">(Deepgram key required)</span>
							{/if}
						</label>
						<p class="text-sm text-gray-400 mt-1">
							<span class="font-medium">Streaming:</span> Real-time transcription as you speak<br/>
							<span class="font-medium">Batch:</span> Process entire recording for better formatting
						</p>
					</div>
					<label class="relative inline-flex items-center cursor-pointer {hasDeepgramKey ? '' : 'opacity-50 cursor-not-allowed'}">
						<input
							type="checkbox"
							id="streamingMode"
							bind:checked={$streamingMode}
							disabled={!hasDeepgramKey}
							class="sr-only peer"
						/>
						<div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-600"></div>
						<span class="ml-3 text-sm text-gray-300">{$streamingMode ? 'Streaming' : 'Batch'}</span>
					</label>
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
