import { useState } from 'react'

import { RepoForm } from './components/RepoForm'
import { RunCard } from './components/RunCard'
import type { AskStreamParams } from './types'

interface Run extends AskStreamParams {
  id: number
}

function App() {
  const [runs, setRuns] = useState<Run[]>([])

  function handleSubmit(params: AskStreamParams) {
    setRuns((prev) => [...prev, { id: prev.length, ...params }])
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6 text-slate-100">
      <div className="flex flex-col gap-2">
        <h1 className="text-4xl font-bold tracking-tight">
          Agent<span className="text-rose-500">Trace</span>
        </h1>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-400">
          <li>Pegá la URL de un repo público de GitHub.</li>
          <li>Escribí tu pregunta.</li>
          <li>Mirá en vivo cómo el agente decide qué herramienta usar.</li>
          <li>Leé la respuesta final.</li>
        </ol>
      </div>
      <div className="max-w-2xl">
        <RepoForm onSubmit={handleSubmit} />
      </div>
      <div className="flex flex-col gap-4">
        {runs.map((run) => (
          <RunCard key={run.id} repoUrl={run.repoUrl} question={run.question} apiKey={run.apiKey} />
        ))}
      </div>
    </div>
  )
}

export default App
