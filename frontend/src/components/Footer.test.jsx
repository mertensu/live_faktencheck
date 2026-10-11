import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Footer } from './Footer'

const renderFooter = (slim) => render(
  <MemoryRouter initialEntries={['/']}>
    <Routes>
      <Route path="/" element={<Footer slim={slim} />} />
      <Route path="/datenschutz" element={<p>Datenschutzseite</p>} />
    </Routes>
  </MemoryRouter>
)

describe('Footer legal links', () => {
  it.each([false, true])('links to the Datenschutz page (slim=%s)', (slim) => {
    renderFooter(slim)
    expect(screen.getByRole('button', { name: 'Impressum' })).toBeDefined()
    fireEvent.click(screen.getByRole('link', { name: 'Datenschutz' }))
    expect(screen.getByText('Datenschutzseite')).toBeDefined()
  })
})
