import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LiveTranscript } from './LiveTranscript'

const live = {
  status: 'streaming',
  partial: '',
  transcript: [
    { speaker: 'Connemann', label: 'A', text: 'Was ist Ihre Antwort?' },
    { speaker: 'Connemann', label: 'A', text: 'Strom ist teurer geworden. Punkt.' },
    { speaker: 'Unklar', label: 'B', text: 'Das stimmt nicht.' },
    { speaker: 'C', label: 'C', text: 'Moment.' },
  ],
  claims: [{
    id: 7, speaker: 'Connemann', claim: 'Strom ist teurer geworden.', source: 'Strom ist teurer geworden.',
    status: 'done', consistency: 'niedrig', begruendung: 'Die Preise sind gesunken.',
    quellen: [{ url: 'https://example.org', title: 'Quelle X' }],
  }],
}

describe('LiveTranscript', () => {
  it('groups consecutive lines of a speaker into one bubble; unnamed speakers stay neutral', () => {
    const { container } = render(<LiveTranscript live={live} />)
    const bubbles = container.querySelectorAll('.live-bubble')
    expect(bubbles).toHaveLength(3)
    expect(bubbles[0].querySelectorAll('.live-bubble-line')).toHaveLength(2)
    expect(bubbles[0].className).toMatch(/spk-0/)
    expect(bubbles[1].className).toMatch(/spk-none/)
    expect(bubbles[2].className).toMatch(/spk-none/)
    expect(screen.getByText('Sprecher C')).toBeDefined()
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
