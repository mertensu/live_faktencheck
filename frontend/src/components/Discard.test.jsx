import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { LiveTranscript } from './LiveTranscript'
import { FactCheckStream } from './FactCheckStream'
import { setFactCheckDiscarded } from '../services/api'

vi.mock('../services/api', async (orig) => ({ ...(await orig()), setFactCheckDiscarded: vi.fn(() => Promise.resolve({})) }))

const claim = {
  id: 7, speaker: 'Connemann', label: 'A', claim: 'Strom ist teurer geworden.', source: 'Strom ist teurer geworden.',
  status: 'done', consistency: 'niedrig', begruendung: 'Die Preise sind gesunken.', quellen: [],
}
const live = {
  status: 'streaming', partial: '', speakerMap: { A: [[-1, 'Connemann']] },
  transcript: [{ label: 'A', text: 'Strom ist teurer geworden. Punkt.' }], claims: [claim],
}
const openMark = (container) => fireEvent.click(container.querySelector('[data-claim-id="7"]'))

describe('Verwerfen', () => {
  beforeEach(() => {
    setFactCheckDiscarded.mockClear()
    window.matchMedia = window.matchMedia || (() => ({ matches: false }))
  })

  it('is not offered without canDiscard (viewers, the guide)', () => {
    const { container } = render(<LiveTranscript live={live} />)
    openMark(container)
    expect(screen.queryByRole('button', { name: 'Check verwerfen' })).toBeNull()
  })

  it('in the guide the button is shown but does nothing', () => {
    const { container } = render(<LiveTranscript live={live} inertDiscard />)
    openMark(container)
    fireEvent.click(screen.getByRole('button', { name: 'Check verwerfen' }))
    expect(container.querySelector('[data-claim-id="7"]')).not.toBeNull()
    expect(setFactCheckDiscarded).not.toHaveBeenCalled()
  })

  it('hides the mark at once and undo brings it back', async () => {
    const { container } = render(<LiveTranscript live={live} canDiscard />)
    openMark(container)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Check verwerfen' })) })
    expect(container.querySelector('[data-claim-id="7"]')).toBeNull()
    expect(setFactCheckDiscarded).toHaveBeenLastCalledWith(7, true)

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Rückgängig' })) })
    expect(container.querySelector('[data-claim-id="7"]')).not.toBeNull()
    expect(setFactCheckDiscarded).toHaveBeenLastCalledWith(7, false)
  })

  it('a failed discard brings the check back and says so', async () => {
    setFactCheckDiscarded.mockImplementationOnce(() => Promise.reject(new Error('404')))
    const { container } = render(<LiveTranscript live={live} canDiscard />)
    openMark(container)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Check verwerfen' })) })
    expect(container.querySelector('[data-claim-id="7"]')).not.toBeNull()
    expect(screen.getByRole('status').textContent).toContain('Verwerfen fehlgeschlagen')
  })

  it('removes a card from the results list', async () => {
    const fcs = [{ id: 7, sprecher: 'Connemann', behauptung: 'Strom ist teurer geworden.', consistency: 'niedrig',
      begruendung: 'x', quellen: [], timestamp: '2026-10-20T20:00:00' }]
    render(<FactCheckStream factChecks={fcs} canDiscard />)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Check verwerfen' })) })
    expect(screen.queryByText('Strom ist teurer geworden.')).toBeNull()
    expect(setFactCheckDiscarded).toHaveBeenLastCalledWith(7, true)
  })
})
