import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the page heading, subtitle, and the repo form', () => {
    render(<App />)
    // The wordmark is split across sibling elements (plain text + a
    // colored <span>), so getByText's default exact-string match won't
    // find it as one node — use a function matcher checking the parsed
    // element's combined text content instead.
    expect(
      screen.getByText((_, element) => element?.tagName.toLowerCase() === 'h1' && element.textContent === 'coderag-mcp'),
    ).toBeInTheDocument()
    expect(screen.getByText(/mirá en vivo cómo el agente explora el código/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url del repo/i)).toBeInTheDocument()
  })
})
