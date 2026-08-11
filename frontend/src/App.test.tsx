import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the page heading and the repo form', () => {
    render(<App />)
    expect(screen.getByText('coderag-mcp')).toBeInTheDocument()
    expect(screen.getByLabelText(/url del repo/i)).toBeInTheDocument()
  })
})
