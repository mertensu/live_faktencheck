import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LiveTranscript } from './LiveTranscript'

const live = {
  status: 'streaming',
  partial: '',
  transcript: [
    { label: 'A', text: 'Was ist Ihre Antwort?' },
    { label: 'A', text: 'Strom ist teurer geworden. Punkt.' },
    { label: 'B', text: 'Das stimmt nicht.' },
    { label: null, text: 'Moment.' },
  ],
  speakerMap: { A: 'Connemann' },
  claims: [{
    id: 7, speaker: 'Connemann', label: 'A', claim: 'Strom ist teurer geworden.', source: 'Strom ist teurer geworden.',
    status: 'done', consistency: 'niedrig', begruendung: 'Die Preise sind gesunken.',
    quellen: [{ url: 'https://example.org', title: 'Quelle X' }],
  }],
}

describe('LiveTranscript', () => {
  it('groups consecutive lines of a label into one bubble; lines without a label stay neutral', () => {
    const { container } = render(<LiveTranscript live={live} />)
    const bubbles = container.querySelectorAll('.live-bubble')
    expect(bubbles).toHaveLength(3)
    expect(bubbles[0].querySelectorAll('.live-bubble-line')).toHaveLength(2)
    expect(bubbles[0].className).toMatch(/spk-0/)
    expect(bubbles[0].textContent).toContain('Connemann')
    expect(bubbles[1].className).toMatch(/spk-1/)
    expect(bubbles[2].className).toMatch(/spk-none/)
    expect(screen.getByText('Sprecher B')).toBeDefined()
    expect(screen.getByText('Unklar')).toBeDefined()
  })

  it('assigns a label to a guest from the bubble name', () => {
    const assignSpeaker = vi.fn()
    render(<LiveTranscript live={{ ...live, assignSpeaker }} speakers={['Connemann', 'Dröge']} />)
    fireEvent.click(screen.getByRole('button', { name: /Sprecher B/ }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Dröge' }))
    expect(assignSpeaker).toHaveBeenCalledWith('B', 'Dröge')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('clears an assignment', () => {
    const assignSpeaker = vi.fn()
    render(<LiveTranscript live={{ ...live, assignSpeaker }} speakers={['Connemann', 'Dröge']} />)
    fireEvent.click(screen.getByRole('button', { name: /Connemann/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Zuordnung entfernen' }))
    expect(assignSpeaker).toHaveBeenCalledWith('A', null)
  })

  it('offers no picker once the stream has stopped', () => {
    render(<LiveTranscript live={{ ...live, status: 'idle', assignSpeaker: vi.fn() }} speakers={['Dröge']} />)
    expect(screen.queryByRole('button', { name: /Sprecher B/ })).toBeNull()
  })

  it('shows the result only on hover or click of the marked passage', () => {
    render(<LiveTranscript live={live} />)
    expect(screen.queryByText('Die Preise sind gesunken.')).toBeNull()
    const mark = screen.getByText('Strom ist teurer geworden.', { selector: 'mark' })
    fireEvent.mouseEnter(mark)
    expect(screen.getByText('Die Preise sind gesunken.')).toBeDefined()
    expect(screen.getByText('Quelle X').getAttribute('href')).toBe('https://example.org')
    fireEvent.click(mark)
    fireEvent.mouseLeave(mark)
    expect(screen.getByRole('dialog')).toBeDefined() // pinned by the click
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('offers claims without a visible passage as badges', () => {
    const l = { ...live, claims: [{ ...live.claims[0], source: 'nicht im Text' }] }
    const { container } = render(<LiveTranscript live={l} />)
    expect(container.querySelector('.live-orphan')).not.toBeNull()
  })
})
