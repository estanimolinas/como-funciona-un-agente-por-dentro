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
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6 text-slate-100">
      <div className="flex flex-col gap-2">
        <h1 className="text-4xl font-bold tracking-tight">
          Agent<span className="text-rose-500">Trace</span>
        </h1>
        <p className="text-slate-400">
          Mirá en vivo cómo el agente explora el código para responder.
        </p>
      </div>
      <RepoForm onSubmit={handleSubmit} />
      <div className="flex flex-col gap-4">
        {runs.map((run) => (
          <RunCard key={run.id} repoUrl={run.repoUrl} question={run.question} apiKey={run.apiKey} />
        ))}
      </div>
    </div>
  )
}

export default App
