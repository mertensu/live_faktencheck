import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useEffect } from 'react'
import { MyChecksSidebar, SidebarProvider, useSidebar } from './MyChecksSidebar'

const SESSIONS = [
  { session_id: 's1', title: 'Hart aber fair', created_at: '2026-09-30T20:15:00', claims: 3, hoch: 2, niedrig: 1, unklar: 0 },
  { session_id: 's2', title: 'Lanz', created_at: '2026-08-20T23:10:00', claims: 0, hoch: 0, niedrig: 0, unklar: 0 },
]

const json = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'content-type': 'application/json' },
})

function Live({ on }) {
  const { setLive } = useSidebar()
  useEffect(() => { setLive(on) }, [on, setLive])
  return null
}

const renderSidebar = ({ path = '/s1', enabled = true, live = false } = {}) => render(
  <MemoryRouter initialEntries={[path]}>
    <SidebarProvider enabled={enabled}>
      <Live on={live} />
      <MyChecksSidebar />
    </SidebarProvider>
  </MemoryRouter>
)

describe('MyChecksSidebar', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('renders nothing when disabled', () => {
    vi.spyOn(globalThis, 'fetch')
    const { container } = renderSidebar({ enabled: false })
    expect(container.innerHTML).toBe('')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('lists own sessions grouped by month with counts', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(SESSIONS))
    renderSidebar()
    expect(await screen.findByText('Hart aber fair')).toBeDefined()
    expect(screen.getByText('3 Aussagen')).toBeDefined()
    expect(screen.getByText('September 2026')).toBeDefined()
    expect(screen.getByText('August 2026')).toBeDefined()
    expect(screen.getByText('Hart aber fair').closest('a').getAttribute('href')).toBe('/s1')
  })

  it('deletes a session after the in-page confirmation', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(SESSIONS))
      .mockResolvedValueOnce(json({ status: 'deleted', session_id: 's2' }))
      .mockImplementation(async () => json([SESSIONS[0]]))
    renderSidebar()
    fireEvent.click(await screen.findByRole('button', { name: 'Lanz löschen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }))
    await waitFor(() => expect(screen.queryByText('Lanz')).toBeNull())
    expect(fetch.mock.calls[1][0]).toMatch(/\/api\/sessions\/s2$/)
    expect(fetch.mock.calls[1][1].method).toBe('DELETE')
  })

  it('cancelling the confirmation deletes nothing', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(SESSIONS))
    renderSidebar()
    fireEvent.click(await screen.findByRole('button', { name: 'Lanz löschen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }))
    expect(screen.getByText('Lanz')).toBeDefined()
    expect(fetch.mock.calls.every(([, opts]) => !opts?.method)).toBe(true)
  })

  it('while live: other checks are locked, no delete, no new check', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(SESSIONS))
    renderSidebar({ live: true })
    expect(await screen.findByText('Lanz')).toBeDefined()
    expect(screen.getByText('Lanz').closest('a')).toBeNull()
    expect(screen.getByText('Hart aber fair').closest('a')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /löschen/ })).toBeNull()
    expect(screen.queryByText(/neuer check/i)).toBeNull()
    expect(screen.getByText('LIVE')).toBeDefined()
  })
})
