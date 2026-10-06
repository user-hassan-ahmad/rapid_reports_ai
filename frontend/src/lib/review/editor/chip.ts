// What a hover chip says and offers (pure; no DOM). The chip replaces the old click popover: one line with a type
// icon, a condensed rationale built by code from the item (no model), and icon buttons by type. Every button is a
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

/** At most `n` words, with an ellipsis when cut. */
export function condense(text: string, n = 6): string {
	const words = text.replace(/\s+/g, ' ').trim().replace(/[.;:,]+$/, '').split(' ').filter(Boolean);
	return words.length <= n ? words.join(' ') : `${words.slice(0, n).join(' ')}…`;
}

const q = (s: string) => `“${condense(s)}”`;

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

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : '');

/** The one-line rationale, from the item's kind and evidence. */
export function chipRationale(t: ChipTarget, item?: ReviewItem): string {
	const type = chipType(t, item);
	const ev = item?.evidence ?? {};
	const pointer = str(ev.pointer) || str(t.pointer);
	const checkReason = str(ev.check_reason) || str(t.on === 'mark' ? t.reason : '');
	const number =
		checkReason === 'number' ||
		str(ev.removal_reason) === 'number' ||
		(t.on === 'widget' && t.reason === 'number') ||
		/number|measurement_not/.test(item?.kind ?? '');
	switch (type) {
		case 'check':
			if (number) return 'measurement not dictated';
			if (checkReason === 'conflict') return pointer ? `contradicts ${q(pointer)}` : 'contradicts your dictation';
			return pointer ? `given ${q(pointer)}` : 'uncertain given your findings';
		case 'normal':
			return 'assumed normal';
		case 'removed':
			return number ? 'measurement not dictated' : 'contradicts your dictation';
		case 'option':
			return 'suggested';
		case 'preapplied':
			return 'added from your dictation';
		case 'info':
			return item?.label ? condense(item.label) : 'for information';
		case 'action': {
			const kind = item?.kind ?? (t.on === 'mark' ? t.kind : '');
			const dictated = pointer || str(ev.dictated) || str(item?.source_line) || str(ev.phrase);
			if (kind === 'contradicted' || kind === 'differs')
				return dictated ? `contradicts ${q(dictated)}` : 'contradicts your dictation';
			if (kind === 'unsupported') return 'not in your dictation';
			if (kind === 'overstated') {
				const d = str(ev.dictated);
				const r = str(ev.report) || str(ev.phrase);
				return d && r ? `${q(d)} → ${q(r)}` : 'more certain than dictated';
			}
			if (number) return 'measurement not dictated';
			if (kind === 'misattributed') return 'measurement on another structure';
			if (kind === 'laterality') return 'side missing';
			if (kind === 'absent') return 'dictated finding missing';
			if (kind === 'partial') return 'dictated finding partly missing';
			return item?.label ? condense(item.label) : 'needs a look';
		}
		default:
			return '';
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
