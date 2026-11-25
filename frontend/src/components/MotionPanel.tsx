import { useState } from 'react'

interface MotionPanelProps {
  title: string
  lines: string[]
}

export function MotionPanel({ title, lines }: MotionPanelProps) {
  const [open, setOpen] = useState(false)
  return (
    <div className="motion-panel-wrap">
      <button type="button" className="motion-button" onClick={() => setOpen(!open)}>
        {open ? '收起证据面板' : '打开证据面板'}
      </button>
      {open && (
        <aside className="motion-panel" aria-label={title}>
          <h3>{title}</h3>
          {lines.map((line, index) => (
            <p className="motion-panel__line" style={{ animationDelay: `${100 + index * 15}ms` }} key={line}>
              {line}
            </p>
          ))}
        </aside>
      )}
    </div>
  )
}
