import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMicDevices } from './useMicDevices'

const MICS = [
  { kind: 'audioinput', deviceId: 'default', label: 'Standard-Mikrofon' },
  { kind: 'audioinput', deviceId: 'usb-1', label: 'USB Podium-Mikro' },
  { kind: 'audiooutput', deviceId: 'spk', label: 'Speaker' },   // filtered out
]

function installMediaMocks(inputs) {
  const stop = vi.fn()
  global.navigator.mediaDevices = {
    getUserMedia: vi.fn(() => Promise.resolve({ getTracks: () => [{ stop }] })),
    enumerateDevices: vi.fn(() => Promise.resolve(inputs)),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
  return { stop }
}

describe('useMicDevices', () => {
  beforeEach(() => { installMediaMocks(MICS) })

  it('listDevices exposes only audio inputs', async () => {
    const { result } = renderHook(() => useMicDevices())
    await act(async () => { await result.current.listDevices() })
    expect(result.current.devices).toEqual([
      { deviceId: 'default', label: 'Standard-Mikrofon' },
      { deviceId: 'usb-1', label: 'USB Podium-Mikro' },
    ])
  })

  it('does not ask for mic permission unless primed', async () => {
    const { result } = renderHook(() => useMicDevices())
    await act(async () => { await result.current.listDevices() })
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  })

  it('priming requests a one-shot permission and releases it when labels are hidden', async () => {
    const { stop } = installMediaMocks([{ kind: 'audioinput', deviceId: '', label: '' }])
    const { result } = renderHook(() => useMicDevices())
    await act(async () => { await result.current.listDevices({ prime: true }) })
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(stop).toHaveBeenCalled()
  })

  it('setDeviceId stores the choice, empty means system default', () => {
    const { result } = renderHook(() => useMicDevices())
    expect(result.current.deviceId).toBe('')
    act(() => { result.current.setDeviceId('usb-1') })
    expect(result.current.deviceId).toBe('usb-1')
    act(() => { result.current.setDeviceId(null) })
    expect(result.current.deviceId).toBe('')
  })
})
