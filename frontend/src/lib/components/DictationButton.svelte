<script>
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { streamingMode as streamingModeStore } from '$lib/stores/dictation';
	import { token } from '$lib/stores/auth';

	export let bindText = ''; // Bound to textarea value
	export let disabled = false;
	export let isRecording = false; // Expose recording state for parent styling (bindable)
	export let disabledReason = ''; // Optional reason for being disabled (for tooltip)

	let internalIsRecording = false;
	let isConnecting = false;
	let isProcessing = false; // For pre-recorded mode
	
	// Sync internal state with exported prop (reactive)
	// Update exported prop whenever internal state changes
	$: if (internalIsRecording !== isRecording) {
		isRecording = internalIsRecording;
	}
	let error = null;
	let mediaRecorder = null;
	let stream = null;
	let websocket = null;
	let audioChunks = []; // For pre-recorded mode
	
	// Streaming mode variables
	let lastFinalTranscript = ''; // Only finalized segments
	let currentInterim = ''; // Current interim segment

	/**
	 * Toggle recording on/off
	 */
	async function toggleRecording() {
		if (isRecording) {
			stopRecording();
		} else {
			await startRecording();
		}
	}

	/**
	 * Start recording (both modes)
	 */
	async function startRecording() {
		try {
			error = null;
			isConnecting = true;
			audioChunks = [];

			// Request microphone access
			stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			
			// Create MediaRecorder with audio/webm
			const mimeType = 'audio/webm';
			if (!MediaRecorder.isTypeSupported(mimeType)) {
				error = 'WebM audio not supported in this browser';
				return;
			}

			mediaRecorder = new MediaRecorder(stream, { mimeType });
			
			// Store the current text before starting dictation
			lastFinalTranscript = bindText;
			currentInterim = '';

			if ($streamingModeStore) {
				await startStreamingMode();
			} else {
				await startPreRecordedMode();
			}
		} catch (err) {
			error = (err instanceof Error ? err.message : 'Failed to start recording') || 'Failed to start recording';
			isConnecting = false;
			cleanup();
		}
	}

	/**
	 * Start streaming mode (original implementation)
	 */
	async function startStreamingMode() {
		// Initialize WebSocket connection with token if available
		let wsUrl = 'ws://localhost:8000/api/transcribe';
		if ($token) {
			wsUrl += `?token=${encodeURIComponent($token)}`;
		}
		websocket = new WebSocket(wsUrl);

		// Handle WebSocket open
		websocket.onopen = () => {
			internalIsRecording = true;
			isConnecting = false;
			mediaRecorder.start(250); // Send audio chunks every 250ms
		};

		// Handle WebSocket messages (transcripts)
		websocket.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				
				if (data.error) {
					error = data.error;
					stopRecording();
					return;
				}
				
				if (data.transcript) {
					// Handle interim and final results
					if (data.is_final) {
						// Final result: add this to finalized transcript, replace any interim
						lastFinalTranscript += ' ' + data.transcript;
						currentInterim = ''; // Clear interim since we have final
						// Update bound text with only final transcript (no interim)
						bindText = lastFinalTranscript.trim();
					} else {
						// Interim result: REPLACE current interim with new one
						currentInterim = data.transcript;
						// Update bound text: lastFinalTranscript + current interim
						bindText = (lastFinalTranscript.trim() + ' ' + currentInterim).trim();
					}
				}
			} catch (e) {
				console.error('Error parsing WebSocket message:', e);
			}
		};

		// Handle WebSocket errors
		websocket.onerror = (err) => {
			error = 'Connection error';
			stopRecording();
		};

		// Handle WebSocket close
		websocket.onclose = () => {
			// Connection closed
		};

		// Handle MediaRecorder data available (streaming mode)
		mediaRecorder.ondataavailable = (event) => {
			if (event.data.size > 0 && websocket && websocket.readyState === WebSocket.OPEN) {
				websocket.send(event.data);
			}
		};

		// Add MediaRecorder error and stop handlers
		mediaRecorder.onerror = (err) => {
			error = 'MediaRecorder error';
			stopRecording();
		};
	}

	/**
	 * Start pre-recorded mode
	 */
	async function startPreRecordedMode() {
		internalIsRecording = true;
		isConnecting = false;
		
		// Collect audio chunks instead of streaming
		mediaRecorder.ondataavailable = (event) => {
			if (event.data.size > 0) {
				audioChunks.push(event.data);
			}
		};

		mediaRecorder.onerror = (err) => {
			error = 'MediaRecorder error';
			stopRecording();
		};

		// Start recording
		mediaRecorder.start(100); // Collect chunks every 100ms
	}

	/**
	 * Stop recording and cleanup
	 */
	async function stopRecording() {
		internalIsRecording = false;
		isConnecting = false;
		
		// Stop MediaRecorder
		if (mediaRecorder && mediaRecorder.state !== 'inactive') {
			mediaRecorder.stop();
		}
		
		// Stop media stream
		if (stream) {
			stream.getTracks().forEach(track => {
				track.stop();
			});
		}
		
		if ($streamingModeStore) {
			// Close WebSocket
			if (websocket) {
				websocket.close();
			}
			
			// Update final text - include any remaining interim text
			bindText = (lastFinalTranscript.trim() + ' ' + currentInterim).trim();
			currentInterim = '';
			lastFinalTranscript = '';
		} else {
			// Wait for MediaRecorder to stop and process audio
			// Wait a bit for ondataavailable to fire for final chunks
			await new Promise(resolve => setTimeout(resolve, 100));
			
			if (audioChunks.length > 0) {
				await processPreRecordedAudio();
			}
		}
	}

	/**
	 * Process pre-recorded audio and send to backend
	 */
	async function processPreRecordedAudio() {
		try {
			isProcessing = true;
			error = null;

			// Create audio blob from chunks
			const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
			
			// Create FormData to send audio
			const formData = new FormData();
			formData.append('audio', audioBlob, 'recording.webm');

			// Send to backend with authentication token
			const headers = {};
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const response = await fetch('http://localhost:8000/api/transcribe/pre-recorded', {
				method: 'POST',
				headers,
				body: formData
			});

			const result = await response.json();

			if (!response.ok) {
				throw new Error(result.detail || 'Failed to transcribe audio');
			}

			if (result.success && result.transcript) {
				// Append transcript to existing text
				const existingText = bindText.trim();
				const newText = result.transcript.trim();
				bindText = existingText ? `${existingText} ${newText}` : newText;
			} else {
				throw new Error('No transcript returned');
			}
		} catch (err) {
			error = (err instanceof Error ? err.message : 'Failed to process audio') || 'Failed to process audio';
			console.error('Error processing pre-recorded audio:', err);
		} finally {
			isProcessing = false;
			audioChunks = [];
		}
	}

	/**
	 * Cleanup resources
	 */
	function cleanup() {
		stopRecording();
	}

	// Cleanup on component destroy
	onDestroy(() => {
		cleanup();
	});
