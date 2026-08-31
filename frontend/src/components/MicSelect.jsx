import { useEffect } from 'react'

// Mic input picker driven by the useAudioRecorder hook. The browser hides device
// labels/ids until mic permission has been granted, so before that the picker has
// no real names. Guided flow: the dropdown stays disabled and the user is led to
// click "Mikrofone laden" first, which requests a one-shot permission and reveals
// the real device names (e.g. an external mic at a live event). Viewers who never
// click it are never prompted.
export function MicSelect({ recorder, className = '', disabled = false }) {
  const { devices, deviceId, setDeviceId, listDevices } = recorder

  // Passive enumerate on mount (no permission prompt).
  useEffect(() => { listDevices() }, [listDevices])

  const hasLabels = devices.some((d) => d.label)

  return (
    <label className={`mic-select ${className}`.trim()}>
      Mikrofon:
      {hasLabels ? (
        <select
          value={deviceId}
          onChange={(e) => setDeviceId(e.target.value)}
          disabled={disabled}
        >
          <option value="">Standard (System)</option>
          {devices.map((d, i) => (
            <option key={d.deviceId || i} value={d.deviceId}>
              {d.label || `Mikrofon ${i + 1}`}
            </option>
          ))}
        </select>
      ) : (
        <>
          <select value="" disabled aria-disabled="true">
            <option value="">Zuerst Mikrofone laden…</option>
          </select>
          <button
            type="button"
            className="mic-select-load"
            onClick={() => listDevices({ prime: true })}
            disabled={disabled}
          >
            Mikrofone laden
          </button>
        </>
      )}
    </label>
  )
}
