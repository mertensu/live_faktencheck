import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAudioRecorder } from './useAudioRecorder'
import * as api from '../services/api'

// --- MediaRecorder / getUserMedia mocks ---
let recorders = []   // every MediaRecorder constructed during a test
let tracks = []      // every track in the granted stream

class FakeMediaRecorder {
  constructor(stream) {
    this.stream = stream
    this.state = 'inactive'
    this.ondataavailable = null
    this.onstop = null
    recorders.push(this)
  }
  start() { this.state = 'recording' }
  stop() {
    this.state = 'inactive'
    // fire a complete, decodable block then onstop (synchronous for test determinism)
    if (this.ondataavailable) {
      this.ondataavailable({ data: new Blob(['audio'], { type: 'audio/webm' }) })
    }
    if (this.onstop) this.onstop()
  }
}

function installMediaMocks({ deny = false } = {}) {
  recorders = []
  tracks = [{ stop: vi.fn() }]
  const stream = { getTracks: () => tracks }
  global.MediaRecorder = FakeMediaRecorder
  global.navigator.mediaDevices = {
    getUserMedia: vi.fn(() =>
      deny
        ? Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' }))
        : Promise.resolve(stream)
    ),
  }
}

describe('useAudioRecorder: start / error / stop', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installMediaMocks()
    vi.spyOn(api, 'sendAudioBlock').mockResolvedValue({ block_id: 'b1' })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('start() requests the mic and enters recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    expect(result.current.status).toBe('idle')

    await act(async () => { await result.current.start() })

    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(result.current.status).toBe('recording')
    expect(recorders).toHaveLength(1)
    expect(recorders[0].state).toBe('recording')
  })

  it('permission rejection sets status=error and never starts a recorder', async () => {
    installMediaMocks({ deny: true })
    const { result } = renderHook(() => useAudioRecorder('sess-1'))

    await act(async () => { await result.current.start() })

    expect(result.current.status).toBe('error')
    expect(result.current.error).toMatch(/Mikrofonzugriff verweigert/)
    expect(recorders).toHaveLength(0)
  })

  it('stop() flushes the final block, releases tracks, returns to idle', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })

    await act(async () => { await result.current.stop() })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)         // final block sent
    expect(api.sendAudioBlock).toHaveBeenCalledWith('sess-1', expect.any(Blob))
    expect(tracks[0].stop).toHaveBeenCalled()                   // mic released
    expect(result.current.status).toBe('idle')
    expect(result.current.blocksSent).toBe(1)
  })
})

describe('useAudioRecorder: auto-send / sendNow / failures / lock', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installMediaMocks()
    vi.spyOn(api, 'sendAudioBlock').mockResolvedValue({ block_id: 'b1' })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('auto-send fires a flush at the configured interval and resumes recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    act(() => { result.current.setBlockSeconds(60) })
    await act(async () => { await result.current.start() })
    expect(recorders).toHaveLength(1)

    // advance one interval (60s)
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)
    expect(recorders).toHaveLength(2)               // a fresh recorder was created
    expect(recorders[1].state).toBe('recording')
    expect(result.current.status).toBe('recording')
  })

  it('sendNow flushes the current block and resets elapsed', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(result.current.elapsed).toBe(5)

    await act(async () => { await result.current.sendNow() })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)
    expect(result.current.elapsed).toBe(0)
    expect(result.current.blocksSent).toBe(1)
    expect(result.current.status).toBe('recording')   // still recording
  })

  it('a failed send surfaces an error but keeps recording', async () => {
    api.sendAudioBlock.mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })

    await act(async () => { await result.current.sendNow() })

    expect(result.current.error).toMatch(/Block konnte nicht gesendet werden/)
    expect(result.current.status).toBe('recording')
    expect(result.current.blocksSent).toBe(0)
  })

  it('setBlockSeconds is honored while idle but ignored while recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    act(() => { result.current.setBlockSeconds(180) })
    expect(result.current.blockSeconds).toBe(180)

    await act(async () => { await result.current.start() })
    act(() => { result.current.setBlockSeconds(60) })   // ignored while recording
    expect(result.current.blockSeconds).toBe(180)
  })

  it('stops recording and reports quota error when a block is rejected with 429', async () => {
    api.sendAudioBlock.mockRejectedValueOnce(Object.assign(new Error('quota'), { isQuota: true }))
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })

    await act(async () => { await result.current.sendNow() })   // triggers flush -> rejected

    expect(result.current.status).toBe('idle')          // recorder stopped
    expect(result.current.error).toMatch(/Kontingent/)
    expect(tracks[0].stop).toHaveBeenCalled()           // mic released
  })

  it('exposes remaining seconds from a successful block', async () => {
    api.sendAudioBlock.mockResolvedValueOnce({ status: 'processing', remaining_seconds: 90 })
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })
    await act(async () => { await result.current.sendNow() })
    expect(result.current.remainingSeconds).toBe(90)
  })
})
