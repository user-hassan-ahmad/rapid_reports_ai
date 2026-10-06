/**
 * The review layer for a CM6 editor (plan Task C2): the review field, its drawing (marks, widgets, hover chip,
 * gutter), density and theme, wired to the host's callbacks. ReportEditor mounts `reviewExtensions(...)` through
 * a Compartment (C3); the viewer loads items with field.replaceDoc / syncItems and applies commands with
 * field.commandTransaction.
 */
import type { Extension } from '@codemirror/state';
import type { ReviewItem } from '../types';
import {
	onReviewCommand,
	onRevealItem,
	reviewDisplay,
	reviewItemLookup,
	type ReviewCommandCallback
} from './decorations';
import {
	onReviewHistory,
	onReviewStale,
	reviewFieldExtension,
	type ReviewFieldState,
	type ReviewHistoryEvent
} from './field';
import { densityExtension, reviewTheme, type Density } from './theme';

export interface ReviewExtensionOptions {
	/** Every popover and widget button: run the named command for the item, dispatch its transaction, post it. */
	onCommand: ReviewCommandCallback;
	/** Items whose marks were edited into (or could not be placed): the store marks them stale. */
	onStale?: (ids: string[]) => void;
	/** Cmd-Z / redo of a review command: post the matching event. */
	onHistory?: (ev: ReviewHistoryEvent) => void;
	/** Assumed-normal density; Quiet by default. Change it later with the `setDensity` effect. */
	density?: Density;
	/** The store item for an id: the popover's label, reason, source line and edit come from it. */
	getItem?: (id: string) => ReviewItem | undefined;
	/** The chip's "›": show the item's card in the rail. */
	onReveal?: (id: string) => void;
	/** The field's initial items (field.fromItems); empty by default, loaded later with replaceDoc / syncItems. */
	initial?: ReviewFieldState;
}

export function reviewExtensions(opts: ReviewExtensionOptions): Extension[] {
	const ext: Extension[] = [
		reviewFieldExtension(opts.initial),
		onReviewCommand.of(opts.onCommand),
		densityExtension(opts.density),
		reviewDisplay(),
		reviewTheme
	];
	if (opts.onStale) ext.push(onReviewStale.of(opts.onStale));
	if (opts.onHistory) ext.push(onReviewHistory.of(opts.onHistory));
	if (opts.getItem) ext.push(reviewItemLookup.of(opts.getItem));
	if (opts.onReveal) ext.push(onRevealItem.of(opts.onReveal));
	return ext;
}

export {
	DESCRIPTIONS,
	ICONS,
	LABELS,
	LEGEND,
	onReviewCommand,
	onRevealItem,
	openPopover,
	popoverField,
	reviewDisplay,
	reviewItemLookup,
	setPreview,
	type Meaning,
	type ReviewCommandCallback
} from './decorations';
export { DEFAULT_DENSITY, densityField, reviewTheme, setDensity, type Density } from './theme';
