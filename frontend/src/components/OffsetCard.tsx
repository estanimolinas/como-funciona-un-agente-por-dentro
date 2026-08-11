import type { ReactNode } from 'react'

interface OffsetCardProps {
  children: ReactNode
  className?: string
}

export function OffsetCard({ children, className = '' }: OffsetCardProps) {
  return (
    <div className="relative">
      <div className="absolute inset-0 translate-x-1 translate-y-1 rounded bg-black" />
      <div className={`relative z-10 rounded border-2 border-slate-100 ${className}`}>
        {children}
      </div>
    </div>
  )
}
