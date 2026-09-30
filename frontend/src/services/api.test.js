import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchFactChecks, openStreamUrl } from './api'

const okJson = (body) => ({
  ok: true, status: 200,
  headers: { get: () => 'application/json' },
  text: async () => JSON.stringify(body), url: '',
})

describe('fetchFactChecks', () => {
  beforeEach(() => { localStorage.clear(); global.fetch = vi.fn() })
  afterEach(() => { vi.restoreAllMocks() })

  it('GETs the session-scoped fact-checks with the access code attached', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson([{ id: 1 }]))

    const res = await fetchFactChecks('sess 1')

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/fact-checks\?session_id=sess%201$/)
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    expect(res).toEqual([{ id: 1 }])
  })

  it('returns an empty list on a non-ok response', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500 })
    expect(await fetchFactChecks('sess-1')).toEqual([])
  })
})

describe('openStreamUrl', () => {
  beforeEach(() => { localStorage.clear() })

  it('uses ws(s) and carries session + code as query params', () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    const url = new URL(openStreamUrl('sess-1'))
    expect(url.protocol).toMatch(/^wss?:$/)
    expect(url.pathname).toBe('/api/stream')
    expect(url.searchParams.get('session_id')).toBe('sess-1')
    expect(url.searchParams.get('code')).toBe('SECRET')
  })
})
