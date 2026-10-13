// Runs the Style step's sheet checks for the sheet in hand (creator and refine panel). Re-runs are debounced, a run
// is skipped when the sheet and ledger are unchanged since the last good run, and only the newest request's answer
// (or failure) is ever shown, so a decision-only change can't be overwritten by an older response.
import type { LedgerEntry, SheetChecksResponse } from './types';

export type ChecksPost = (body: { skill_sheet: string; decisions: LedgerEntry[] }) => Promise<SheetChecksResponse>;

export function createChecksLoader(
	post: ChecksPost,
	onResult: (checks: SheetChecksResponse | null) => void,
	delayMs = 500
) {
	let seq = 0;
	let lastGoodKey: string | null = null;
	let pendingKey: string | null = null;   // the newest run's key while it is in flight
	let timer: ReturnType<typeof setTimeout> | null = null;

	async function run(sheet: string, decisions: LedgerEntry[], key: string) {
		const mine = ++seq;
		pendingKey = key;
		try {
			const r = await post({ skill_sheet: sheet, decisions });
			if (mine !== seq) return;
			pendingKey = null;
			lastGoodKey = r.success ? key : null;
			onResult(r.success ? r : null);
		} catch {
			if (mine !== seq) return;
			pendingKey = null;
			lastGoodKey = null;
			onResult(null);
		}
	}

	return {
		/** Ask for the checks of this sheet and ledger; `now` skips the debounce (a template just opened or built). */
		request(sheet: string, decisions: LedgerEntry[], opts: { now?: boolean } = {}) {
			if (timer) clearTimeout(timer);
			timer = null;
			const key = JSON.stringify([sheet, decisions]);
			if (key === pendingKey) return;   // the newest run already asks for exactly this
			if (key === lastGoodKey) {
				seq++;   // a run in flight for another key is now stale; the shown checks are this key's
				pendingKey = null;
				return;
			}
			if (opts.now) void run(sheet, decisions, key);
			else timer = setTimeout(() => void run(sheet, decisions, key), delayMs);
		},
		/** Forget the last run (a different template); the next request always runs. */
		reset() {
			if (timer) clearTimeout(timer);
			timer = null;
			seq++;
			lastGoodKey = null;
			pendingKey = null;
		}
	};
}
