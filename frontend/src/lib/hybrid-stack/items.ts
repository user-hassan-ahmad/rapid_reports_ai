// Checklist rows (spec 2026-10-11-scratchpad-checklist §3): pure helpers for the view and the scratchpad.
import { effectiveItems } from './regionState';
import type { StackItem, StackUnit } from './types';

export const QUIET_MAX = 3;

const norm = (s: string) => s.trim().toLowerCase().replace(/\.$/, '').replace(/\s+/g, ' ');

/** The answer button: the one sentence it adds, or "Both normal" with both sentences in view above it. */
export function answerLabel(sentences: string[]): string {
	return sentences.length === 1 ? sentences[0].trim().replace(/\.$/, '') : 'Both normal';
}

/** The sentences a tap will add: the row's own, minus any the radiologist removed with ×. */
export function rowSentences(item: StackItem, removed: string[]): string[] {
	const gone = new Set(removed.map(norm));
	return item.sentences.filter((s) => !gone.has(norm(s)));
}

/** Rows still waiting for the radiologist: the gate stays locked while any is open. */
export function openCount(items: StackItem[], tapped: string[], removed: string[]): number {
	return items.filter((i) => !i.answered && !tapped.includes(i.id) && rowSentences(i, removed).length > 0).length;
}

export function quietLine(sentences: string[], max = QUIET_MAX): { shown: string[]; more: number } {
	return { shown: sentences.slice(0, max), more: Math.max(0, sentences.length - max) };
}

/** Every abnormal sentence, parts included: the writer's cache key (its rows change only when these change). */
export function abnormalAll(units: StackUnit[]): string[] {
	return effectiveItems(units).filter((i) => i.abnormal).map((i) => i.text);
}
