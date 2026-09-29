// AudioWorklet processor: downsamples mono float audio from the context sample rate
// to 16 kHz PCM16 and posts it to the main thread in ~200 ms chunks.
//
// AssemblyAI Universal-Streaming expects 16 kHz mono PCM16 AND each sent chunk must
// represent between 50 ms and 1000 ms of audio (error 3007 otherwise). A render
// quantum is only 128 frames (~2.7 ms at 48 kHz), so we accumulate resampled samples
// and flush once we have a full chunk. MediaRecorder's WebM/Opus is not accepted by
// the streaming API, which is why we capture raw PCM here.

const TARGET_RATE = 16000
const CHUNK_MS = 200
const CHUNK_SAMPLES = (TARGET_RATE * CHUNK_MS) / 1000 // 3200 samples ≈ 200 ms @ 16 kHz

class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    this._pos = 0                                  // fractional read position across blocks
    this._buf = new Int16Array(CHUNK_SAMPLES)      // accumulation buffer
    this._len = 0                                  // samples currently buffered
  }

  _push(sample) {
    // Clamp float [-1,1] and convert to Int16.
    const s = Math.max(-1, Math.min(1, sample))
    this._buf[this._len++] = s < 0 ? s * 0x8000 : s * 0x7fff
    if (this._len === CHUNK_SAMPLES) {
      // Transfer a copy so the buffer can keep filling for the next chunk.
      const out = this._buf.slice(0, CHUNK_SAMPLES)
      this.port.postMessage(out.buffer, [out.buffer])
      this._len = 0
    }
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const channel = input[0] // mono
    if (!channel || channel.length === 0) return true

    const ratio = sampleRate / TARGET_RATE // e.g. 48000/16000 = 3
    let pos = this._pos
    while (pos < channel.length) {
      this._push(channel[Math.floor(pos)] || 0)
      pos += ratio
    }
    // Preserve the fractional remainder for continuity with the next block.
    this._pos = pos - channel.length
    return true
  }
}

registerProcessor('pcm-worklet', PCMWorklet)
