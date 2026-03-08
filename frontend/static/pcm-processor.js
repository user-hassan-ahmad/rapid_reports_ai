/**
 * AudioWorkletProcessor that converts Float32 mic samples to Int16 PCM
 * and posts each 128-sample frame back to the main thread.
 * Runs in the audio worklet thread — no deprecated ScriptProcessorNode needed.
 */
class PCMProcessor extends AudioWorkletProcessor {
	process(inputs) {
		const channel = inputs[0]?.[0];
		if (channel?.length) {
			const int16 = new Int16Array(channel.length);
			for (let i = 0; i < channel.length; i++) {
				const s = Math.max(-1, Math.min(1, channel[i]));
				int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
			}
			// Transfer the buffer (zero-copy) to the main thread
			this.port.postMessage(int16.buffer, [int16.buffer]);
		}
		return true;
	}
}

registerProcessor('pcm-processor', PCMProcessor);
