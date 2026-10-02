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

// The operator's pick for a voice that is no guest (a clip, "Einspieler"): its words are
// not checked, and claims already shown from it are withdrawn. Same string as the backend.
export const OTHER_VOICE = 'Andere Stimme'

// A turn's transcript lines: one per speaker segment. A turn ends at a pause, not at a
// change of speaker, so the backend splits it where its words' speakers change.
export function turnLines(msg) {
  const segments = msg.segments?.length ? msg.segments : [{ label: msg.label, text: msg.text }]
  return segments
    .filter((s) => s.text)
    .map((s) => ({ label: s.label || null, text: s.text, turnOrder: msg.turn_order ?? null }))
}

// Put a turn's lines in place of its earlier ones (a re-sent final, a reclustering), or
// append a new turn. A turn the operator split by hand (a passage) keeps its own lines.
export function placeTurn(prev, turnOrder, lines, append) {
  const at = turnOrder == null ? -1 : prev.findIndex((t) => t.turnOrder === turnOrder)
  if (at < 0) return append ? [...prev, ...lines] : prev
  if (prev.some((t) => t.turnOrder === turnOrder && t.speaker)) return prev
  const rest = prev.filter((t) => t.turnOrder !== turnOrder)
  return [...rest.slice(0, at), ...lines, ...rest.slice(at)]
}

// A label's names over time: [[fromTurn, name], …]. Diarization may fold two people into
// one label, so the operator names it from a given turn on; earlier turns keep their name.
// fromTurn null = from the start.
export function assignFrom(map, label, fromTurn, name) {
  const start = fromTurn ?? -1
  const kept = (map[label] || []).filter(([from]) => from < start)
  return { ...map, [label]: [...kept, [start, name]] }
}

// The name a label has at a turn (the latest one when the turn is unknown), or null.
export function nameAt(map, label, turnOrder) {
  let name = null
  for (const [from, assigned] of map[label] || []) {
    if (turnOrder == null || from <= turnOrder) name = assigned
  }
  return name
}

// The marked text of each part: [{ index, lineText, start, end, text }], empty ones dropped.
function markedParts(parts) {
  return parts
    .map((p) => ({ ...p, text: p.lineText.slice(p.start, p.end).trim() }))
    .filter((p) => p.text)
}

// Split each marked line so its marked part becomes a line of its own under `speaker`.
// `parts` is [{ index, lineText, start, end }]; a line that changed since it was marked stays.
export function splitPassages(transcript, parts, speaker) {
  let next = transcript
  // From the last line up, so splitting a line doesn't shift the indices still to come.
  for (const p of markedParts(parts).sort((a, b) => b.index - a.index)) {
    const t = next[p.index]
    if (!t || t.text !== p.lineText) continue
    const pieces = [
      { ...t, text: p.lineText.slice(0, p.start).trim() },
      { ...t, text: p.text, speaker },
      { ...t, text: p.lineText.slice(p.end).trim() },
    ].filter((piece) => piece.text)
    next = [...next.slice(0, p.index), ...pieces, ...next.slice(p.index + 1)]
  }
  return next
}

/**
 * Live streaming recorder: captures mic audio as 16 kHz PCM16 via an AudioWorklet and
 * streams it over a WebSocket to the backend (/api/stream), which relays to AssemblyAI
 * and drives the fast fact-check lane.
 *
 * Returns live status plus the latest partial transcript and a small event log so the
 * UI can show "Live" activity while verdicts stream into the results feed separately.
 */
