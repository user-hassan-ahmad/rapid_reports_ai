// What a highlight's inline control offers (pure; no DOM). Hovering (or the keyboard caret on) a highlight expands a
// small control at the END of that highlight, inside the text flow: simple icons only, ✓ (keep / include / apply)
// and ✕ (remove / dismiss), ↺ restore and ↶ undo on removed or pre-applied text. No type icon and no "?". Only a
// flagged issue (an action item, which has a rail card) keeps a tiny `›` to its card; checks, normals and
// suggestions have no rail link. Every button is a review command (lib/review/commands.ts) except `reveal`.
import type { CommandName } from '../commands';
import type { ReviewItem } from '../types';
import type { MarkClass } from './field';

export type ChipType =
	| 'check'
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
		case 'rv-preapplied':
			return isRemoval(item, t.kind) ? 'removed' : 'preapplied';
		case 'rv-info':
			return 'info';
		default:
			return 'action';
	}
}

const KEEP = (label: string): ChipAction => ({ command: 'keep', icon: '✓', label });
const REMOVE: ChipAction = { command: 'remove', icon: '✕', label: 'Remove from the report' };
const DISMISS: ChipAction = { command: 'dismiss', icon: '✕', label: 'Dismiss' };
const REVEAL: ChipAction = { command: 'reveal', icon: '›', label: 'Show in the review rail' };

/** The control's buttons, by type. `›` only on a flagged issue (an action item, which has a rail card). */
export function chipActions(t: ChipTarget, item?: ReviewItem): ChipAction[] {
	switch (chipType(t, item)) {
		case 'check':
			return [KEEP('Keep as written'), REMOVE];
		case 'normal':
			return [KEEP('Keep'), REMOVE];
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
		case 'info':
			return [DISMISS];
	}
}
