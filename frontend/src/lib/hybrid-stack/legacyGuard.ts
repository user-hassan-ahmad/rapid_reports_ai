// Client mirror of the server tripwire (spec §9.5): while the stack is latched, any legacy URL is warned and counted
// (P3 reads the count from window.__legacyHits in dev). It never blocks: the request still goes out.
const LEGACY = [/\/api\/quick-report\/(analyse|generate)\b/, /\/api\/canvas\/sections(-from-template)?\b/,
	/\/api\/canvas\/review\b/, /\/api\/templates\/[^/]+\/(prepare|generate)\b/, /\/api\/reports\/[^/]+\/enhance\b/,
	/\/api\/audit\b/, /\/validation-status\b/];

export const legacyHits: string[] = [];

export function isLegacy(url: string, body?: string): boolean {
	if (LEGACY.some((r) => r.test(url))) return true;
	if (/\/api\/canvas\/process\b/.test(url)) return !!body && /"mode"\s*:\s*"structured"/.test(body);
	if (/\/api\/canvas\/bundle\b/.test(url)) return !!body && /"checklist"\s*:/.test(body);
	return false;
}

/** Wrap fetch once; `active` is read per call (the latched stack mode). Returns the uninstall function. */
export function installLegacyGuard(active: () => boolean): () => void {
	const orig = globalThis.fetch;
	const guarded = (input: RequestInfo | URL, init?: RequestInit) => {
		const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
		if (active() && isLegacy(url, typeof init?.body === 'string' ? init.body : undefined)) {
			legacyHits.push(url);
			console.warn('[legacy.call]', url);
		}
		return orig(input, init);
	};
	globalThis.fetch = guarded as typeof fetch;
	return () => {
		if (globalThis.fetch === guarded) globalThis.fetch = orig;
	};
}

let installed = false;
/** The app's one install (+layout): idempotent across HMR re-runs; `expose` puts the hits on window.__legacyHits. */
export function installAppLegacyGuard(active: () => boolean, expose: boolean): void {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	installLegacyGuard(active);
	if (expose) (window as unknown as { __legacyHits?: string[] }).__legacyHits = legacyHits;
}
