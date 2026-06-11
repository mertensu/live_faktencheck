import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sendAudioBlock } from './api'

describe('sendAudioBlock', () => {
  beforeEach(() => {
    localStorage.clear()
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('POSTs multipart form data with audio + session_id and no JSON content-type', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue({
      ok: true,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ block_id: 'block_1' }),
      url: '', status: 202,
    })
    const blob = new Blob(['xx'], { type: 'audio/webm' })

    const result = await sendAudioBlock('sess-42', blob)

    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/audio-block$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    expect(opts.headers['Content-Type']).toBeUndefined()
    expect(opts.body).toBeInstanceOf(FormData)
    expect(opts.body.get('session_id')).toBe('sess-42')
    expect(opts.body.get('audio')).toBeInstanceOf(Blob)
    expect(result).toEqual({ block_id: 'block_1' })
  })

  it('throws on a non-ok response', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ detail: 'nope' }),
      url: '', status: 403,
    })
    const blob = new Blob(['xx'], { type: 'audio/webm' })
    await expect(sendAudioBlock('s', blob)).rejects.toThrow('nope')
  })
})
