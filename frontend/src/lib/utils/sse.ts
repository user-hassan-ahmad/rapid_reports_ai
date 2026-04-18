/**
 * Minimal Server-Sent Events reader for POST endpoints.
 *
 * The browser's native `EventSource` only supports GET. For POST-based SSE
 * (e.g. our /api/quick-report/generate which takes a JSON request body),
 * this helper parses the SSE wire format out of a streaming fetch response.
 *
 * Uses the SSE spec's line-by-line parsing model:
 *   - Each line starting with "event:" sets the current event name
 *   - Each line starting with "data:" appends to the current event's data
 *   - Each line starting with ":" is a comment (ignored, used for ping)
 *   - A blank line = end of event — dispatch it, reset state
 *
 * This approach is robust to any whitespace/terminator variant the server
 * emits (sse-starlette uses non-standard separator sequences that broke
 * the previous naive split-on-double-delimiter implementation).
 */

export type SSEEventHandler = (eventName: string, data: any) => void;

export interface SSEOptions {
	signal?: AbortSignal;
}

// Line boundary within a chunk: \r\n, \n, or \r (any SSE spec terminator).
const LINE_TERMINATOR = /\r\n|\r|\n/;

/**
 * Read an SSE stream from a fetch Response body and invoke onEvent for each
 * complete event. Resolves when the stream closes; rejects if the abort
 * signal fires.
 */
export async function readSSEStream(
	response: Response,
	onEvent: SSEEventHandler,
	options: SSEOptions = {}
): Promise<void> {
	if (!response.body) {
		throw new Error('SSE response has no body');
	}
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	// Per-event accumulating state. Reset on every dispatch (blank line).
	let eventName = 'message';
	let dataLines: string[] = [];

	const dispatchIfReady = () => {
		if (dataLines.length === 0) {
			// Empty event (ping comment or just whitespace) — reset without dispatching
			eventName = 'message';
			return;
		}
		const dataText = dataLines.join('\n');
		let parsed: any;
		try {
			parsed = JSON.parse(dataText);
		} catch {
			parsed = dataText;
		}
		onEvent(eventName, parsed);
		eventName = 'message';
		dataLines = [];
	};

	const processLine = (line: string) => {
		if (line === '') {
			// Blank line = event boundary → dispatch
			dispatchIfReady();
		} else if (line.startsWith('event:')) {
			eventName = line.slice('event:'.length).trim();
		} else if (line.startsWith('data:')) {
			dataLines.push(line.slice('data:'.length).trim());
		} else if (line.startsWith(':')) {
			// SSE comment (e.g. ping) — ignore
		} else if (line.startsWith('id:') || line.startsWith('retry:')) {
			// id and retry fields are part of the spec but we don't use them
		}
	};

	try {
		while (true) {
			if (options.signal?.aborted) {
				await reader.cancel();
				throw new DOMException('SSE stream aborted', 'AbortError');
			}

			const { done, value } = await reader.read();
			if (done) {
				// Stream closed — process any remaining buffered line and
				// dispatch if we have accumulated data (safety net for a
				// final event that wasn't followed by a blank line).
				if (buffer.length > 0) {
					processLine(buffer);
					buffer = '';
				}
				dispatchIfReady();
				break;
			}

			const chunk = decoder.decode(value, { stream: true });
			buffer += chunk;

			// Split into complete lines; keep incomplete last line in buffer.
			const parts = buffer.split(LINE_TERMINATOR);
			buffer = parts.pop() || '';

			for (const line of parts) {
				processLine(line);
			}
		}
	} finally {
		try {
			reader.releaseLock();
		} catch {
			// already released
		}
	}
}
