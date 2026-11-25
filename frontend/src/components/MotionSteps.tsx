import { useEffect, useState } from 'react'

interface MotionStepsProps {
  steps: string[]
  current?: number
  interactive?: boolean
}

export function MotionSteps({ steps, current = 0, interactive = true }: MotionStepsProps) {
  const [internalActive, setInternalActive] = useState(current)
  const active = interactive ? internalActive : Math.max(0, Math.min(current, steps.length - 1))
  useEffect(() => setInternalActive(current), [current])
  return (
    <div className="motion-steps" aria-label="任务进度">
      <ol>
        {steps.map((step, index) => (
          <li key={step} className={`motion-step${active === index ? ' is-active' : ''}`}>
            <span className="motion-step__dot" aria-hidden="true" />
            <span>{step}</span>
          </li>
        ))}
      </ol>
      {interactive && (
        <button type="button" className="motion-button" onClick={() => setInternalActive((active + 1) % steps.length)}>
          下一阶段
        </button>
      )}
      <output aria-live="polite">当前：{steps[active]}</output>
    </div>
  )
}
