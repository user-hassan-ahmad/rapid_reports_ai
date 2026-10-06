// What a hover chip offers (pure; no DOM). The chip replaces the old click popover: one line with a type icon and
// icon buttons by type (the rationale lives only on the rail card). Every button is a
// review command (lib/review/commands.ts) except `reveal`, which scrolls the rail to the item's card.
import type { CommandName } from '../commands';
import type { ReviewItem } from '../types';
import type { MarkClass } from './field';

export type ChipType = 'check' | 'action' | 'normal' | 'removed' | 'option' | 'preapplied' | 'info';

export const CHIP_ICONS: Record<ChipType, string> = {
	check: '?',
	action: '✕',
	normal: '✓',
	removed: '↺',
	option: '+',
	preapplied: '↶',
	info: 'i'
};

/** What a chip is anchored to: a mark (text in the report) or a display widget (removed / option). */
export type ChipTarget =
	| { on: 'mark'; mark: MarkClass; kind: string; pointer?: string; reason?: string }
	| { on: 'widget'; kind: 'removed' | 'option' | 'excluded'; pointer?: string; reason?: string };

export interface ChipAction {
	command: CommandName | 'reveal';
	icon: string;
	label: string;
	/** ⏎ apply: hovering previews the change inline. */
	preview?: boolean;
}

function isRemoval(item: ReviewItem | undefined, kind: string): boolean {
	return kind === 'removed' || item?.kind === 'removed' || item?.edit?.mode === 'remove';
}

export function chipType(t: ChipTarget, item?: ReviewItem): ChipType | null {
	if (t.on === 'widget') return t.kind === 'excluded' ? null : t.kind;
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

const REVEAL: ChipAction = { command: 'reveal', icon: '›', label: 'Show in the review rail' };

/** The chip's buttons, by type; `›` (reveal) always last. */
export function chipActions(t: ChipTarget, item?: ReviewItem): ChipAction[] {
	const type = chipType(t, item);
	const out: ChipAction[] = [];
	switch (type) {
		case 'check':
			out.push(
				{ command: 'keep', icon: '✓', label: 'Keep as written' },
				{ command: 'remove', icon: '✕', label: 'Remove from the report' }
			);
			break;
		case 'normal':
			out.push({ command: 'remove', icon: '✕', label: 'Remove from the report' });
			break;
		case 'action':
			if (item?.edit) out.push({ command: 'apply', icon: '⏎', label: 'Apply the fix', preview: true });
			out.push({ command: 'dismiss', icon: '⊘', label: 'Dismiss' });
			break;
		case 'removed':
			out.push({ command: 'restore', icon: '↺', label: 'Restore the original text' });
			break;
		case 'option':
			out.push({ command: 'apply', icon: '+', label: 'Include in the report' });
			break;
		case 'preapplied':
			out.push({ command: 'undo', icon: '↶', label: 'Undo this change' });
			break;
	}
	out.push(REVEAL);
	return out;
}
