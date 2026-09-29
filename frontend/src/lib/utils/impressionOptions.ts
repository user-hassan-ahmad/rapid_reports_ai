// Reporter-choice options: sentences the reporter can tick into, or out of, the
// IMPRESSION section of a quick report. Pure text functions so they can be tested
// without the editor; the editor applies the returned range as one transaction.

export interface ReportOption {
	id: string;
	kind: 'recommendation' | 'impression';
	sentence: string;
	reason?: string;
	source?: string;
}

export interface TextEdit {
	from: number;
	to: number;
	insert: string;
}

const SECTION_HEADER = /^[A-Z][A-Z /&()-]{2,}:\s*$/;
const IMPRESSION_HEADER = /^IMPRESSION:?\s*$/;
const NUMBERED = /^(\d+)[.)]\s/;

interface Block {
	start: number; // offset of the first content line after the header
	end: number; // offset just past the last line that ends a sentence
	numbered: boolean;
	lastNumber: number;
}

/** The IMPRESSION block, ending at the next section header or end of text. The insertion
 * point is after the block's last complete sentence, so a trailing signature is left alone. */
function impressionBlock(text: string): Block | null {
	const lines = text.split('\n');
	let offset = 0;
	let start = -1;
	let end = -1;
	let numbered = false;
	let lastNumber = 0;
	for (const line of lines) {
		const lineEnd = offset + line.length;
		if (start === -1) {
			if (IMPRESSION_HEADER.test(line.trim())) start = lineEnd + 1;
		} else {
			if (SECTION_HEADER.test(line.trim())) break;
			const t = line.trim();
			const m = t.match(NUMBERED);
			if (m) {
				numbered = true;
				lastNumber = Number(m[1]);
			}
			if (/[.!?)]$/.test(t)) end = lineEnd;
		}
		offset = lineEnd + 1;
	}
	if (start === -1 || end === -1) return null;
	return { start, end, numbered, lastNumber };
}

export function isApplied(text: string, option: ReportOption): boolean {
	return text.includes(option.sentence);
}

/** Edit that appends the option's sentence to the impression, matching its format. */
export function insertEdit(text: string, option: ReportOption): TextEdit | null {
	if (isApplied(text, option)) return null;
	const block = impressionBlock(text);
	if (!block) return null;
	const insert = block.numbered
		? `\n${block.lastNumber + 1}. ${option.sentence}`
		: ` ${option.sentence}`;
	return { from: block.end, to: block.end, insert };
}

/** Edit that removes the option's sentence (and its joining space or numbered line). */
export function removeEdit(text: string, option: ReportOption): TextEdit | null {
	const idx = text.indexOf(option.sentence);
	if (idx === -1) return null;
	let from = idx;
	let to = idx + option.sentence.length;
	const lineStart = text.lastIndexOf('\n', idx - 1) + 1;
	const prefix = text.slice(lineStart, idx);
	if (NUMBERED.test(prefix) && prefix.trim().match(/^\d+[.)]$/)) {
		from = lineStart > 0 ? lineStart - 1 : lineStart; // drop the whole numbered line
	} else if (text[from - 1] === ' ') {
		from -= 1;
	}
	return { from, to, insert: '' };
}

export function applyEdit(text: string, edit: TextEdit): string {
	return text.slice(0, edit.from) + edit.insert + text.slice(edit.to);
}

export function appliedOptionIds(text: string, options: ReportOption[]): string[] {
	return options.filter((o) => isApplied(text, o)).map((o) => o.id);
}
