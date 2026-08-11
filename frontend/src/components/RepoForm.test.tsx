import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RepoForm } from './RepoForm'

describe('RepoForm', () => {
  // RepoForm seeds its apiKey field from localStorage on mount, and one of
  // the tests below submits a form with an API key, which writes it to
  // localStorage. jsdom's localStorage persists across tests within a file
  // (not reset automatically between tests), so without this, an earlier
  // test's assertion that submitting without an API key produces
  // `apiKey: undefined` would only pass because of test execution order.
  beforeEach(() => {
    localStorage.clear()
  })

  it('calls onSubmit with the entered repo URL and question', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/url del repo/i), 'https://github.com/pypa/sampleproject')
    await user.type(screen.getByLabelText(/pregunta/i), 'How is the version defined?')
    await user.click(screen.getByRole('button', { name: /preguntar/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      repoUrl: 'https://github.com/pypa/sampleproject',
      question: 'How is the version defined?',
      apiKey: undefined,
    })
  })

  it('includes the API key when the optional field is filled', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/url del repo/i), 'https://github.com/a/b')
    await user.type(screen.getByLabelText(/pregunta/i), 'q')
    await user.click(screen.getByRole('button', { name: /agregar/i }))
    await user.type(screen.getByLabelText(/api key/i), 'secret-key')
    await user.click(screen.getByRole('button', { name: /preguntar/i }))

    expect(onSubmit).toHaveBeenCalledWith({
      repoUrl: 'https://github.com/a/b',
      question: 'q',
      apiKey: 'secret-key',
    })
  })

  it('fills the form when an example button is clicked', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.click(screen.getAllByRole('button', { name: /probar:/i })[0])

    const repoUrlInput = screen.getByLabelText(/url del repo/i) as HTMLInputElement
    const questionInput = screen.getByLabelText(/pregunta/i) as HTMLInputElement
    expect(repoUrlInput.value).not.toBe('')
    expect(questionInput.value).not.toBe('')
  })

  it('fills the form with Spanish example questions', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.click(screen.getAllByRole('button', { name: /probar:/i })[0])

    const questionInput = screen.getByLabelText(/pregunta/i) as HTMLInputElement
    expect(questionInput.value).toMatch(/^¿/)
  })

  it('does not call onSubmit when the repo URL is empty', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/pregunta/i), 'q')
    await user.click(screen.getByRole('button', { name: /preguntar/i }))

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('shows an always-visible explanation when the API key field is expanded', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    expect(screen.queryByText(/CODERAG_API_KEY/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /agregar/i }))

    expect(screen.getByText(/opcional.*CODERAG_API_KEY.*configurada/i)).toBeInTheDocument()
  })
})
