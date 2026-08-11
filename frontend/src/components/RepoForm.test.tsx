import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RepoForm } from './RepoForm'

describe('RepoForm', () => {
  it('calls onSubmit with the entered repo URL and question', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/repo url/i), 'https://github.com/pypa/sampleproject')
    await user.type(screen.getByLabelText(/question/i), 'How is the version defined?')
    await user.click(screen.getByRole('button', { name: /ask/i }))

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

    await user.type(screen.getByLabelText(/repo url/i), 'https://github.com/a/b')
    await user.type(screen.getByLabelText(/question/i), 'q')
    await user.click(screen.getByRole('button', { name: /add/i }))
    await user.type(screen.getByLabelText(/api key/i), 'secret-key')
    await user.click(screen.getByRole('button', { name: /ask/i }))

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

    await user.click(screen.getAllByRole('button', { name: /try:/i })[0])

    const repoUrlInput = screen.getByLabelText(/repo url/i) as HTMLInputElement
    const questionInput = screen.getByLabelText(/question/i) as HTMLInputElement
    expect(repoUrlInput.value).not.toBe('')
    expect(questionInput.value).not.toBe('')
  })

  it('does not call onSubmit when the repo URL is empty', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<RepoForm onSubmit={onSubmit} />)

    await user.type(screen.getByLabelText(/question/i), 'q')
    await user.click(screen.getByRole('button', { name: /ask/i }))

    expect(onSubmit).not.toHaveBeenCalled()
  })
})