</script>

<div class="inline-flex flex-col gap-2">
	<!-- Dictation Button -->
	<button
		type="button"
		onclick={toggleRecording}
		disabled={disabled || isConnecting || isProcessing}
		class="p-2.5 text-white rounded-lg transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed
			{internalIsRecording 
				? 'bg-red-600 hover:bg-red-500 shadow-lg shadow-red-500/50 pulse-glow' 
				: 'bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 hover:shadow-lg hover:shadow-purple-500/50'}"
		title={disabled && disabledReason ? disabledReason : (isProcessing ? 'Processing...' : internalIsRecording ? 'Stop Recording' : 'Start Dictation')}
	>
		{#if isProcessing}
			<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
			</svg>
		{:else if internalIsRecording}
			<svg class="w-5 h-5 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
				<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 100-2 1 1 0 000 2zm7-1a1 1 0 11-2 0 1 1 0 012 0zm-9.536 5.879a1 1 0 001.415 0 1 1 0 000-1.415 1 1 0 00-1.415 0zm11.072 0a1 1 0 00-1.415-1.415 1 1 0 001.415 1.415zM10 12a1 1 0 01-1 1v1a1 1 0 102 0v-1a1 1 0 01-1-1zM9 1a1 1 0 000 2h2a1 1 0 100-2H9z"/>
			</svg>
		{:else}
			<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/>
			</svg>
		{/if}
	</button>
	
	{#if error}
		<p class="text-sm text-red-400">{error}</p>
	{/if}
</div>

<style>
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
	
	.animate-pulse {
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.animate-spin {
		animation: spin 1s linear infinite;
	}

	.pulse-glow {
		animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}
</style>
