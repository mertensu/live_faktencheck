import { useState, useEffect } from 'react'

// Input level of the chosen mic before going live, so the operator sees that sound
// arrives (playback and recording on one device often filters the sound out).
// Opens its own short-lived stream only while `enabled` — the caller enables it once
// mic permission exists, so it never triggers a prompt of its own — and closes it
// when disabled (going live opens the stream useAudioStream needs).
// Returns { level: 0..1 (RMS, scaled) or null while not measuring, hasSignal }.
// hasSignal stays true a moment after the last loud frame, so pauses don't flicker it.
const SIGNAL_LEVEL = 0.08
const SIGNAL_HOLD_MS = 3000

export function useMicLevel(deviceId, enabled) {
  const [level, setLevel] = useState(null)
  const [hasSignal, setHasSignal] = useState(false)

  useEffect(() => {
    if (!enabled || !navigator.mediaDevices?.getUserMedia) {
      setLevel(null)
      setHasSignal(false)
      return
    }
    let cancelled = false
    let stream = null
    let ctx = null
    let raf = 0

    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: deviceId ? { deviceId: { exact: deviceId } } : true,
        })
        if (cancelled) return
        const AudioCtx = window.AudioContext || window.webkitAudioContext
        ctx = new AudioCtx()
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 1024
        ctx.createMediaStreamSource(stream).connect(analyser)
        const buf = new Float32Array(analyser.fftSize)
        let last = 0
        let lastLoud = -Infinity
        const tick = (t) => {
          // ~12 updates a second is plenty for a meter and keeps re-renders cheap.
          if (t - last > 80) {
            last = t
            analyser.getFloatTimeDomainData(buf)
            let sum = 0
            for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
            const rms = Math.sqrt(sum / buf.length)
            const lvl = Math.min(1, rms * 6)
            if (lvl > SIGNAL_LEVEL) lastLoud = t
            setLevel(lvl)
            setHasSignal(t - lastLoud < SIGNAL_HOLD_MS)
          }
          raf = requestAnimationFrame(tick)
        }
        raf = requestAnimationFrame(tick)
      } catch {
        if (!cancelled) { setLevel(null); setHasSignal(false) }
      }
    }
    start()

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
      stream?.getTracks().forEach((tr) => tr.stop())
      ctx?.close().catch(() => {})
    }
  }, [deviceId, enabled])

  return { level, hasSignal }
}
