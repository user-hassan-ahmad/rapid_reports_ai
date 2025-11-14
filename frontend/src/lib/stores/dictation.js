import { writable } from 'svelte/store';
import { browser } from '$app/environment';

// Default to streaming mode
const defaultMode = true; // true = streaming, false = batch

// Create store and initialize from localStorage if available
export const streamingMode = writable(defaultMode);

if (browser) {
	// Load from localStorage on init
	const stored = localStorage.getItem('dictationMode');
	if (stored !== null) {
		streamingMode.set(stored === 'streaming');
	}
	
	// Save to localStorage whenever it changes
	streamingMode.subscribe(mode => {
		localStorage.setItem('dictationMode', mode ? 'streaming' : 'batch');
	});
}

