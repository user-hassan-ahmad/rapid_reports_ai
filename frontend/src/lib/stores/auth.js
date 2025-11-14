import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { API_URL } from '$lib/config';

// Auth state stores
export const user = writable(null);
export const token = writable(null);
export const isAuthenticated = writable(false);

// Initialize from localStorage
if (browser) {
	const storedToken = localStorage.getItem('token');
	if (storedToken) {
		token.set(storedToken);
		// Don't set isAuthenticated until we verify the token
		// Fetch user data - will set isAuthenticated on success
		fetchUserData(storedToken).then(() => {
			// Only set authenticated if fetchUserData succeeded
			// (it will set user, which indicates success)
			// We check the user store via reactive statement
		}).catch(() => {
			// If fetch fails, keep token but don't auto-logout
			// User can try logging in again
		});
	}
}

async function fetchUserData(authToken) {
	try {
		const res = await fetch(`${API_URL}/api/auth/me`, {
			headers: { 'Authorization': `Bearer ${authToken}` }
		});
		
		if (res.ok) {
			const data = await res.json();
			if (data.success && data.user) {
				user.set(data.user);
				isAuthenticated.set(true); // Only set authenticated on success
				return; // Success
			}
		}
		// Only logout if token is clearly invalid (401/403)
		if (res.status === 401 || res.status === 403) {
			console.log('Token invalid or expired, clearing token');
			// Clear token but don't fully logout (keep them on the page)
			localStorage.removeItem('token');
			token.set(null);
			isAuthenticated.set(false);
		} else {
			console.warn('Failed to fetch user data but token may still be valid:', res.status);
			// Don't logout on other errors - might be temporary server issue
		}
	} catch (err) {
		console.error('Failed to fetch user:', err);
		// Don't auto-logout on network errors - server might be temporarily unreachable
		// User can still try to login manually
	}
}

export function login(authToken) {
	if (!browser) {
		console.log('⚠️ login() called in SSR context, skipping');
		return;
	}
	
	console.log('🔐 auth.login() called');
	localStorage.setItem('token', authToken);
	token.set(authToken);
	isAuthenticated.set(true);
	console.log('✅ isAuthenticated set to true, token stored');
	fetchUserData(authToken);
}

export function logout() {
	if (!browser) return;
	
	localStorage.removeItem('token');
	token.set(null);
	user.set(null);
	isAuthenticated.set(false);
}

