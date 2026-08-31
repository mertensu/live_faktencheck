import { useEffect } from 'react'

// Mic input picker driven by the useAudioRecorder hook. The browser hides device
// labels/ids until mic permission has been granted, so before the first recording
// the list has no real names. Opening the dropdown is a clear user gesture, so we
// prime a one-shot permission on focus/pointer-down to reveal the real names (e.g.
// an external mic at a live event). Viewers who never touch the picker are never
// prompted.
export function MicSelect({ recorder, className = '', disabled = false }) {
  const { devices, deviceId, setDeviceId, listDevices } = recorder

  // Passive enumerate on mount (no permission prompt).
  useEffect(() => { listDevices() }, [listDevices])

  const hasLabels = devices.some((d) => d.label)

  // Reveal real device names the moment the user opens the picker.
  const revealNames = () => { if (!hasLabels) listDevices({ prime: true }) }

  return (
    <label className={`mic-select ${className}`.trim()}>
      Mikrofon:
      <select
        value={deviceId}
        onChange={(e) => setDeviceId(e.target.value)}
        onFocus={revealNames}
        onMouseDown={revealNames}
        disabled={disabled}
      >
        <option value="">Standard (System)</option>
        {devices.map((d, i) => (
          <option key={d.deviceId || i} value={d.deviceId}>
            {d.label || `Mikrofon ${i + 1}`}
          </option>
        ))}
      </select>
      {!hasLabels && (
        <span className="mic-select-hint">Zum Anzeigen der Namen öffnen</span>
      )}
    </label>
  )
}
