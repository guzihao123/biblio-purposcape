import { useId } from 'react'

export interface OptionCardOption {
  value: string
  label: string
  description?: string
  preview?: string
}

interface OptionCardProps {
  option: OptionCardOption
  selected: boolean
  onSelect: (value: string) => void
}

export function OptionCard({ option, selected, onSelect }: OptionCardProps) {
  const id = useId()
  const labelId = `${id}-label`
  const descriptionId = `${id}-description`

  return (
    <button
      type="button"
      className={`full-power-card full-power-option${selected ? ' is-selected' : ''}`}
      aria-labelledby={labelId}
      aria-describedby={option.description ? descriptionId : undefined}
      aria-pressed={selected}
      onClick={() => onSelect(option.value)}
    >
      <span className="full-power-option__topline">
        <span className="full-power-option__label" id={labelId}>
          {option.label}
        </span>
        <span className="full-power-option__indicator" aria-hidden="true">
          <span />
        </span>
      </span>
      {option.description && (
        <span className="full-power-option__description" id={descriptionId}>
          {option.description}
        </span>
      )}
      {option.preview && (
        <span
          className={`full-power-option__preview${option.preview.includes('\n') ? ' is-multiline' : ''}`}
          lang={/[\u4e00-\u9fff]/.test(option.preview) ? 'zh-CN' : 'en'}
        >
          {option.preview}
        </span>
      )}
    </button>
  )
}
