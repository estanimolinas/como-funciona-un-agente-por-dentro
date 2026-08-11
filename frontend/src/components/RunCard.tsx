import { useMemo } from 'react'

import { useAskStream } from '../hooks/useAskStream'
import { OffsetCard } from './OffsetCard'
import { TwoColumnLog } from './TwoColumnLog'
import type { AskStreamParams } from '../types'

interface RunCardProps {
  repoUrl: string
  question: string
  apiKey?: string
}

export function RunCard({ repoUrl, question, apiKey }: RunCardProps) {
  // Built once (useMemo with an empty dep array) so useAskStream sees a
  // stable params identity for this card's whole lifetime and never
  // reopens the connection — see useAskStream's Task 2 contract.
  const params: AskStreamParams = useMemo(
    () => ({ repoUrl, question, apiKey }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const { events, status } = useAskStream(params)

  const hasDone = events.some((e) => e.type === 'done')
  const hasError = events.some((e) => e.type === 'error')
  const isTruncated = hasError && !hasDone

  return (
    <OffsetCard className="p-4">
      <div className="mb-2 text-sm text-slate-400">
        {repoUrl} — {question}
      </div>
      <p className="mb-2 text-xs text-slate-400">Así explora y responde el agente, en vivo:</p>
      <TwoColumnLog events={events} status={status} isTruncated={isTruncated} />
    </OffsetCard>
  )
}
