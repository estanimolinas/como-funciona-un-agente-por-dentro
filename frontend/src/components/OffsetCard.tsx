import type { ReactNode } from 'react'

interface OffsetCardProps {
  children: ReactNode
  className?: string
}

export function OffsetCard({ children, className = '' }: OffsetCardProps) {
  return (
    <div className="relative">
      <div aria-hidden="true" className="absolute inset-0 translate-x-1.5 translate-y-1.5 rounded bg-slate-100" />
      <div className={`relative z-10 rounded border-2 border-slate-100 bg-slate-950 ${className}`}>
        {children}
      </div>
    </div>
  )
}
