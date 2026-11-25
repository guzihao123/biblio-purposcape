import type { ReactNode } from 'react'

interface PageTransitionProps {
  children: ReactNode
  className?: string
}

export function PageTransition({ children, className = '' }: PageTransitionProps) {
  return (
    <div className={`page-transition ${className}`.trim()} data-motion="page-enter">
      {children}
    </div>
  )
}
