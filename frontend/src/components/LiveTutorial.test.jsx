import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LiveTutorial } from './LiveTutorial'

// Mark all of transcript line `index` and release the mouse, like the operator does.
function markLine(container, index) {
  const textNode = container.querySelector(`.live-bubble-line[data-index="${index}"]`).firstChild
  const range = document.createRange()
  range.setStart(textNode, 0)
  range.setEnd(textNode, textNode.length)
  window.getSelection().removeAllRanges()
  window.getSelection().addRange(range)
  fireEvent.mouseUp(textNode)
}

const bubbleNames = (container) =>
  [...container.querySelectorAll('.live-bubble:not(.live-bubble-partial) .live-bubble-name')].map((el) => el.textContent.replace(' ▾', ''))

describe('LiveTutorial', () => {
  it('names a label from the bubble on, on the real transcript', () => {
    const { container } = render(<LiveTutorial onClose={vi.fn()} />)
    expect(bubbleNames(container)).toEqual(['Sprecher A', 'Sprecher B', 'Sprecher A', 'Sprecher B'])
    fireEvent.click(screen.getAllByRole('button', { name: /Sprecher A/ })[0])
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Anna Keller' }))
    expect(bubbleNames(container)).toEqual(['Anna Keller', 'Sprecher B', 'Anna Keller', 'Sprecher B'])
    expect(screen.getByRole('status').textContent).toMatch(/ab dieser Sprechblase/)
  })

  it('practises the correction in two steps: 1 with "everything further", 2 without', () => {
    const { container } = render(<LiveTutorial onClose={vi.fn()} />)
    const next = () => fireEvent.click(screen.getByRole('button', { name: /^Weiter:/ }))
    next()

    // Korrektur 1, checkbox on (default): the later line of label A goes to Sandra too.
    markLine(container, 1)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Sandra Berger' }))
    expect(bubbleNames(container)).toEqual(['Anna Keller', 'Sandra Berger', 'Peter Müller', 'Sandra Berger'])
    expect(screen.getByRole('status').textContent).toMatch(/„auch alles Weitere“ aktiviert/)
    expect(screen.getByRole('tab', { name: /Korrektur 1/ }).textContent).toContain('✓')
    next()

    // Korrektur 2, wrong first (checkbox left on): no tick, a retry instead.
    markLine(container, 1)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Sandra Berger' }))
    expect(screen.getByRole('tab', { name: /Korrektur 2/ }).textContent).not.toContain('✓')
    fireEvent.click(screen.getByRole('button', { name: /noch einmal versuchen/ }))
    expect(screen.queryByRole('status')).toBeNull()

    // Korrektur 2, checkbox off: only the marked passage.
    markLine(container, 1)
    fireEvent.click(screen.getByRole('checkbox', { name: /auch alles Weitere von Sprecher A/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Sandra Berger' }))
    expect(bubbleNames(container)).toEqual(['Anna Keller', 'Sandra Berger', 'Peter Müller', 'Anna Keller'])
    expect(screen.getByRole('status').textContent).toMatch(/„auch alles Weitere“ deaktiviert/)
    expect(screen.getByRole('tab', { name: /Korrektur 2/ }).textContent).toContain('✓')
  })

  it('opens a result from its mark and closes on the last step', () => {
    const onClose = vi.fn()
    const { container } = render(<LiveTutorial onClose={onClose} />)
    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole('button', { name: /^Weiter:/ }))
    fireEvent.click(container.querySelector('.live-transcript-mark.verdict-niedrig'))
    expect(screen.getByRole('dialog', { name: 'Prüfergebnis' }).textContent).toContain('Die Renten sind seit 2010 real gesunken.')
    fireEvent.click(screen.getByRole('button', { name: 'Fertig – Übung schließen' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('ticks the tab of a step once its task is done, and jumps between tabs', () => {
    render(<LiveTutorial onClose={vi.fn()} />)
    const tab = (name) => screen.getByRole('tab', { name: new RegExp(name) })
    expect(tab('Namen vergeben').textContent).not.toContain('✓')
    fireEvent.click(screen.getAllByRole('button', { name: /Sprecher A/ })[0])
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Anna Keller' }))
    expect(tab('Namen vergeben').textContent).toContain('✓')
    fireEvent.click(tab('Ergebnisse lesen'))
    expect(tab('Ergebnisse lesen').getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('button', { name: 'Fertig – Übung schließen' })).toBeTruthy()
  })

  it('can be skipped at any step, also with Escape', () => {
    const onClose = vi.fn()
    render(<LiveTutorial onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
