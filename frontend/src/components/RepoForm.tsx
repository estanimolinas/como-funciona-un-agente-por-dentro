import { useState, type FormEvent } from 'react'

import type { AskStreamParams } from '../types'
import { OffsetCard } from './OffsetCard'

interface RepoFormProps {
  onSubmit: (params: AskStreamParams) => void
}

const EXAMPLES: { label: string; repoUrl: string; question: string }[] = [
  {
    label: 'pypa/sampleproject — ¿Cómo se define la versión del paquete?',
    repoUrl: 'https://github.com/pypa/sampleproject',
    question: '¿Cómo se define la versión del paquete?',
  },
  {
    label:
      'asabeneh/30-days-of-python — ¿Cómo están implementadas las operaciones aritméticas en los ejemplos de este repo?',
    repoUrl: 'https://github.com/asabeneh/30-days-of-python',
    question:
      '¿Cómo están implementadas las operaciones aritméticas (suma, resta, multiplicación) en los ejemplos de este repositorio?',
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
    <OffsetCard className="p-6">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span>URL del repo</span>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            aria-describedby="repo-url-note"
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
          />
        </label>
        <p id="repo-url-note" className="text-xs text-slate-500">
          Búsqueda semántica disponible solo para repos Python — otros
          lenguajes usan exploración directa de archivos.
        </p>
        <label className="flex flex-col gap-1">
          <span>Pregunta</span>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="¿Cómo funciona X?"
            className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
          />
        </label>
        <button
          type="button"
          onClick={() => setShowApiKey((v) => !v)}
          className="self-start text-sm text-slate-400 underline"
        >
          {showApiKey ? 'Ocultar' : 'Agregar'} API key (opcional)
        </button>
        {showApiKey ? (
          <>
            <label className="flex flex-col gap-1">
              <span>API key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="rounded border-2 border-slate-700 bg-slate-900 px-3 py-2 focus:border-amber-400 focus:outline-none"
              />
            </label>
            <p className="text-xs text-slate-400">
              CODERAG_API_KEY es una variable de entorno opcional que quien
              corre este backend puede configurar para protegerlo. Si vos
              no la configuraste, dejá este campo vacío.
            </p>
          </>
        ) : null}
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() => fillExample(example)}
                className="rounded border-2 border-amber-700 bg-amber-950 px-2 py-1 text-xs text-amber-100 hover:bg-amber-900"
              >
                Probar: {example.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            El agente decide qué método usar según la pregunta — no siempre elige búsqueda
            semántica, incluso con estos ejemplos.
          </p>
        </div>
        <button
          type="submit"
          className="self-start rounded border-2 border-slate-100 bg-amber-500 px-4 py-2 font-semibold text-slate-950 hover:bg-amber-400"
        >
          Preguntar
        </button>
      </form>
    </OffsetCard>
  )
}
