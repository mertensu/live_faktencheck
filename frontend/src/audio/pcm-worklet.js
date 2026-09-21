// AudioWorklet processor: downsamples mono float audio from the context sample rate
// to 16 kHz PCM16 and posts each chunk (ArrayBuffer of Int16) to the main thread.
// AssemblyAI Universal-Streaming expects 16 kHz mono PCM16; MediaRecorder's WebM/Opus
// is not accepted by the streaming API, which is why we capture raw PCM here.

const TARGET_RATE = 16000

class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    // Fractional read position into the incoming buffer, carried across process() calls.
    this._pos = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const channel = input[0] // mono
    if (!channel || channel.length === 0) return true

    const ratio = sampleRate / TARGET_RATE // e.g. 48000/16000 = 3
    const outLength = Math.floor((channel.length - this._pos) / ratio)
    if (outLength <= 0) {
      this._pos -= channel.length
      return true
    }

    const out = new Int16Array(outLength)
    let pos = this._pos
    for (let i = 0; i < outLength; i++) {
      const idx = Math.floor(pos)
      let sample = channel[idx] || 0
      // Clamp and convert float [-1,1] to Int16.
      sample = Math.max(-1, Math.min(1, sample))
      out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      pos += ratio
    }
    // Preserve the fractional remainder for continuity with the next block.
    this._pos = pos - channel.length

    this.port.postMessage(out.buffer, [out.buffer])
    return true
  }
}

registerProcessor('pcm-worklet', PCMWorklet)
