import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { API_URL } from '$lib/config';
import { user, isAuthenticated } from '$lib/stores/auth';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ url, fetch }) => {
	// Only check auth on client-side (localStorage not available on server)
	if (!browser) {
		return {}; // Let server render, client will handle redirect
	}
	
	const token = localStorage.getItem('token');
	const isPublicRoute = [
		'/home',
		'/login',
		'/register',
		'/forgot-password',
		'/reset-password',
		'/verify-email',
		'/resend-verification',
		'/docs'
	].includes(url.pathname);
	
	// If no token and trying to access protected route
	if (!token && !isPublicRoute) {
		throw redirect(302, '/home');
	}
	
	// If token exists, verify it
	if (token) {
		try {
			const res = await fetch(`${API_URL}/api/auth/me`, {
				headers: { 'Authorization': `Bearer ${token}` }
			});
			
			if (res.ok) {
				const data = await res.json();
				if (data.success && data.user) {
					// Sync with auth store
					user.set(data.user);
					isAuthenticated.set(true);
					
					// Token valid - if on public route, redirect to main app (except /docs which is accessible to everyone)
					// Don't redirect if navigating to /docs - allow it for authenticated users
					if (isPublicRoute && url.pathname !== '/' && url.pathname !== '/docs') {
						throw redirect(302, '/');
					}
					return { user: data.user, authenticated: true };
				}
			}
			
			// Token invalid - clear it and redirect if on protected route
			if (res.status === 401 || res.status === 403) {
				localStorage.removeItem('token');
				user.set(null);
				isAuthenticated.set(false);
				if (!isPublicRoute) {
					throw redirect(302, '/home');
				}
			}
		} catch (err) {
			// Re-throw redirects (SvelteKit redirect() throws a special error)
			if (err && typeof err === 'object' && 'status' in err && (err as any).status >= 300 && (err as any).status < 400) {
				throw err;
			}
			// Network error - don't redirect, let client handle it
			// The auth store will handle this case
		}
	}
	
	return {};
};

