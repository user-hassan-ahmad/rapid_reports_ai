import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent }) => {
	// Only check on client-side
	if (!browser) {
		return {};
	}

	// Get auth state from layout
	const layoutData = await parent();
	
	// Check token synchronously to redirect immediately before page renders
	const token = localStorage.getItem('token');
	
	if (!token) {
		// No token - redirect to home immediately (before page component renders)
		throw redirect(302, '/home');
	}
	
	// If token exists, let the page component handle the loading state
	// The layout will verify the token and set isAuthenticated
	return {};
};
