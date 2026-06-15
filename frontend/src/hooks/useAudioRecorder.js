import { useState, useRef, useCallback, useEffect } from 'react'
import { sendAudioBlock } from '../services/api'

const DEFAULT_BLOCK_SECONDS = 120

// German user-facing messages.
const MSG = {
  denied: 'Mikrofonzugriff verweigert',
  noMic: 'Kein Mikrofon gefunden',
  sendFailed: 'Block konnte nicht gesendet werden',
  unsupported: 'Audioaufnahme wird von diesem Browser nicht unterstützt',
  quota: 'Audio-Kontingent für diesen Code aufgebraucht',
}

export function useAudioRecorder(sessionId) {
  const [status, setStatus] = useState('idle')      // idle | requesting | recording | error
  const [elapsed, setElapsed] = useState(0)
  const [blocksSent, setBlocksSent] = useState(0)
  const [error, setError] = useState(null)
  const [blockSeconds, setBlockSecondsState] = useState(DEFAULT_BLOCK_SECONDS)
  const [remainingSeconds, setRemainingSeconds] = useState(null)

  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const tickRef = useRef(null)            // elapsed-time interval
  const autoSendRef = useRef(null)        // auto-send interval
  const stoppingRef = useRef(false)       // true while stop() is releasing the mic
  const blockSecondsRef = useRef(DEFAULT_BLOCK_SECONDS)

  // Block length is locked once recording starts (only honored while idle).
  const setBlockSeconds = useCallback((n) => {
    setStatus((s) => {
      if (s === 'idle') {
        blockSecondsRef.current = n
        setBlockSecondsState(n)
      }
      return s
    })
  }, [])

  const clearTimers = useCallback(() => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
    if (autoSendRef.current) { clearInterval(autoSendRef.current); autoSendRef.current = null }
  }, [])

  // Start a fresh MediaRecorder on the (still-open) stream.
  const startRecorder = useCallback(() => {
    const rec = new MediaRecorder(streamRef.current)
    recorderRef.current = rec
    rec.start()
  }, [])

  // Core cycle: stop current recorder (-> one complete block), POST it, then
  // restart a fresh recorder unless we are stopping. Shared by auto-send,
  // sendNow, and stop.
  const flush = useCallback(async () => {
    const rec = recorderRef.current
    if (!rec || rec.state !== 'recording') return

    const blob = await new Promise((resolve) => {
      rec.ondataavailable = (e) => resolve(e.data)
      rec.stop()
    })

    if (!stoppingRef.current) startRecorder()   // resume immediately
    setElapsed(0)

    try {
      const data = await sendAudioBlock(sessionId, blob)
      setBlocksSent((n) => n + 1)
      setError(null)   // a recovered send clears a prior send-failure indicator
      if (data && data.remaining_seconds !== undefined) {
        setRemainingSeconds(data.remaining_seconds)
      }
    } catch (e) {
      if (e && e.isQuota) {
        // Budget exhausted: stop the session and surface a clear message.
        setError(MSG.quota)
        setRemainingSeconds(0)
        stoppingRef.current = true
        clearTimers()
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop())
          streamRef.current = null
        }
        recorderRef.current = null
        setElapsed(0)
        setStatus('idle')
        return
      }
      // One bad block must not kill the session: surface, keep recording.
      setError(MSG.sendFailed)
    }
  }, [sessionId, startRecorder, clearTimers])

  const start = useCallback(async (overrideSeconds) => {
    if (typeof MediaRecorder === 'undefined') {
      setStatus('error'); setError(MSG.unsupported); return
    }
    if (typeof overrideSeconds === 'number') {
      blockSecondsRef.current = overrideSeconds
      setBlockSecondsState(overrideSeconds)
    }
    setStatus('requesting'); setError(null)
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setStatus('error')
      setError(e && e.name === 'NotFoundError' ? MSG.noMic : MSG.denied)
      return
    }
    stoppingRef.current = false
    startRecorder()
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed((s) => s + 1), 1000)
    autoSendRef.current = setInterval(() => { flush() }, blockSecondsRef.current * 1000)
    setStatus('recording')
  }, [flush, startRecorder])

  const sendNow = useCallback(async () => {
    await flush()
  }, [flush])

  const stop = useCallback(async () => {
    stoppingRef.current = true
    clearTimers()
    await flush()                       // final block, no restart
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    recorderRef.current = null
    setElapsed(0)
    setStatus('idle')
  }, [flush, clearTimers])

  // Release the mic if the component unmounts mid-recording.
  useEffect(() => () => {
    clearTimers()
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
  }, [clearTimers])

  return {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds,
    remainingSeconds,
    start, sendNow, stop,
  }
}
