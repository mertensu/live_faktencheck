import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTabAudio } from './useTabAudio'

const track = (kind) => ({ kind, readyState: 'live', stop: vi.fn(), addEventListener: vi.fn() })

function shareTab({ audio = true } = {}) {
  const video = track('video')
  const sound = audio ? [track('audio')] : []
  navigator.mediaDevices.getDisplayMedia = vi.fn(() => Promise.resolve({
    getVideoTracks: () => [video],
    getAudioTracks: () => sound,
  }))
  return { video, sound }
}

describe('useTabAudio', () => {
  beforeEach(() => {
    global.navigator.mediaDevices = {}
    global.MediaStream = class {
      constructor(tracks) { this.tracks = tracks }
      getTracks() { return this.tracks }
      getAudioTracks() { return this.tracks.filter((t) => t.kind === 'audio') }
    }
  })

  it('keeps only the audio of the shared tab', async () => {
    const { video, sound } = shareTab()
    const { result } = renderHook(() => useTabAudio())
    let stream
    await act(async () => { stream = await result.current.pick() })
    expect(video.stop).toHaveBeenCalled()
    expect(stream.getTracks()).toEqual(sound)
    expect(result.current.stream).toBe(stream)
    expect(result.current.error).toBeNull()
  })

  it('asks to tick "Tab-Audio teilen" when the tab came without sound', async () => {
    const { video } = shareTab({ audio: false })
    const { result } = renderHook(() => useTabAudio())
    let stream
    await act(async () => { stream = await result.current.pick() })
    expect(stream).toBeNull()
    expect(video.stop).toHaveBeenCalled()
    expect(result.current.error).toMatch(/Tab-Audio teilen/)
  })

  it('stays quiet when the operator cancels the prompt', async () => {
    navigator.mediaDevices.getDisplayMedia = vi.fn(() =>
      Promise.reject(Object.assign(new Error('cancel'), { name: 'NotAllowedError' })))
    const { result } = renderHook(() => useTabAudio())
    await act(async () => { await result.current.pick() })
    expect(result.current.stream).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('stops the shared tab when released', async () => {
    const { sound } = shareTab()
    const { result } = renderHook(() => useTabAudio())
    await act(async () => { await result.current.pick() })
    act(() => { result.current.release() })
    expect(sound[0].stop).toHaveBeenCalled()
    expect(result.current.stream).toBeNull()
  })
})
