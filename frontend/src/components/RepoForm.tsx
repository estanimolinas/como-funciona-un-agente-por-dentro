import { useState, type FormEvent } from 'react'

import type { AskStreamParams } from '../types'

interface RepoFormProps {
  onSubmit: (params: AskStreamParams) => void
}

const EXAMPLES: { label: string; repoUrl: string; question: string }[] = [
  {
    label: 'pypa/sampleproject — How is the package version defined?',
    repoUrl: 'https://github.com/pypa/sampleproject',
    question: 'How is the package version defined?',
  },
  {
    label: 'pallets/click — How does the @click.command decorator work?',
    repoUrl: 'https://github.com/pallets/click',
    question: 'How does the @click.command decorator work?',
  },
]

export function RepoForm({ onSubmit }: RepoFormProps) {
  const [repoUrl, setRepoUrl] = useState('')
  const [question, setQuestion] = useState('')
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('coderag_api_key') ?? '')
  const [showApiKey, setShowApiKey] = useState(false)

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmedRepoUrl = repoUrl.trim()
    const trimmedQuestion = question.trim()
    if (!trimmedRepoUrl || !trimmedQuestion) return

    const trimmedApiKey = apiKey.trim()
    if (trimmedApiKey) {
      localStorage.setItem('coderag_api_key', trimmedApiKey)
    } else {
      localStorage.removeItem('coderag_api_key')
    }

    onSubmit({
      repoUrl: trimmedRepoUrl,
      question: trimmedQuestion,
      apiKey: trimmedApiKey || undefined,
    })
  }

  function fillExample(example: (typeof EXAMPLES)[number]) {
    setRepoUrl(example.repoUrl)
    setQuestion(example.question)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span>Repo URL</span>
        <input
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span>Question</span>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="How does X work?"
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
        />
      </label>
      <button
        type="button"
        onClick={() => setShowApiKey((v) => !v)}
        className="self-start text-sm text-slate-400 underline"
      >
        {showApiKey ? 'Hide' : 'Add'} API key (optional)
      </button>
      {showApiKey ? (
        <label className="flex flex-col gap-1">
          <span>API key</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
          />
        </label>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            onClick={() => fillExample(example)}
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400"
          >
            Try: {example.label}
          </button>
        ))}
      </div>
      <button
        type="submit"
        className="self-start rounded bg-sky-600 px-4 py-2 font-semibold text-white"
      >
        Ask
      </button>
    </form>
  )
}
