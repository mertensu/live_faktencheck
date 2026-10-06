import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PipelineAnimation } from './PipelineAnimation'

const current = () => screen.getByRole('button', { current: 'step' })
// jsdom has no AnimationEvent, so React listens for the prefixed name there.
const finishStep = () => {
  const clock = screen.getByTestId('pa-clock')
  const name = 'AnimationEvent' in window ? 'animationend' : 'webkitAnimationEnd'
  fireEvent(clock, new Event(name, { bubbles: true }))
}

describe('PipelineAnimation', () => {
  beforeEach(() => {
    window.matchMedia = () => ({ matches: false })
  })

  it('advances to the next step when the progress bar finishes, and loops', () => {
    render(<PipelineAnimation />)
    expect(current().textContent).toContain('Zuhören')
    finishStep()
    expect(current().textContent).toContain('Auswählen')
    fireEvent.click(screen.getByRole('button', { name: /Markieren/ }))
    finishStep()
    expect(current().textContent).toContain('Zuhören')
  })

  it('jumps to a step on click and shows its scene', () => {
    render(<PipelineAnimation />)
    fireEvent.click(screen.getByRole('button', { name: /Umformulieren/ }))
    expect(screen.getByText(/In Deutschland/)).toBeTruthy()
    expect(screen.getByText('Einordnung')).toBeTruthy()
  })

  it('pauses and resumes', () => {
    const { container } = render(<PipelineAnimation />)
    fireEvent.click(screen.getByRole('button', { name: /Pause/ }))
    expect(container.querySelector('.pa').classList.contains('pa--halted')).toBe(true)
    expect(screen.getByRole('button', { name: /Abspielen/ })).toBeTruthy()
  })

  it('does not auto-advance with reduced motion', () => {
    window.matchMedia = () => ({ matches: true })
    const { container } = render(<PipelineAnimation />)
    expect(container.querySelector('.pa').classList.contains('pa--still')).toBe(true)
    expect(screen.queryByTestId('pa-clock')).toBeNull()
    expect(screen.queryByRole('button', { name: /Pause/ })).toBeNull()
  })
})
