import { useState, useCallback, useEffect } from 'react'

// Audio-input picker state for the live stream: the list of mics and the chosen
// one ('' = system default). The stream itself is opened by useAudioStream, which
// reads deviceId on start.
export function useMicDevices() {
  const [devices, setDevices] = useState([])        // [{ deviceId, label }] audio inputs
  const [deviceId, setDeviceIdState] = useState('') // '' = system default input

  // Enumerate audio inputs. Device labels (and stable ids) are hidden by the
  // browser until mic permission has been granted at least once; pass
  // { prime: true } to request a one-shot permission first so the picker can
  // show real names before going live. Priming is only ever triggered by an
  // explicit user action, never on mount, so viewers are not prompted.
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

  const setDeviceId = useCallback((id) => setDeviceIdState(id || ''), [])

  // Keep the picker in sync when a mic is plugged in or removed.
  useEffect(() => {
    const md = navigator.mediaDevices
    if (!md?.addEventListener) return
    const onChange = () => listDevices()
    md.addEventListener('devicechange', onChange)
    return () => md.removeEventListener('devicechange', onChange)
  }, [listDevices])

  return { devices, deviceId, setDeviceId, listDevices }
}
