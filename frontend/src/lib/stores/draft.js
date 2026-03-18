import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

const STORAGE_KEY = 'rr_draft';
const DEBOUNCE_MS = 400;
const SCHEMA_VERSION = 3;

const EMPTY_STATE = {
	version: SCHEMA_VERSION,
	intelliTab: {
		clinicalHistory: '',
		scanType: '',
		prePoppedSections: [],
		scratchpadContent: ''
	},
	templateTab: {
		templateId: null,
		variables: {},
		prePoppedSections: [],
		scratchpadContent: ''
	},
	savedAt: null
};

function loadFromStorage() {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return null;
		const parsed = JSON.parse(raw);
		if (parsed.version !== SCHEMA_VERSION) {
			// Wipe stale schema — don't attempt to migrate
			localStorage.removeItem(STORAGE_KEY);
			return null;
		}
		return parsed;
	} catch {
		return null;
	}
}

function persistToStorage(draft) {
	if (!browser) return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
	} catch {
		// QuotaExceededError — silently fail, app still works
	}
}

function createDraftStore() {
	const { subscribe, set, update } = writable(loadFromStorage() ?? structuredClone(EMPTY_STATE));

	let intelliDebounce = null;
	let templateDebounce = null;

	return {
		subscribe,

		saveIntelliTab(clinicalHistory, scanType, prePoppedSections, scratchpadContent) {
			let latest;
			update((draft) => {
				latest = {
					...draft,
					intelliTab: { clinicalHistory, scanType, prePoppedSections: prePoppedSections ?? [], scratchpadContent },
					savedAt: Date.now()
				};
				return latest;
			});
			if (browser) {
				clearTimeout(intelliDebounce);
				intelliDebounce = setTimeout(() => persistToStorage(latest), DEBOUNCE_MS);
			}
		},

		saveTemplateTab(templateId, variables, prePoppedSections, scratchpadContent) {
			let latest;
			update((draft) => {
				latest = {
					...draft,
					templateTab: {
						templateId,
						variables: { ...variables },
						prePoppedSections: prePoppedSections ?? [],
						scratchpadContent: scratchpadContent ?? ''
					},
					savedAt: Date.now()
				};
				return latest;
			});
			if (browser) {
				clearTimeout(templateDebounce);
				templateDebounce = setTimeout(() => persistToStorage(latest), DEBOUNCE_MS);
			}
		},

		clearIntelliTab() {
			update((draft) => {
				const next = { ...draft, intelliTab: structuredClone(EMPTY_STATE.intelliTab) };
				// Only null out savedAt if the template tab is also empty
				if (!hasTemplateContent(next.templateTab)) next.savedAt = null;
				persistToStorage(next);
				return next;
			});
		},

		clearTemplateTab() {
			update((draft) => {
				const next = { ...draft, templateTab: structuredClone(EMPTY_STATE.templateTab) };
				if (!hasIntelliContent(next.intelliTab)) next.savedAt = null;
				persistToStorage(next);
				return next;
			});
		},

		clearAll() {
			set(structuredClone(EMPTY_STATE));
			if (browser) localStorage.removeItem(STORAGE_KEY);
		}
	};
}

function hasIntelliContent(intelliTab) {
	return (
		intelliTab?.clinicalHistory?.trim().length > 0 ||
		intelliTab?.scanType?.trim().length > 0 ||
		intelliTab?.scratchpadContent?.trim().length > 0
	);
}

function hasTemplateContent(templateTab) {
	return (
		!!templateTab?.templateId &&
		(Object.values(templateTab?.variables ?? {}).some((v) => String(v).trim().length > 0) ||
			(templateTab?.scratchpadContent ?? '').trim().length > 0)
	);
}

export const draftStore = createDraftStore();

export const hasIntelliDraft = derived(
	draftStore,
	($d) => !!$d.savedAt && hasIntelliContent($d.intelliTab)
);

export const hasTemplateDraft = derived(
	draftStore,
	($d) => !!$d.savedAt && hasTemplateContent($d.templateTab)
);
