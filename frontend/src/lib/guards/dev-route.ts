/**
 * Guard for dev-only routes (stress-test surfaces, skill-sheet proto pages,
 * eval dashboards). Throws a 404 from a SvelteKit load function unless the
 * PUBLIC_ENABLE_DEV_ROUTES build-time env var is set to "true".
 *
 * Production builds omit the flag → routes 404 → end users cannot reach them
 * even by direct URL. Dev/staging set `PUBLIC_ENABLE_DEV_ROUTES=true` in
 * their `.env` to retain access.
 *
 * Usage in a route:
 *   // src/routes/<dev-route>/+page.ts
 *   import { requireDevRoute } from '$lib/guards/dev-route';
 *   export const load = () => requireDevRoute();
 */

import { error } from '@sveltejs/kit';

export function requireDevRoute(): void {
	if (import.meta.env.PUBLIC_ENABLE_DEV_ROUTES !== 'true') {
		error(404, 'Not Found');
	}
}
