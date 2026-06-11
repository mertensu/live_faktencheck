import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sendAudioBlock, setSessionAutoCheck, approveClaims, discardClaims } from './api'

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

describe('claim + auto-check helpers', () => {
  beforeEach(() => { localStorage.clear(); global.fetch = vi.fn() })
  afterEach(() => { vi.restoreAllMocks() })

  const okJson = (body) => ({
    ok: true, status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body), url: '',
  })

  it('setSessionAutoCheck POSTs {enabled} with auth header', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson({ auto_check: true }))

    const res = await setSessionAutoCheck('sess-1', true)

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/sessions\/sess-1\/auto-check$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    expect(JSON.parse(opts.body)).toEqual({ enabled: true })
    expect(res).toEqual({ auto_check: true })
  })

  it('setSessionAutoCheck throws on non-ok', async () => {
    global.fetch.mockResolvedValue({
      ok: false, status: 403, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ detail: 'nope' }), url: '',
    })
    await expect(setSessionAutoCheck('s', true)).rejects.toThrow('nope')
  })

  it('approveClaims POSTs claims + session_id with auth header', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson({ status: 'processing' }))

    await approveClaims('sess-1', [{ name: 'A', claim: 'X' }])

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/approve-claims$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    const body = JSON.parse(opts.body)
    expect(body.session_id).toBe('sess-1')
    expect(body.claims).toEqual([{ name: 'A', claim: 'X' }])
    expect(body.block_id).toMatch(/^swipe_\d+$/)
  })

  it('discardClaims POSTs claims + session_id', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson({ status: 'discarded' }))

    await discardClaims('sess-1', [{ name: 'A', claim: 'X' }])

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/discard-claims$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    const body = JSON.parse(opts.body)
    expect(body.session_id).toBe('sess-1')
    expect(body.claims).toEqual([{ name: 'A', claim: 'X' }])
  })
})
