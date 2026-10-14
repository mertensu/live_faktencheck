import { useState, useCallback, useEffect } from 'react'

// The sound of another browser tab (the Mediathek, a livestream) as the live source,
// taken digitally via screen sharing: no second device, no room sound. Only Chromium
// browsers (Chrome, Edge) hand over tab audio; Safari and Firefox share video only.
export const TAB_AUDIO_SUPPORTED = typeof navigator !== 'undefined'
  && !!navigator.mediaDevices?.getDisplayMedia
  && !!navigator.userAgentData?.brands?.some((b) => /Chromium/.test(b.brand))

const MSG = {
  noAudio: 'Kein Tab-Ton geteilt. Bitte einen Tab wählen und „Tab-Audio teilen“ anhaken.',
  failed: 'Tab konnte nicht geteilt werden',
}

// Raw capture, as for the mic (see audioConstraints): no call processing. The tab keeps
// playing for the operator (suppressLocalAudioPlayback false).
const DISPLAY_OPTIONS = {
  video: { displaySurface: 'browser' },  // required by the API; dropped right after
  audio: {
    echoCancellation: false, noiseSuppression: false, autoGainControl: false,
    suppressLocalAudioPlayback: false,
  },
  preferCurrentTab: false,
  selfBrowserSurface: 'exclude',
  surfaceSwitching: 'include',
  monitorTypeSurfaces: 'exclude',
  systemAudio: 'exclude',
}

const isLive = (stream) => !!stream?.getAudioTracks().some((t) => t.readyState === 'live')

export function useTabAudio() {
  const [stream, setStream] = useState(null)
  const [error, setError] = useState(null)

  // Ask the browser for a tab; call from a click. Returns the audio-only stream, or null
  // when the operator cancelled or shared no audio.
  const pick = useCallback(async () => {
    setError(null)
    // Stay on this page after picking: Chrome otherwise jumps to the shared tab.
    const controller = typeof CaptureController !== 'undefined' ? new CaptureController() : null
    const keepFocus = () => { try { controller?.setFocusBehavior('no-focus-change') } catch { /* too late or unsupported */ } }
    keepFocus()  // newer Chrome takes it up front
    let display
    try {
      display = await navigator.mediaDevices.getDisplayMedia(
        controller ? { ...DISPLAY_OPTIONS, controller } : DISPLAY_OPTIONS)
      keepFocus()  // older Chrome only right after the pick
    } catch (e) {
      if (e?.name !== 'NotAllowedError') setError(MSG.failed)  // NotAllowed: cancelled
      return null
    }
    display.getVideoTracks().forEach((t) => t.stop())
    const audio = display.getAudioTracks()
    if (!audio.length) {
      setError(MSG.noAudio)
      return null
    }
    const next = new MediaStream(audio)
    // Ended from the browser's "Freigabe beenden" bar.
    audio[0].addEventListener('ended', () => setStream((s) => (s === next ? null : s)))
    setStream(next)  // the effect below stops the one it replaces
    return next
  }, [])

  const release = useCallback(() => setStream(null), [])

  // A stream stopped here (track.stop() fires no "ended") counts as gone.
  const live = isLive(stream) ? stream : null

  // Stop a stream once it is replaced, released or the page closes.
  useEffect(() => () => { stream?.getTracks().forEach((t) => t.stop()) }, [stream])

  return { stream: live, error, pick, release }
}
