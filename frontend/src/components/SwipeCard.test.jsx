import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SwipeCard } from './SwipeCard'

const claim = { id: 'b-0', name: 'Anna', claim: 'Die Inflation liegt bei 2%.' }

describe('SwipeCard', () => {
  it('renders the claim text, speaker and the remaining counter', () => {
    render(<SwipeCard claim={claim} remaining={3} onKeep={() => {}} onDiscard={() => {}} />)
    expect(screen.getByText('Anna')).toBeDefined()
    expect(screen.getByText(/Inflation liegt bei 2%/)).toBeDefined()
    expect(screen.getByText(/noch 3/i)).toBeDefined()
  })

  it('Behalten calls onKeep with the unedited claim', () => {
    const onKeep = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={onKeep} onDiscard={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /behalten/i }))
    expect(onKeep).toHaveBeenCalledWith({ name: 'Anna', claim: 'Die Inflation liegt bei 2%.' })
  })

  it('Verwerfen calls onDiscard with the claim', () => {
    const onDiscard = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={() => {}} onDiscard={onDiscard} />)
    fireEvent.click(screen.getByRole('button', { name: /verwerfen/i }))
    expect(onDiscard).toHaveBeenCalledWith({ name: 'Anna', claim: 'Die Inflation liegt bei 2%.' })
  })

  it('edit mode surfaces edited speaker + claim to onKeep', () => {
    const onKeep = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={onKeep} onDiscard={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /bearbeiten/i }))
    fireEvent.change(screen.getByLabelText(/sprecher/i), { target: { value: 'Bert' } })
    fireEvent.change(screen.getByLabelText(/aussage/i), { target: { value: 'Neu.' } })
    fireEvent.click(screen.getByRole('button', { name: /prüfen/i }))
    expect(onKeep).toHaveBeenCalledWith({ name: 'Bert', claim: 'Neu.' })
  })
})
