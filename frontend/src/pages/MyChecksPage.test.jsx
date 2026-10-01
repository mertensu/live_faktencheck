import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MyChecksPage } from './MyChecksPage'

const renderPage = () => render(<MemoryRouter><MyChecksPage /></MemoryRouter>)

describe('MyChecksPage', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('asks for a code when none is stored', () => {
    renderPage()
    expect(screen.getByText(/mit einem zugangscode/i)).toBeDefined()
  })

  it('lists the own sessions with claim counts', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([
      { session_id: 's1', title: 'Hart aber fair', date: '', created_at: '2026-09-30T20:15:00', claims: 3, hoch: 2, niedrig: 1, unklar: 0 },
    ]), { status: 200, headers: { 'content-type': 'application/json' } }))
    renderPage()
    expect(await screen.findByText('Hart aber fair')).toBeDefined()
    expect(screen.getByText('3 Aussagen')).toBeDefined()
    expect(screen.getByText(/2 hoch/)).toBeDefined()
    expect(screen.queryByText(/unklar/)).toBeNull()
    expect(fetch.mock.calls[0][1].headers['X-Access-Code']).toBe('abc')
  })

  it('shows the empty state', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]', {
      status: 200, headers: { 'content-type': 'application/json' },
    }))
    renderPage()
    expect(await screen.findByText(/noch keine eigenen checks/i)).toBeDefined()
  })
})

describe('MyChecksPage delete', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('deletes a session after confirmation and removes it from the list', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    const json = (body) => new Response(JSON.stringify(body), {
      status: 200, headers: { 'content-type': 'application/json' },
    })
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json([
        { session_id: 's1', title: 'Weg damit', created_at: '2026-09-30T20:15:00', claims: 0, hoch: 0, niedrig: 0, unklar: 0 },
      ]))
      .mockResolvedValueOnce(json({ status: 'deleted', session_id: 's1' }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /weg damit löschen/i }))
    await waitFor(() => expect(screen.queryByText('Weg damit')).toBeNull())
    expect(fetch.mock.calls[1][0]).toMatch(/\/api\/sessions\/s1$/)
    expect(fetch.mock.calls[1][1].method).toBe('DELETE')
  })

  it('does nothing when the confirmation is cancelled', async () => {
    localStorage.setItem('fc_access_code', 'abc')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([
      { session_id: 's1', title: 'Bleibt', created_at: '', claims: 0, hoch: 0, niedrig: 0, unklar: 0 },
    ]), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /bleibt löschen/i }))
    expect(screen.getByText('Bleibt')).toBeDefined()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
