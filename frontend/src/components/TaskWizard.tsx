import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { OptionCard } from './OptionCard'
import type { OptionCardOption } from './OptionCard'
import { MotionButton } from './MotionButton'
import { PageTransition } from './PageTransition'

export type TaskAnswer = Record<string, string | string[] | Record<string, string>>
export type TaskSubmit = (answer: TaskAnswer) => void | PromiseLike<void>

export interface CustomTaskField {
  label: string
  placeholder: string
}

export interface ConditionalTaskField {
  name: string
  label: string
  placeholder?: string
  kind?: 'text' | 'textarea' | 'select'
  options?: { value: string; label: string }[]
  group?: string
  required?: boolean
}

export interface TaskCard {
  id: string
  eyebrow: string
  title: string
  description: string
  options: readonly OptionCardOption[]
  multiple?: boolean
  custom?: CustomTaskField
  conditional_fields?: Record<string, ConditionalTaskField[]>
  onSubmit?: TaskSubmit
}

interface TaskWizardProps {
  card: TaskCard
  onSubmit?: TaskSubmit
}

export function TaskWizard({ card, onSubmit }: TaskWizardProps) {
  const [selected, setSelected] = useState<string[]>([])
  const [customValue, setCustomValue] = useState('')
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [cStep, setCStep] = useState<'mode' | 'route' | 'info'>('mode')
  const [cRoute, setCRoute] = useState('')
  const [confirmed, setConfirmed] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    setSelected([])
    setCustomValue('')
    setFieldValues({})
    setCStep('mode')
    setCRoute('')
    setSubmitting(false)
    submittingRef.current = false
  }, [card.id])

  const selectOption = (value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setCStep('mode')
    setCRoute('')
    if (!card.multiple) setCustomValue('')
    setSelected((current) => {
      if (!card.multiple) return [value]
      return current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    })
  }

  const updateCustomValue = (value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setCustomValue(value)
    if (!card.multiple) setSelected([])
  }

  const activeFields = card.conditional_fields?.[selected[0]] ?? []
  const isCMode = card.id === 'mode' && selected[0] === 'C'
  const cRouteField = activeFields.find((field) => field.name === 'c_route')
  const visibleFields = isCMode
    ? cStep === 'info'
      ? activeFields.filter((field) => field.name !== 'c_route')
      : []
    : activeFields
  const missingRequired = visibleFields.some((field) => field.required && !fieldValues[field.name]?.trim())
  const routeOptions = (cRouteField?.options ?? []).map((option) => ({
    ...option,
    description: option.value === 'C1' ? '围绕本文研究问题组织引言' : option.value === 'C2' ? '围绕领域知识体系组织独立综述' : '分别生成两份文本并检查衔接',
    preview: option.value,
  }))
  const displayOptions = isCMode && cStep === 'route' ? routeOptions : isCMode && cStep === 'info' ? [] : card.options

  const updateFieldValue = (name: string, value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setFieldValues((current) => ({ ...current, [name]: value }))
  }

  const submitSelection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isCMode && cStep === 'mode') {
      setCStep('route')
      return
    }
    if (isCMode && cStep === 'route') {
      if (cRoute) setCStep('info')
      return
    }
    const customText = customValue.trim()
    const customTerms = card.multiple
      ? customText.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
      : []
    const hasCustom = Boolean(card.custom && customText)
    if ((selected.length === 0 && !hasCustom) || missingRequired || confirmed.length > 0 || submittingRef.current) return

    submittingRef.current = true
    setSubmitting(true)
    const confirmedValues = hasCustom
      ? card.multiple
        ? [...selected, ...customTerms]
        : [customText]
      : selected
    const answer: TaskAnswer = {
      [card.id]: card.multiple ? confirmedValues : confirmedValues[0],
    }
    for (const field of visibleFields) {
      const value = fieldValues[field.name] ?? field.options?.[0]?.value ?? ''
      if (field.group) {
        const group = (answer[field.group] as Record<string, string> | undefined) ?? {}
        answer[field.group] = { ...group, [field.name]: value }
      } else {
        answer[field.name] = value
      }
    }
    if (isCMode) answer.c_route = cRoute
    const submit = card.onSubmit ?? onSubmit
    try {
      const result = submit?.(answer)
      if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
        await result
      }
      setConfirmed(confirmedValues)
    } catch {
      setConfirmed([])
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <PageTransition>
      <main className="full-power-site wizard-page">
        <div className="site-orbit site-orbit--one" aria-hidden="true" />
        <div className="site-orbit site-orbit--two" aria-hidden="true" />
        <section className="wizard-shell" aria-labelledby={`${card.id}-title`}>
          <header className="wizard-header">
            <a className="site-brand" href="#main-card" aria-label="研究图谱确认卡">
              <span className="site-brand__mark" aria-hidden="true"><span /><span /><span /></span>
              <span>研究图谱</span>
            </a>
            <span className="wizard-step">确认卡 · {card.id}</span>
          </header>

          <div className="wizard-intro" id="main-card">
            <p className="site-eyebrow">{isCMode && cStep !== 'mode' ? (cStep === 'route' ? 'C模式任务' : '本文信息') : card.eyebrow}</p>
            <h1 id={`${card.id}-title`}>
              {isCMode && cStep === 'route'
                ? '本次最需要完成哪一项？'
                : isCMode && cStep === 'info'
                  ? '本文的核心研究问题、拟用方法与预期创新是什么？（可跳过；目标期刊可一并说明）'
                  : card.title}
            </h1>
            <p>{isCMode && cStep !== 'mode' ? '选择后统一确认；本文细节可跳过，按通用口径写框架。' : card.description}</p>
          </div>

          <form onSubmit={submitSelection}>
            {displayOptions.length > 0 && (
              <div className="option-grid" role="group" aria-label={card.multiple ? '可多选选项' : '单选选项'}>
                {displayOptions.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    selected={isCMode && cStep === 'route' ? cRoute === option.value : selected.includes(option.value)}
                    onSelect={isCMode && cStep === 'route' ? setCRoute : selectOption}
                  />
                ))}
              </div>
            )}
            {visibleFields.length > 0 && (
              <div className="wizard-conditional-fields">
                {visibleFields.map((field) => {
                  const id = `${card.id}-${field.name}`
                  const value = fieldValues[field.name] ?? field.options?.[0]?.value ?? ''
                  return (
                    <div key={field.name} className="wizard-field">
                      <label htmlFor={id}>{field.label}</label>
                      {field.kind === 'select' ? (
                        <select id={id} value={value} onChange={(event) => updateFieldValue(field.name, event.target.value)}>
                          {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      ) : field.kind === 'textarea' ? (
                        <textarea id={id} rows={4} value={value} placeholder={field.placeholder} onChange={(event) => updateFieldValue(field.name, event.target.value)} />
                      ) : (
                        <input id={id} value={value} placeholder={field.placeholder} onChange={(event) => updateFieldValue(field.name, event.target.value)} />
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {card.custom && (
              <div className="wizard-custom">
                <label htmlFor={`${card.id}-custom`}>{card.custom.label}</label>
                <textarea
                  id={`${card.id}-custom`}
                  value={customValue}
                  placeholder={card.custom.placeholder}
                  rows={card.multiple ? 3 : 2}
                  onChange={(event) => updateCustomValue(event.target.value)}
                />
              </div>
            )}

            <footer className="wizard-actions">
              <p className="wizard-hint" aria-live="polite">
                {selected.length > 0
                  ? `已选 ${selected.length} 项`
                  : card.multiple
                    ? '可多选，选择后统一确认'
                    : '请选择一项或输入内容，再确认'}
              </p>
              <MotionButton
                className="full-power-button"
                type="submit"
                disabled={isCMode && cStep === 'route' ? !cRoute : (selected.length === 0 && !customValue.trim()) || missingRequired || submitting}
              >
                确认选择
                <span aria-hidden="true">↗</span>
              </MotionButton>
            </footer>
            {confirmed.length > 0 && (
              <p className="wizard-receipt" role="status">
                <span className="status-dot" aria-hidden="true" />
                已确认：
                {confirmed.map((value) => card.options.find((option) => option.value === value)?.label ?? value).join('、')}
              </p>
            )}
          </form>
        </section>
      </main>
    </PageTransition>
  )
}
