<script>
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { streamingMode as streamingModeStore } from '$lib/stores/dictation';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';

	export let bindText = ''; // Bound to textarea value
	export let textareaElement = null; // Reference to textarea element for cursor insertion
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
	let currentInterim = ''; // Current interim segment text from API
	let segmentStartPosition = -1; // Track where current speech segment started (for cumulative replacement)
	let segmentEndPosition = -1; // Track where segment ends (for replacing selected text)
	let lastInsertionPosition = 0; // Track where we last inserted text (for cursor-based insertion)
	let startedWithSelection = false; // Track if dictation started with text selected

	/**
	 * Check if we're at a sentence boundary (should capitalize)
	 * Only capitalize at true sentence starts, not mid-sentence insertions
	 */
	function shouldCapitalizeFirstLetter(currentValue, insertPos) {
		// At start of text - always capitalize
		if (insertPos === 0) return true;
		
		// Get text before insertion point
		const before = currentValue.substring(0, insertPos);
		
		// Trim trailing spaces to check what's actually there
		const trimmedBefore = before.trimEnd();
		
		// Empty after trimming - we're at start of a line (after newline)
		if (trimmedBefore.length === 0) return true;
		
		// Check if we're after sentence-ending punctuation
		// This handles: "word. " or "word." (with or without space)
		const sentenceEnders = /[.!?]$/;
		if (sentenceEnders.test(trimmedBefore)) return true;
		
		// Check if we're after a newline (new paragraph/section)
		// Look for newline at the end (after trimming spaces)
		const beforeNewline = before.replace(/\s+$/, ''); // Remove trailing spaces
		if (beforeNewline.endsWith('\n') || beforeNewline.endsWith('\n\n')) return true;
		
		// Otherwise, we're mid-sentence - don't capitalize
		return false;
	}

	/**
	 * Clean up text: remove spaces before punctuation, fix spacing issues
	 */
	function cleanTextSpacing(text) {
		if (!text) return text;
		
		// Remove spaces before punctuation marks
		// Pattern: space followed by punctuation (but not if punctuation is at start)
		let cleaned = text.replace(/\s+([.,!?;:])/g, '$1');
		
		// Remove multiple consecutive spaces
		cleaned = cleaned.replace(/\s{2,}/g, ' ');
		
		return cleaned;
	}

	/**
	 * Capitalize first letter of text if needed
	 * Also handles cases where text starts with punctuation followed by a word
	 * Only capitalizes at sentence boundaries, preserves Deepgram's capitalization otherwise
	 */
	function capitalizeIfNeeded(text, shouldCapitalize) {
		if (!text || text.length === 0) return text;
		
		// Only capitalize if we're at a sentence boundary
		if (!shouldCapitalize) {
			// Mid-sentence: force lowercase first letter (Deepgram may capitalize first word of each segment)
			// Find first letter (skip leading spaces/punctuation)
			const firstLetterIndex = text.search(/[a-zA-Z]/);
			if (firstLetterIndex !== -1) {
				const firstLetter = text.charAt(firstLetterIndex);
				if (firstLetter === firstLetter.toUpperCase()) {
					// Force lowercase for mid-sentence insertions
					return text.substring(0, firstLetterIndex) + 
					       firstLetter.toLowerCase() + 
					       text.substring(firstLetterIndex + 1);
				}
			}
			return text;
		}
		
		// Check if text starts with punctuation followed by a word (e.g., ". unusual")
		// In this case, capitalize the word after the punctuation
		const punctuationWordMatch = text.match(/^([\s.,!?;:]*)([a-zA-Z])/);
		if (punctuationWordMatch) {
			const beforeLetter = punctuationWordMatch[1];
			const firstLetter = punctuationWordMatch[2];
			return beforeLetter + firstLetter.toUpperCase() + text.substring(beforeLetter.length + 1);
		}
		
		// Find first letter (skip leading spaces/punctuation)
		const firstLetterIndex = text.search(/[a-zA-Z]/);
		if (firstLetterIndex === -1) return text;
		
		// Only capitalize if it's lowercase (preserve if already capitalized)
		const firstLetter = text.charAt(firstLetterIndex);
		if (firstLetter === firstLetter.toLowerCase()) {
			return text.substring(0, firstLetterIndex) + 
			       firstLetter.toUpperCase() + 
			       text.substring(firstLetterIndex + 1);
		}
		
		// Already capitalized, return as-is
		return text;
	}

	/**
	 * Check if we need to add spacing before text insertion
	 * Never add space before punctuation marks or if space already exists
	 */
	function needsSpacingBefore(currentValue, insertPos, textToInsert) {
		if (insertPos === 0) return false;
		
		// Never add space before punctuation marks
		const firstChar = textToInsert.trim().charAt(0);
		if (/[.,!?;:]/.test(firstChar)) return false;
		
		// Check if text already starts with a space
		if (textToInsert.startsWith(' ')) return false;
		
		// Check if there's already a space at insertion point
		const charAtPos = currentValue.charAt(insertPos - 1);
		if (charAtPos === ' ') return false; // Already has space
		
		const charBefore = currentValue.charAt(insertPos - 1);
		// Need space if previous char is a word character or punctuation (except spaces/newlines)
		return /[\w.,!?;:]/.test(charBefore);
	}

	/**
	 * Check if we need to add spacing after text insertion
	 */
	function needsSpacingAfter(currentValue, insertPos) {
		if (insertPos >= currentValue.length) return false;
		const charAfter = currentValue.charAt(insertPos);
		// Need space if next char is a word character
		return /[\w]/.test(charAfter);
	}

	/**
	 * Insert or replace text at cursor position
	 * Uses segmentStartPosition to replace cumulative transcripts from Deepgram
	 * Handles text selection (highlighted text) by replacing it
	 * Handles spacing and capitalization intelligently
	 */
	function insertTextAtCursor(text, replaceSegment = false) {
		if (!textareaElement) {
			// Fallback: append to end if no textarea reference
			bindText = bindText + (bindText && !bindText.endsWith(' ') ? ' ' : '') + text;
			return;
		}
		
		const currentValue = textareaElement.value;
		
		if (replaceSegment && segmentStartPosition >= 0) {
			// Replace entire segment from segmentStartPosition to lastInsertionPosition
			// Deepgram sends cumulative transcripts, so we replace everything from segment start
			const before = currentValue.substring(0, segmentStartPosition);
			const after = currentValue.substring(lastInsertionPosition);
			
			// Clean up spacing issues (remove spaces before punctuation)
			const cleanedText = cleanTextSpacing(text);
			
			// Add space before if needed (when inserting after existing text)
			// Never add space before punctuation marks or if space already exists
			// Check if before text already ends with space
			const beforeEndsWithSpace = before.endsWith(' ');
			const spaceBefore = (!beforeEndsWithSpace && segmentStartPosition > 0 && needsSpacingBefore(currentValue, segmentStartPosition, cleanedText)) ? ' ' : '';
			
			// Capitalize if needed (after sentence enders or newlines)
			// Check if text before segment ends with punctuation, or if replacement text starts with punctuation+word
			const beforeText = before.trimEnd();
			const endsWithPunctuation = /[.!?]$/.test(beforeText);
			const startsWithPunctuationWord = /^[\s]*[.!?]\s+[a-zA-Z]/.test(cleanedText);
			
			// Should capitalize if: before ends with punctuation, or we're at start, or after newline
			const shouldCapitalize = endsWithPunctuation || startsWithPunctuationWord || shouldCapitalizeFirstLetter(currentValue, segmentStartPosition);
			const processedText = capitalizeIfNeeded(cleanedText, shouldCapitalize);
			
			const newValue = before + spaceBefore + processedText + after;
			
			textareaElement.value = newValue;
			bindText = newValue;
			
			// Update insertion position
			lastInsertionPosition = segmentStartPosition + spaceBefore.length + processedText.length;
			
			// Restore cursor
			textareaElement.focus();
			textareaElement.setSelectionRange(lastInsertionPosition, lastInsertionPosition);
		} else {
			// New segment: always use CURRENT cursor/selection position
			// (stored state is only for replaceSegment=true cumulative replacement)
			let replaceStart, replaceEnd;
			
			// Always check current selection/cursor, ignore stored state
			const selectionStart = textareaElement.selectionStart;
			const selectionEnd = textareaElement.selectionEnd;
			const hasSelection = selectionStart !== selectionEnd;
			
			if (hasSelection) {
				// User has selected text - replace it
				replaceStart = selectionStart;
				replaceEnd = selectionEnd;
			} else {
				// No selection - insert at cursor position
				replaceStart = selectionStart;
				replaceEnd = selectionStart; // No replacement, just insert
			}
			
			// Replace selected text or insert at cursor
			const before = currentValue.substring(0, replaceStart);
			const after = currentValue.substring(replaceEnd);
			
			// Add space before if needed (check context before insertion point)
			// Apply spacing logic whether replacing selected text or inserting at cursor
			// Never add space before punctuation marks or if space already exists
			const beforeEndsWithSpace = before.endsWith(' ');
			const spaceBefore = (!beforeEndsWithSpace && replaceStart > 0 && needsSpacingBefore(currentValue, replaceStart, text)) ? ' ' : '';
			
			// Add space after if inserting before a word (and text doesn't end with punctuation)
			// Don't add space if after already starts with space
			const afterStartsWithSpace = after.startsWith(' ');
			const spaceAfter = (!afterStartsWithSpace && after.length > 0 && needsSpacingAfter(currentValue, replaceEnd) && !text.endsWith(' ') && !/[,.;:!?]/.test(text.slice(-1))) ? ' ' : '';
			
			// Clean up spacing issues (remove spaces before punctuation)
			const cleanedText = cleanTextSpacing(text);
			
			// Capitalize if needed (after sentence enders, newlines, or at start)
			// Check context at the insertion point - only capitalize at true sentence boundaries
			const shouldCapitalize = shouldCapitalizeFirstLetter(currentValue, replaceStart);
			const processedText = capitalizeIfNeeded(cleanedText, shouldCapitalize);
			
			const newValue = before + spaceBefore + processedText + spaceAfter + after;
			
			textareaElement.value = newValue;
			bindText = newValue;
			
			// Track where this segment started (for potential future replaceSegment=true calls)
			segmentStartPosition = replaceStart;
			lastInsertionPosition = replaceStart + spaceBefore.length + processedText.length + spaceAfter.length;
			
			// Restore cursor
			textareaElement.focus();
			textareaElement.setSelectionRange(lastInsertionPosition, lastInsertionPosition);
		}
	}

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
			
			// Store the current text and cursor/selection position before starting dictation
			lastFinalTranscript = bindText;
			currentInterim = '';
			
			// Capture selection/cursor position for dictation start
			// If text is selected, we'll replace it; otherwise insert at cursor
			if (textareaElement) {
				const selectionStart = textareaElement.selectionStart;
				const selectionEnd = textareaElement.selectionEnd;
				const hasSelection = selectionStart !== selectionEnd;
				
				if (hasSelection) {
					// Text is selected - we'll replace it, so track the selection range
					segmentStartPosition = selectionStart;
					segmentEndPosition = selectionEnd;
					lastInsertionPosition = selectionEnd;
					startedWithSelection = true;
				} else {
					// No selection - reset tracking, will use cursor position on first insert
					segmentStartPosition = -1;
					segmentEndPosition = -1;
					lastInsertionPosition = 0;
					startedWithSelection = false;
				}
			} else {
				// Fallback: reset tracking
				segmentStartPosition = -1;
				segmentEndPosition = -1;
				lastInsertionPosition = 0;
				startedWithSelection = false;
			}

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
		// Convert HTTP/HTTPS URL to WS/WSS
		const wsUrlBase = API_URL.replace(/^http/, 'ws');
		let wsUrl = `${wsUrlBase}/api/transcribe`;
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
					// Deepgram sends cumulative transcripts - each contains full text from segment start
					if (data.is_final) {
						// Final result: replace entire segment with final transcript
						if (segmentStartPosition >= 0) {
							// Replace the segment we've been building
							insertTextAtCursor(data.transcript, true);
						} else {
							// No segment started yet, insert at cursor with spacing
							// Check if we need space - don't add if already exists or before punctuation
							if (textareaElement) {
								const cursorPos = textareaElement.selectionStart;
								const charBefore = bindText.charAt(cursorPos - 1);
								const transcriptStartsWithPunctuation = /^[\s]*[.,!?;:]/.test(data.transcript);
								const needsSpace = cursorPos > 0 && charBefore !== ' ' && !/[.!?]/.test(charBefore) && !transcriptStartsWithPunctuation;
								const prefix = needsSpace ? ' ' : '';
								insertTextAtCursor(prefix + data.transcript, false);
							} else {
								// Fallback: check end of text
								const needsSpace = bindText && !bindText.trimEnd().endsWith(' ') && !/[.!?]/.test(bindText.trimEnd().slice(-1));
								const prefix = needsSpace ? ' ' : '';
								insertTextAtCursor(prefix + data.transcript, false);
							}
						}
						currentInterim = '';
						// Reset segment tracking for next segment
						segmentStartPosition = -1;
						// Track finalized text (for reference)
						lastFinalTranscript += ' ' + data.transcript;
					} else {
						// Interim result: replace current segment with new cumulative transcript
						if (segmentStartPosition >= 0) {
							// Replace the segment we've been building
							insertTextAtCursor(data.transcript, true);
						} else {
							// First interim: start new segment at cursor with spacing
							// Check if we need space - don't add if already exists or before punctuation
							if (textareaElement) {
								const cursorPos = textareaElement.selectionStart;
								const charBefore = bindText.charAt(cursorPos - 1);
								const transcriptStartsWithPunctuation = /^[\s]*[.,!?;:]/.test(data.transcript);
								const needsSpace = cursorPos > 0 && charBefore !== ' ' && !/[.!?]/.test(charBefore) && !transcriptStartsWithPunctuation;
								const prefix = needsSpace ? ' ' : '';
								insertTextAtCursor(prefix + data.transcript, false);
							} else {
								// Fallback: check end of text
								const needsSpace = bindText && !bindText.trimEnd().endsWith(' ') && !/[.!?]/.test(bindText.trimEnd().slice(-1));
								const prefix = needsSpace ? ' ' : '';
								insertTextAtCursor(prefix + data.transcript, false);
							}
						}
						currentInterim = data.transcript;
					}
				}
			} catch (e) {
				// Error parsing WebSocket message
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
			
			// Finalize any remaining interim text
			if (currentInterim && textareaElement) {
				// Replace interim with final version
				insertTextAtCursor(currentInterim, true);
			}
			
			currentInterim = '';
			lastFinalTranscript = '';
			segmentStartPosition = -1;
			segmentEndPosition = -1;
			lastInsertionPosition = 0;
			startedWithSelection = false;
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
			const response = await fetch(`${API_URL}/api/transcribe/pre-recorded`, {
				method: 'POST',
				headers,
				body: formData
			});

			const result = await response.json();

			if (!response.ok) {
				throw new Error(result.detail || 'Failed to transcribe audio');
			}

			if (result.success && result.transcript) {
				// Insert transcript at cursor position with intelligent spacing and capitalization
				if (textareaElement) {
					// Use insertTextAtCursor which handles spacing and capitalization intelligently
					// It will check for existing spaces and add spacing/capitalization as needed
					insertTextAtCursor(result.transcript.trim(), false);
				} else {
					// Fallback: append to end with spacing check
					const existingText = bindText.trim();
					const newText = result.transcript.trim();
					// Add space only if existing text doesn't end with space or punctuation
					const needsSpace = existingText && !existingText.endsWith(' ') && !/[.!?]/.test(existingText.slice(-1));
					bindText = existingText ? `${existingText}${needsSpace ? ' ' : ''}${newText}` : newText;
				}
			} else {
				throw new Error('No transcript returned');
			}
		} catch (err) {
			error = (err instanceof Error ? err.message : 'Failed to process audio') || 'Failed to process audio';
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
