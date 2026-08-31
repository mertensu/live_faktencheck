import { useEffect } from 'react'

// Mic input picker driven by the useAudioRecorder hook. The browser hides device
// labels/ids until mic permission is granted, so before the first recording the
// list may be empty — "Mikrofone laden" primes a one-shot permission (explicit
// user action) to reveal the real names, e.g. an external mic at a live event.
export function MicSelect({ recorder, className = '', disabled = false }) {
  const { devices, deviceId, setDeviceId, listDevices } = recorder

  // Passive enumerate on mount (no permission prompt).
  useEffect(() => { listDevices() }, [listDevices])

  const hasLabels = devices.some((d) => d.label)

  return (
    <label className={`mic-select ${className}`.trim()}>
      Mikrofon:
      <select
        value={deviceId}
        onChange={(e) => setDeviceId(e.target.value)}
        disabled={disabled}
      >
        <option value="">Standard</option>
        {devices.map((d, i) => (
          <option key={d.deviceId || i} value={d.deviceId}>
            {d.label || `Mikrofon ${i + 1}`}
          </option>
        ))}
      </select>
      {!hasLabels && (
        <button
          type="button"
          className="mic-select-load"
          onClick={() => listDevices({ prime: true })}
          disabled={disabled}
        >
          Mikrofone laden
        </button>
      )}
    </label>
  )
}
