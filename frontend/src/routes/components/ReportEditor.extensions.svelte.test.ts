import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { Decoration, EditorView } from '@codemirror/view';
import { StateField, type EditorState, type Extension, type TransactionSpec } from '@codemirror/state';
import ReportEditor from './ReportEditor.svelte';

// `render` supplies `target`; the typed mount options demand it anyway.
type MountOpts = Parameters<typeof render<typeof ReportEditor>>[1];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A test extension that marks the first `len` characters with `cls`. */
function markFirst(cls: string, len = 4): Extension {
	return StateField.define({
		create: (state) =>
			Decoration.set([Decoration.mark({ class: cls }).range(0, Math.min(len, state.doc.length))]),
		update: (deco, tr) => deco.map(tr.changes),
		provide: (f) => EditorView.decorations.from(f)
	});
}

describe('ReportEditor extra extensions', () => {
	it('renders a decoration from an extra extension', async () => {
		const { container } = render(ReportEditor, { content: 'No ascites.', extraExtensions: [markFirst('tx-a')] });
		await pause(50);
		const el = container.querySelector('.tx-a');
		expect(el).not.toBeNull();
		expect(el!.textContent).toBe('No a');
	});

	it('reconfigures the extensions when the prop changes', async () => {
		const { container, rerender } = render(ReportEditor, {
			content: 'No ascites.',
			extraExtensions: [markFirst('tx-a')]
		});
		await pause(50);
		expect(container.querySelector('.tx-a')).not.toBeNull();
		await rerender({ extraExtensions: [markFirst('tx-b')] });
		await pause(50);
		expect(container.querySelector('.tx-a')).toBeNull();
		expect(container.querySelector('.tx-b')).not.toBeNull();
		await rerender({ extraExtensions: [] });
		await pause(50);
		expect(container.querySelector('.tx-b')).toBeNull();
	});

	it('exposes the view', async () => {
		const { component } = render(ReportEditor, { content: 'No ascites.' });
		await pause(50);
		const view = (component as unknown as { getView: () => EditorView | null }).getView();
		expect(view).toBeInstanceOf(EditorView);
		expect(view!.state.doc.toString()).toBe('No ascites.');
	});

	it('routes a content-prop change through replaceDocHook', async () => {
		const hook = vi.fn(
			(state: EditorState, text: string): TransactionSpec => ({
				changes: { from: 0, to: state.doc.length, insert: text.toUpperCase() }
			})
		);
		const onChange = vi.fn();
		const { component, rerender } = render(ReportEditor, {
			props: { content: 'No ascites.', replaceDocHook: hook },
			events: { change: onChange }
		} as MountOpts);
		await pause(50);
		expect(hook).not.toHaveBeenCalled();
		await rerender({ content: 'Small effusion.' });
		await pause(50);
		expect(hook).toHaveBeenCalledTimes(1);
		expect(hook.mock.calls[0][1]).toBe('Small effusion.');
		const view = (component as unknown as { getView: () => EditorView }).getView();
		expect(view.state.doc.toString()).toBe('SMALL EFFUSION.');
		// An external replace is never reported as a user change.
		expect(onChange).not.toHaveBeenCalled();
	});

	it('keeps the default replace path when no hook is given', async () => {
		const onChange = vi.fn();
		const { component, rerender } = render(ReportEditor, {
			props: { content: 'No ascites.' },
			events: { change: onChange }
		} as MountOpts);
		await pause(50);
		await rerender({ content: 'Small effusion.' });
		await pause(50);
		const view = (component as unknown as { getView: () => EditorView }).getView();
		expect(view.state.doc.toString()).toBe('Small effusion.');
		expect(onChange).not.toHaveBeenCalled();
		// A user edit still fires 'change'.
		view.dispatch({ changes: { from: 0, insert: 'X' }, userEvent: 'input' });
		await pause(20);
		expect(onChange).toHaveBeenCalledTimes(1);
		expect(onChange.mock.calls[0][0].detail).toEqual({ content: 'XSmall effusion.' });
	});
});
