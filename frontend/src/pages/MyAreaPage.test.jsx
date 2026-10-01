import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MyAreaPage } from './MyAreaPage'

const renderPage = () => render(<MemoryRouter><MyAreaPage /></MemoryRouter>)

describe('MyAreaPage', () => {
  beforeEach(() => localStorage.clear())

  it('asks for a code when none is stored', () => {
    renderPage()
    expect(screen.getByText(/mit einem zugangscode/i)).toBeDefined()
  })

  it('points to the sidebar when a code is stored', () => {
    localStorage.setItem('fc_access_code', 'abc')
    renderPage()
    expect(screen.getByRole('heading', { name: 'Mein Bereich' })).toBeDefined()
    expect(screen.getByRole('button', { name: /meine checks öffnen/i })).toBeDefined()
  })
})
