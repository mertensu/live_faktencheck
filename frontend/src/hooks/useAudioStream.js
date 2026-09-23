import { useState, useRef, useCallback, useEffect } from 'react'
import { openStreamUrl, debug } from '../services/api'
import pcmWorkletUrl from '../audio/pcm-worklet.js?url'

// German user-facing messages.
const MSG = {
  denied: 'Mikrofonzugriff verweigert',
  noMic: 'Kein Mikrofon gefunden',
  unsupported: 'Live-Streaming wird von diesem Browser nicht unterstützt',
  connectFailed: 'Verbindung zum Server fehlgeschlagen',
  quota: 'Audio-Kontingent für diesen Code aufgebraucht',
}

/**
 * Live streaming recorder: captures mic audio as 16 kHz PCM16 via an AudioWorklet and
 * streams it over a WebSocket to the backend (/api/stream), which relays to AssemblyAI
 * and drives the fast fact-check lane. Sibling of useAudioRecorder (the 120s block path).
 *
 * Returns live status plus the latest partial transcript and a small event log so the
 * UI can show "Live" activity while verdicts stream into the results feed separately.
 */
export function useAudioStream(sessionId, { deviceId = '' } = {}) {
  const [status, setStatus] = useState('idle')   // idle | connecting | streaming | error
  const [error, setError] = useState(null)
  const [partial, setPartial] = useState('')      // current interim (not-yet-final) turn
  const [transcript, setTranscript] = useState([]) // finalized turns [{ speaker, text }]
  const [claims, setClaims] = useState([])        // gated claims [{ id, speaker, claim, source, consistency, status, begruendung, quellen }]
  const [events, setEvents] = useState([])        // last few backend events (for debug/UI)

  const wsRef = useRef(null)
  const streamRef = useRef(null)
  const ctxRef = useRef(null)
  const nodeRef = useRef(null)
  const stoppingRef = useRef(false)

  const cleanup = useCallback(() => {
    try { nodeRef.current?.disconnect() } catch { /* noop */ }
    try { ctxRef.current?.close() } catch { /* noop */ }
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
    nodeRef.current = null
    ctxRef.current = null
    streamRef.current = null
  }, [])

  const stop = useCallback(() => {
    stoppingRef.current = true
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send('stop') } catch { /* noop */ }
    }
    try { ws?.close() } catch { /* noop */ }
    wsRef.current = null
    cleanup()
    setStatus('idle')
    setPartial('')
  }, [cleanup])

  const start = useCallback(async () => {
    if (typeof AudioWorkletNode === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setStatus('error'); setError(MSG.unsupported); return
    }
    setStatus('connecting'); setError(null); stoppingRef.current = false
    setTranscript([]); setPartial(''); setClaims([])

    // 1. Mic
    try {
      const constraints = { audio: deviceId ? { deviceId: { exact: deviceId } } : true }
      streamRef.current = await navigator.mediaDevices.getUserMedia(constraints)
    } catch (e) {
      setStatus('error')
      setError(e && e.name === 'NotFoundError' ? MSG.noMic : MSG.denied)
      return
    }

    // 2. Audio graph: mic -> worklet (PCM16 @ 16kHz) -> ws
    try {
      const ctx = new AudioContext()
      ctxRef.current = ctx
      await ctx.audioWorklet.addModule(pcmWorkletUrl)
      const source = ctx.createMediaStreamSource(streamRef.current)
      const node = new AudioWorkletNode(ctx, 'pcm-worklet')
      nodeRef.current = node
      source.connect(node)
      // Drive the worklet without routing mic audio to the speakers.
      node.connect(ctx.destination)

      node.port.onmessage = (e) => {
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data)
      }
    } catch (e) {
      debug.error('AudioWorklet setup failed', e)
      cleanup(); setStatus('error'); setError(MSG.unsupported); return
    }

    // 3. WebSocket
    const ws = new WebSocket(openStreamUrl(sessionId))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => { if (!stoppingRef.current) setStatus('streaming') }
    ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }
      setEvents((prev) => [...prev.slice(-19), msg])
      if (msg.type === 'turn') {
        // Finalized turn: append to the transcript and clear the interim line.
        // turnOrder/label let later speaker events rename this line.
        if (msg.text) setTranscript((prev) => [...prev, {
          speaker: msg.speaker || null, text: msg.text,
          turnOrder: msg.turn_order ?? null, label: msg.label || null, named: false,
        }])
        setPartial('')
      } else if (msg.type === 'turn_speaker_update') {
        // Voiceprint identified who spoke this turn: name the line directly. A turn with
        // several speakers (no pause between them) arrives as segments → one line each.
        setTranscript((prev) => prev.flatMap((t) => {
          if (t.turnOrder !== msg.turn_order) return [t]
          if (msg.segments) return msg.segments.map((s) => ({ ...t, speaker: s.speaker, text: s.text, named: true }))
          return [{ ...t, speaker: msg.speaker, named: true }]
        }))
      } else if (msg.type === 'claim_source_update') {
        // An early claim's sentence got re-formatted in the final turn: keep the mark matching.
        setClaims((prev) => prev.map((c) =>
          c.source === msg.old ? { ...c, source: msg.source } : c))
      } else if (msg.type === 'speaker_map_update') {
        // A diarization label got its name: rename lines still showing the bare label.
        setTranscript((prev) => prev.map((t) =>
          !t.named && t.label === msg.label ? { ...t, speaker: msg.speaker } : t))
      } else if (msg.type === 'partial') {
        setPartial(msg.text || '')
      } else if (msg.type === 'claim_processing') {
        // A gated claim is being checked: show it immediately (spinner) and remember
        // its source sentence so the transcript can highlight the passage.
        setClaims((prev) => [...prev, {
          id: msg.id, speaker: msg.speaker || null, claim: msg.claim || '',
          source: msg.source || '', consistency: null, status: 'processing',
        }])
      } else if (msg.type === 'claim_result') {
        setClaims((prev) => prev.map((c) =>
          c.id === msg.id ? {
            ...c, consistency: msg.consistency, status: 'done',
            begruendung: msg.begruendung || '', quellen: msg.quellen || [],
          } : c))
      } else if (msg.type === 'claim_error') {
        setClaims((prev) => prev.map((c) =>
          c.id === msg.id ? { ...c, status: 'error' } : c))
      } else if (msg.type === 'claim_speaker_update') {
        // Diarization was reclustered: rewrite this claim's speaker retroactively.
        setClaims((prev) => prev.map((c) =>
          c.id === msg.id ? { ...c, speaker: msg.speaker } : c))
      }
    }
    ws.onerror = () => { if (!stoppingRef.current) { setStatus('error'); setError(MSG.connectFailed) } }
    ws.onclose = (evt) => {
      if (stoppingRef.current) return
      // 1013 = budget exhausted (see backend WS_TRY_AGAIN_LATER).
      if (evt.code === 1013 && (evt.reason || '').includes('Kontingent')) setError(MSG.quota)
      cleanup(); setStatus('idle')
    }
  }, [sessionId, deviceId, cleanup])

  // Release everything on unmount.
  useEffect(() => () => { stoppingRef.current = true; cleanup() }, [cleanup])

  return { status, error, partial, transcript, claims, events, start, stop }
}
