import { writable, derived } from 'svelte/store';
import type { UnfilledItems, UnfilledItem } from '../utils/placeholderDetection';

export interface UnfilledEdit {
	itemId: string;
	originalText: string;
	newValue: string;
	type: 'measurement' | 'variable' | 'alternative' | 'instruction';
	context: string;
	position?: number; // Position in original report for accurate replacement
}

export interface UnfilledEditorState {
	items: UnfilledItems;
	edits: Map<string, UnfilledEdit>;
	currentStep: number; // For wizard
	aiTips: Map<string, string>; // Cached AI tips
	mode: 'wizard' | 'list' | null;
}

function createUnfilledEditor() {
	const { subscribe, set, update } = writable<UnfilledEditorState>({
		items: { measurements: [], variables: [], alternatives: [], instructions: [], total: 0 },
		edits: new Map(),
		currentStep: 0,
		aiTips: new Map(),
		mode: null
	});

	return {
		subscribe,
		initialize: (items: UnfilledItems) => {
			update(state => ({
				...state,
				items,
				edits: new Map(),
				currentStep: 0,
				mode: null
			}));
		},
		setEdit: (itemId: string, edit: UnfilledEdit) => {
			update(state => {
				const newEdits = new Map(state.edits);
				newEdits.set(itemId, edit);
				return { ...state, edits: newEdits };
			});
		},
		removeEdit: (itemId: string) => {
			update(state => {
				const newEdits = new Map(state.edits);
				newEdits.delete(itemId);
				return { ...state, edits: newEdits };
			});
		},
		setAITip: (itemId: string, tip: string) => {
			update(state => {
				const newTips = new Map(state.aiTips);
				newTips.set(itemId, tip);
				return { ...state, aiTips: newTips };
			});
		},
		nextStep: () => {
			update(state => ({ ...state, currentStep: state.currentStep + 1 }));
		},
		previousStep: () => {
			update(state => ({ ...state, currentStep: Math.max(0, state.currentStep - 1) }));
		},
		setStep: (step: number) => {
			update(state => ({ ...state, currentStep: step }));
		},
		setMode: (mode: 'wizard' | 'list' | null) => {
			update(state => ({ ...state, mode }));
		},
		reset: () => {
			set({
				items: { measurements: [], variables: [], alternatives: [], instructions: [], total: 0 },
				edits: new Map(),
				currentStep: 0,
				aiTips: new Map(),
				mode: null
			});
		}
	};
}

export const unfilledEditor = createUnfilledEditor();

// Derived store for flattened items list
export const allUnfilledItems = derived(unfilledEditor, ($state) => {
	const items: Array<UnfilledItem & { id: string }> = [];
	
	$state.items.measurements.forEach((item, idx) => {
		items.push({ ...item, id: `measurement-${idx}-${item.index}` });
	});
	$state.items.variables.forEach((item, idx) => {
		items.push({ ...item, id: `variable-${idx}-${item.index}` });
	});
	$state.items.alternatives.forEach((item, idx) => {
		items.push({ ...item, id: `alternative-${idx}-${item.index}` });
	});
	$state.items.instructions.forEach((item, idx) => {
		items.push({ ...item, id: `instruction-${idx}-${item.index}` });
	});
	
	// Sort by position in report
	return items.sort((a, b) => a.index - b.index);
});

// Derived store for edit count
export const editCount = derived(unfilledEditor, ($state) => {
	return $state.edits.size;
});