// Capture the source as it is: the browser's call-processing (echo cancellation, noise
// suppression, gain control) is tuned for one voice and flattens the differences between
// speakers that AssemblyAI's diarization needs — on TV audio it made voices merge.
export function audioConstraints(deviceId) {
  const raw = { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
  return { audio: deviceId ? { ...raw, deviceId: { exact: deviceId } } : raw }
}

export function useAudioStream(sessionId, { deviceId = '' } = {}) {
  const [status, setStatus] = useState('idle')   // idle | connecting | streaming | error
  const [error, setError] = useState(null)
  const [partial, setPartial] = useState('')      // current interim (not-yet-final) turn
  const [transcript, setTranscript] = useState([]) // finalized turns [{ label, text, turnOrder, speaker? }]
  const [claims, setClaims] = useState([])        // gated claims [{ id, speaker, label, claim, source, consistency, status, begruendung, quellen }]
  const [speakerMap, setSpeakerMap] = useState({}) // label → [[fromTurn, name]], assigned by the operator
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
    setTranscript([]); setPartial(''); setClaims([]); setSpeakerMap({})

    // 1. Mic
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia(audioConstraints(deviceId))
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
        // Finalized turn: add its lines to the transcript and clear the interim line. Lines
        // keep their diarization label; the name is looked up in speakerMap when shown.
        if (msg.text) setTranscript((prev) => placeTurn(prev, msg.turn_order ?? null, turnLines(msg), true))
        setPartial('')
      } else if (msg.type === 'turn_speaker_update') {
        // Diarization was reclustered: the turn is split anew. In a turn the operator split
        // by hand, the passage keeps its name and the rest takes the new label.
        setTranscript((prev) => {
          if (msg.segments?.length && !prev.some((t) => t.turnOrder === msg.turn_order && t.speaker)) {
            return placeTurn(prev, msg.turn_order, turnLines(msg), false)
          }
          return prev.map((t) => (t.turnOrder === msg.turn_order && !t.speaker ? { ...t, label: msg.label } : t))
        })
      } else if (msg.type === 'claim_source_update') {
        // An early claim's sentence got re-formatted in the final turn: keep the mark matching.
        setClaims((prev) => prev.map((c) =>
          c.source === msg.old ? { ...c, source: msg.source } : c))
      } else if (msg.type === 'speaker_map_update') {
        // The operator named (or un-named) a label from a turn on; confirmed by the backend.
        setSpeakerMap((prev) => assignFrom(prev, msg.label, msg.from_turn, msg.speaker || null))
      } else if (msg.type === 'partial') {
        setPartial(msg.text || '')
      } else if (msg.type === 'claim_processing') {
        // A gated claim is being checked: show it immediately (spinner) and remember
        // its source sentence so the transcript can highlight the passage.
        setClaims((prev) => [...prev, {
          id: msg.id, speaker: msg.speaker || null, label: msg.label || null, claim: msg.claim || '',
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
      } else if (msg.type === 'claim_withdrawn') {
        // Its speaker is no guest (any more): the claim is off air.
        setClaims((prev) => prev.filter((c) => c.id !== msg.id))
      } else if (msg.type === 'claim_speaker_update') {
        // Label assigned or reclustered: rewrite this claim's speaker retroactively.
        setClaims((prev) => prev.map((c) =>
          c.id === msg.id ? { ...c, speaker: msg.speaker, label: 'label' in msg ? msg.label : c.label } : c))
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

  // Name a diarization label (or clear it with null) from turn `fromTurn` on. The backend
  // rewrites the stored claims and answers with speaker_map_update, which updates speakerMap.
  const assignSpeaker = useCallback((label, speaker, fromTurn = null) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'assign_speaker', label, speaker: speaker || null, from_turn: fromTurn ?? null }))
  }, [])

  // Give a marked passage to a guest. It may span several transcript lines: `parts` is
  // [{ index, lineText, start, end }], chars start..end of line `index`. Each line splits so
  // its marked part shows under that name, and the backend moves any claim from it (now or
  // later) to the guest, whatever its label says.
  const assignPassage = useCallback((parts, speaker) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN || !speaker) return
    for (const p of markedParts(parts)) ws.send(JSON.stringify({ type: 'assign_passage', text: p.text, speaker }))
    setTranscript((prev) => splitPassages(prev, parts, speaker))
  }, [])

  // Release everything on unmount.
  useEffect(() => () => { stoppingRef.current = true; cleanup() }, [cleanup])

  return { status, error, partial, transcript, claims, speakerMap, events, start, stop, assignSpeaker, assignPassage }
}
