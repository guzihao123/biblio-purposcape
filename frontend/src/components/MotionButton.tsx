import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface MotionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  selected?: boolean
}

export function MotionButton({ children, className = '', selected = false, ...props }: MotionButtonProps) {
  return (
    <button
      className={`motion-button${selected ? ' motion-button--selected' : ''} ${className}`.trim()}
      data-motion="button"
      aria-pressed={props['aria-pressed'] ?? selected}
      {...props}
    >
      <span className="motion-button__content">{children}</span>
      <span className="motion-button__ripple" aria-hidden="true" />
    </button>
  )
}
