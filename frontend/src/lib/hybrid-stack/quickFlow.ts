// Stack-mode decisions shared by the quick and template hosts (integration spec §10).
import type { GateRecord } from './types';

/** In stack mode Generate is blocked only by recording, loading, empty findings and the stack gate (§10); the
 *  analyser, /sections and the tab-level integrity gate are not part of the stack. */
export function stackGenerateBlocked(s: { isRecording: boolean; loading: boolean; scratchpad: string; gate: GateRecord | null }): boolean {
	return s.isRecording || s.loading || !s.scratchpad.trim() || !s.gate;
}
