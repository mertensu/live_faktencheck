import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PipelineAnimation } from './PipelineAnimation'

const current = () => screen.getByRole('button', { current: 'step' })

describe('PipelineAnimation', () => {
  beforeEach(() => {
    window.matchMedia = () => ({ matches: false })
  })

  it('moves only when the reader clicks, and starts over after the last step', () => {
    render(<PipelineAnimation />)
    expect(current().textContent).toContain('Zuhören')
    expect(screen.getByRole('button', { name: /Zurück/ }).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: /Weiter/ }))
    expect(current().textContent).toContain('Auswählen')
    fireEvent.click(screen.getByRole('button', { name: /Zurück/ }))
    expect(current().textContent).toContain('Zuhören')
    fireEvent.click(screen.getByRole('button', { name: /Markieren/ }))
    fireEvent.click(screen.getByRole('button', { name: /Von vorn/ }))
    expect(current().textContent).toContain('Zuhören')
  })

  it('jumps to a step on click and shows its scene', () => {
    render(<PipelineAnimation />)
    fireEvent.click(screen.getByRole('button', { name: /Umformulieren/ }))
    expect(screen.getByText(/In Deutschland/)).toBeTruthy()
    expect(screen.getByText('Einordnung')).toBeTruthy()
  })

  it('shows complete scenes with reduced motion', () => {
    window.matchMedia = () => ({ matches: true })
    const { container } = render(<PipelineAnimation />)
    expect(container.querySelector('.pa').classList.contains('pa--still')).toBe(true)
  })
})
