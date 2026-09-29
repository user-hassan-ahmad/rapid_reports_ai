/**
 * Live ghost text (lab): Deepgram's interim words drawn in grey at the end of the document
 * while you speak, replaced by the faded final when it arrives. Display only — not part of
 * the document, so decisions, polish, undo and the export never see it. Lab capture showed
 * interim words arriving within ~1 s while finals lagged by several seconds.
 */
import { EditorView, Decoration, WidgetType, type DecorationSet } from '@codemirror/view';
import { StateEffect, StateField, type EditorState } from '@codemirror/state';

export const setGhost = StateEffect.define<string>();

class GhostWidget extends WidgetType {
	constructor(readonly text: string) {
		super();
	}
	eq(other: GhostWidget) {
		return other.text === this.text;
	}
	toDOM() {
		const span = document.createElement('span');
		span.className = 'cm-ghost-interim';
		span.textContent = this.text;
		return span;
	}
	ignoreEvent() {
		return true;
	}
}

function shown(doc: string, ghost: string): string {
	if (!ghost) return '';
	return !doc || /\s$/.test(doc) ? ghost : ` ${ghost}`;
}

export const ghostField = StateField.define<string>({
	create: () => '',
	update(value, tr) {
		for (const e of tr.effects) if (e.is(setGhost)) value = e.value.trim();
		return value;
	},
	provide: (f) =>
		EditorView.decorations.compute([f, 'doc'], (state): DecorationSet => {
			const g = ghostShown(state);
			if (!g) return Decoration.none;
			return Decoration.set([Decoration.widget({ widget: new GhostWidget(g.text), side: 1 }).range(g.pos)]);
		})
});

export function ghostShown(state: EditorState): { pos: number; text: string } | null {
	const ghost = state.field(ghostField, false) ?? '';
	if (!ghost) return null;
	const doc = state.doc.toString();
	return { pos: doc.length, text: shown(doc, ghost) };
}
