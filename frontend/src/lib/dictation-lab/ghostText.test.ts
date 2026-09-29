import { describe, expect, it } from 'vitest';
import { EditorState } from '@codemirror/state';
import { ghostField, ghostShown, setGhost } from './ghostText';

describe('live ghost text (Deepgram interim words at the end of the document)', () => {
	it('shows the interim words at the end, separated from the text before', () => {
		let s = EditorState.create({ doc: 'No effusion.', extensions: [ghostField] });
		s = s.update({ effects: setGhost.of('The spleen meas') }).state;
		expect(ghostShown(s)).toEqual({ pos: 12, text: ' The spleen meas' });
	});

	it('needs no separator after a space or line break, or in an empty document', () => {
		let s = EditorState.create({ doc: 'Findings:\n', extensions: [ghostField] });
		s = s.update({ effects: setGhost.of('No effusion') }).state;
		expect(ghostShown(s)?.text).toBe('No effusion');
		let e = EditorState.create({ doc: '', extensions: [ghostField] });
		e = e.update({ effects: setGhost.of('No effusion') }).state;
		expect(ghostShown(e)?.text).toBe('No effusion');
	});

	it('follows the end of the document as text is added, and clears with an empty value', () => {
		let s = EditorState.create({ doc: 'A.', extensions: [ghostField] });
		s = s.update({ effects: setGhost.of('B') }).state;
		s = s.update({ changes: { from: 2, insert: ' C.' } }).state;
		expect(ghostShown(s)?.pos).toBe(5);
		s = s.update({ effects: setGhost.of('') }).state;
		expect(ghostShown(s)).toBeNull();
	});
});
