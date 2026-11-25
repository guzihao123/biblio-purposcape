import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

interface MotionTab {
  value: string
  label: string
}

interface MotionTabsProps {
  tabs: MotionTab[]
  value?: string
  onChange?: (value: string) => void
}

export function MotionTabs({ tabs, value, onChange }: MotionTabsProps) {
  const controlledIndex = Math.max(0, tabs.findIndex((tab) => tab.value === value))
  const [internalActive, setInternalActive] = useState(controlledIndex)
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([])
  const active = value === undefined ? internalActive : controlledIndex
  useEffect(() => {
    if (value !== undefined) setInternalActive(controlledIndex)
  }, [controlledIndex, value])
  const style = {
    left: `${active * (100 / tabs.length)}%`,
    width: `${100 / tabs.length}%`,
  } as CSSProperties

  const selectTab = (index: number) => {
    const tab = tabs[index]
    if (!tab) return
    setInternalActive(index)
    onChange?.(tab.value)
    tabButtons.current[index]?.focus()
  }

  return (
    <div className="motion-tabs" role="tablist">
      <span className="motion-tab-indicator" aria-hidden="true" style={style} />
      {tabs.map((tab, index) => (
        <button
          key={tab.value}
          ref={(element) => { tabButtons.current[index] = element }}
          type="button"
          role="tab"
          aria-selected={active === index}
          tabIndex={active === index ? 0 : -1}
          className={active === index ? 'is-active' : ''}
          onClick={() => selectTab(index)}
          onKeyDown={(event) => {
            let next: number
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
            else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length
            else if (event.key === 'Home') next = 0
            else if (event.key === 'End') next = tabs.length - 1
            else return
            event.preventDefault()
            selectTab(next)
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
