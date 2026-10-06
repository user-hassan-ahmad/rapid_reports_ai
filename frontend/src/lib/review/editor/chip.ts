// What a highlight's inline control offers (pure; no DOM). Hovering (or the keyboard caret on) a highlight expands a
// small control at the END of that highlight, inside the text flow: simple icons only. Only flagged action items
// (✓ apply / ✕ dismiss / › to their rail card) have one, plus ↺ restore and ↶ undo on removed or pre-applied text.
// Recommendations are kept or removed from their section's checkbox block (editor/decorations.ts). The AI-generated layer (assumed normals, checks, synthesis) and info items are
// colour only: no control (the text is directly editable). Every button is a review command
// (lib/review/commands.ts) except `reveal`.
import type { CommandName } from '../commands';
import type { ReviewItem } from '../types';
import type { MarkClass } from './field';

export type ChipType =
	| 'check'
	| 'synth'
	| 'rec'
	| 'action'
	| 'normal'
	| 'removed'
	| 'option'
	| 'preapplied'
	| 'excluded'
	| 'info';

/** What a control is anchored to: a mark (text in the report) or a display widget (removed / option / excluded). */
export type ChipTarget =
	| { on: 'mark'; mark: MarkClass; kind: string; pointer?: string; reason?: string }
	| { on: 'widget'; kind: 'removed' | 'option' | 'excluded'; pointer?: string; reason?: string };

export interface ChipAction {
	command: CommandName | 'reveal';
	icon: string;
	label: string;
	/** apply: hovering previews the change inline. */
	preview?: boolean;
}

function isRemoval(item: ReviewItem | undefined, kind: string): boolean {
	return kind === 'removed' || item?.kind === 'removed' || item?.edit?.mode === 'remove';
}

export function chipType(t: ChipTarget, item?: ReviewItem): ChipType {
	if (t.on === 'widget') return t.kind;
	switch (t.mark) {
		case 'rv-check':
			return 'check';
		case 'rv-normal':
			return 'normal';
		case 'rv-synth':
			return 'synth';
		case 'rv-rec':
			return 'rec';
		case 'rv-preapplied':
			return isRemoval(item, t.kind) ? 'removed' : 'preapplied';
		case 'rv-info':
			return 'info';
		default:
			return 'action';
	}
}

const DISMISS: ChipAction = { command: 'dismiss', icon: '✕', label: 'Dismiss' };
const REVEAL: ChipAction = { command: 'reveal', icon: '›', label: 'Show in the review rail' };

/** The control's buttons, by type (none: no control). `›` only on a flagged issue (an action item, which has a rail
 * card). */
export function chipActions(t: ChipTarget, item?: ReviewItem): ChipAction[] {
	switch (chipType(t, item)) {
		case 'check':
		case 'normal':
		case 'synth':
		case 'info':
			return []; // the AI-generated layer: colour only
		case 'rec':
			return []; // kept / removed from the section's checkbox block
		case 'action': {
			const out: ChipAction[] = [];
			if (item?.edit) out.push({ command: 'apply', icon: '✓', label: 'Apply the fix', preview: true });
			out.push(DISMISS);
			if (item?.cls === 'action') out.push(REVEAL);
			return out;
		}
		case 'removed':
			return [{ command: 'restore', icon: '↺', label: 'Restore the original text' }];
		case 'option':
			return [{ command: 'apply', icon: '✓', label: 'Include in the report' }, DISMISS];
		case 'preapplied':
			return [{ command: 'undo', icon: '↶', label: 'Undo this change' }];
		case 'excluded':
			return [{ command: 'undo', icon: '↶', label: 'Undo the removal' }];
	}
}
