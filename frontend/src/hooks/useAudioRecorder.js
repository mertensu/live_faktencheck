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
  const [devices, setDevices] = useState([])        // [{ deviceId, label }] audio inputs
  const [deviceId, setDeviceIdState] = useState('') // '' = system default input

  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const tickRef = useRef(null)            // elapsed-time interval
  const autoSendRef = useRef(null)        // auto-send interval
  const stoppingRef = useRef(false)       // true while stop() is releasing the mic
  const blockSecondsRef = useRef(DEFAULT_BLOCK_SECONDS)
  const deviceIdRef = useRef('')          // selected input, mirrors deviceId state
  const pendingDeviceRef = useRef(null)   // device to switch to at the next block boundary

  // Open a mic stream for the given input. Falls back to the system default if
  // the requested device is gone (e.g. an external mic was unplugged).
  const openStream = useCallback(async (id) => {
    const constraints = { audio: id ? { deviceId: { exact: id } } : true }
    try {
      return await navigator.mediaDevices.getUserMedia(constraints)
    } catch (e) {
      if (id && (e?.name === 'OverconstrainedError' || e?.name === 'NotFoundError')) {
        deviceIdRef.current = ''
        setDeviceIdState('')
        return await navigator.mediaDevices.getUserMedia({ audio: true })
      }
      throw e
    }
  }, [])

  // Enumerate audio inputs. Device labels (and stable ids) are hidden by the
  // browser until mic permission has been granted at least once; pass
  // { prime: true } to request a one-shot permission first so the picker can
  // show real names before recording starts. Priming is only ever triggered by
  // an explicit user action, never on mount, so viewers are not prompted.
  const listDevices = useCallback(async ({ prime = false } = {}) => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    let all = await navigator.mediaDevices.enumerateDevices()
    let inputs = all.filter((d) => d.kind === 'audioinput')
    if (prime && !inputs.some((d) => d.label)) {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: true })
        s.getTracks().forEach((t) => t.stop())
        all = await navigator.mediaDevices.enumerateDevices()
        inputs = all.filter((d) => d.kind === 'audioinput')
      } catch { /* permission denied: keep the unlabeled list */ }
    }
    setDevices(inputs.map((d) => ({ deviceId: d.deviceId, label: d.label })))
  }, [])

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

    // Apply a requested input switch in the gap between blocks: swap the live
    // stream so the next recorder captures from the newly selected mic.
    if (pendingDeviceRef.current !== null && !stoppingRef.current) {
      const id = pendingDeviceRef.current
      pendingDeviceRef.current = null
      try {
        const next = await openStream(id)
        if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
        streamRef.current = next
      } catch { /* switch failed: keep recording on the current stream */ }
    }

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
  }, [sessionId, startRecorder, clearTimers, openStream])

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
      streamRef.current = await openStream(deviceIdRef.current)
    } catch (e) {
      setStatus('error')
      setError(e && e.name === 'NotFoundError' ? MSG.noMic : MSG.denied)
      return
    }
    stoppingRef.current = false
    pendingDeviceRef.current = null
    startRecorder()
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed((s) => s + 1), 1000)
    autoSendRef.current = setInterval(() => { flush() }, blockSecondsRef.current * 1000)
    setStatus('recording')
    // Permission is now granted, so labels/ids are available — refresh the picker.
    listDevices()
  }, [flush, startRecorder, openStream, listDevices])

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

  // Select the input mic. While idle the choice is stored for the next start();
  // while recording it is applied at the next block boundary (a sendNow() makes
  // the switch take effect promptly).
  const setDeviceId = useCallback((id) => {
    const next = id || ''
    deviceIdRef.current = next
    setDeviceIdState(next)
    if (streamRef.current && !stoppingRef.current) {
      pendingDeviceRef.current = next
      flush()   // apply the switch now instead of waiting a full block
    }
  }, [flush])

  // Keep the picker in sync when a mic is plugged in or removed.
  useEffect(() => {
    const md = navigator.mediaDevices
    if (!md?.addEventListener) return
    const onChange = () => listDevices()
    md.addEventListener('devicechange', onChange)
    return () => md.removeEventListener('devicechange', onChange)
  }, [listDevices])

  // Release the mic if the component unmounts mid-recording.
  useEffect(() => () => {
    clearTimers()
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
  }, [clearTimers])

  return {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds,
    remainingSeconds,
    devices, deviceId, setDeviceId, listDevices,
    start, sendNow, stop,
  }
}
