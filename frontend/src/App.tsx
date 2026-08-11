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
      <h1 className="text-3xl font-bold">coderag-mcp</h1>
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
