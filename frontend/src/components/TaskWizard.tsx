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
  required?: boolean
}

export interface ConditionalTaskField {
  name: string
  label: string
  placeholder?: string
  kind?: 'text' | 'textarea' | 'select'
  options?: OptionCardOption[]
  group?: string
  required?: boolean
}

export interface ProjectThemeDetails {
  name: string
  goal: string
  object: string
  method: string
  expected_output: string
  custom?: string
}

export interface ProjectThemeOption extends OptionCardOption {
  theme?: ProjectThemeDetails
}

export interface TaskCard {
  id: string
  eyebrow: string
  title: string
  description: string
  options: readonly OptionCardOption[]
  multiple?: boolean
  custom?: CustomTaskField
  custom_for?: readonly string[]
  conditional_fields?: Record<string, ConditionalTaskField[]>
  onSubmit?: TaskSubmit
}

// Skill 固定卡 2 的逐字说明；后端下发同文案，此处兜底避免旧 payload 丢说明。
const C_INFO_DESCRIPTIONS: Record<string, string> = {
  skip: '不提供本文细节，只给框架与占位提示，并在交付中注明。',
  upload: '用户提供论文文件或粘贴内容后，先提取研究目标、方法、数据与创新，再决定补检索。',
  oral: '用户直接说明研究问题、方法与创新，据此填写本文研究思路与贡献相关内容。',
}

interface TaskWizardProps {
  card: TaskCard
  onSubmit?: TaskSubmit
  loadProjectThemes?: () => Promise<ProjectThemeOption[]>
}

export function TaskWizard({ card, onSubmit, loadProjectThemes }: TaskWizardProps) {
  const [selected, setSelected] = useState<string[]>([])
  const [customValue, setCustomValue] = useState('')
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [cStep, setCStep] = useState<'mode' | 'route' | 'info'>('mode')
  const [cRoute, setCRoute] = useState('')
  const [cInfoRoute, setCInfoRoute] = useState('')
  const [bStep, setBStep] = useState<'mode' | 'theme' | 'project'>('mode')
  const [themeOptions, setThemeOptions] = useState<ProjectThemeOption[]>([])
  const [themeSelected, setThemeSelected] = useState('')
  const [themeCustomValue, setThemeCustomValue] = useState('')
  const [themesLoaded, setThemesLoaded] = useState(false)
  const [themesLoading, setThemesLoading] = useState(false)
  const [themeError, setThemeError] = useState('')
  const [confirmed, setConfirmed] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  useEffect(() => {
    setSelected([])
    setCustomValue('')
    setFieldValues({})
    setCStep('mode')
    setCRoute('')
    setCInfoRoute('')
    setBStep('mode')
    setThemeOptions([])
    setThemeSelected('')
    setThemeCustomValue('')
    setThemesLoaded(false)
    setThemesLoading(false)
    setThemeError('')
    setSubmitting(false)
    submittingRef.current = false
  }, [card.id])

  const selectOption = (value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setCStep('mode')
    setCRoute('')
    setCInfoRoute('')
    setBStep('mode')
    setThemeSelected('')
    setThemeCustomValue('')
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
    if (!card.multiple && !card.custom_for) setSelected([])
  }

  const isBMode = card.id === 'mode' && selected[0] === 'B'
  const isBModeThemeStep = isBMode && bStep === 'theme'
  const isBModeProjectStep = isBMode && bStep === 'project'

  useEffect(() => {
    if (!isBModeThemeStep || themesLoaded) return
    let active = true
    setThemesLoading(true)
    setThemeError('')
    const loading = loadProjectThemes
      ? loadProjectThemes()
      : Promise.resolve([] as ProjectThemeOption[])
    loading
      .then((options) => {
        if (!active) return
        setThemeOptions(options)
        setThemesLoaded(true)
        if (options.length === 0 && !loadProjectThemes) {
          setThemeError('可直接自定义项目主题，或返回重试候选生成。')
        }
      })
      .catch(() => {
        if (!active) return
        setThemeOptions([])
        setThemesLoaded(true)
        setThemeError('项目主题候选暂不可用，可直接自定义项目主题。')
      })
      .finally(() => {
        if (active) setThemesLoading(false)
      })
    return () => {
      active = false
    }
  }, [isBModeThemeStep, themesLoaded, loadProjectThemes])

  const activeFields = card.conditional_fields?.[selected[0]] ?? []
  const isCMode = card.id === 'mode' && selected[0] === 'C'
  const cRouteField = activeFields.find((field) => field.name === 'c_route')
  const cInfoRouteField = activeFields.find((field) => field.name === 'c_info_route')
  const visibleFields = isCMode
    ? cStep === 'info'
      ? activeFields.filter((field) => !['c_route', 'c_info_route', 'user_results'].includes(field.name))
        .filter((field) => field.name !== 'c_material' || cInfoRoute === 'upload' || cInfoRoute === 'oral')
      : []
    : isBMode
      ? bStep === 'project'
        ? activeFields
        : []
      : activeFields
  const customVisible = Boolean(card.custom) && (
    !card.custom_for || selected.some((value) => card.custom_for?.includes(value))
  )
  const missingCustom = Boolean(
    card.custom?.required && customVisible && !customValue.trim(),
  )
  const missingRequired = visibleFields.some((field) => field.required && !fieldValues[field.name]?.trim())
  const routeOptions = (cRouteField?.options ?? []).map((option) => ({
    ...option,
    description: option.value === 'C1' ? '围绕本文研究问题组织引言' : option.value === 'C2' ? '围绕领域知识体系组织独立综述' : '分别生成两份文本并检查衔接',
    preview: option.value,
  }))
  const infoOptions = (cInfoRouteField?.options ?? []).map((option) => ({
    ...option,
    description: C_INFO_DESCRIPTIONS[option.value] ?? option.description,
  }))
  const displayOptions = isCMode && cStep === 'route'
    ? routeOptions
    : isCMode && cStep === 'info'
      ? infoOptions
      : isBModeThemeStep
        ? themeOptions
        : isBModeProjectStep
          ? []
          : card.options
  const cInfoNeedsMaterial = cInfoRoute === 'upload' || cInfoRoute === 'oral'
  const cInfoMaterialReady = !cInfoNeedsMaterial || Boolean(fieldValues.c_material?.trim())
  const cInfoSelected = isCMode && cStep === 'info' ? Boolean(cInfoRoute) && cInfoMaterialReady : true
  const cardEyebrow = isCMode && cStep !== 'mode'
    ? (cStep === 'route' ? 'C模式任务' : '本文信息')
    : isBModeThemeStep
      ? '项目主题'
      : isBModeProjectStep
        ? '项目信息'
        : card.eyebrow
  const cardTitle = isCMode && cStep === 'route'
    ? '本次最需要完成哪一项？'
    : isCMode && cStep === 'info'
      ? '本文的核心研究问题、拟用方法与预期创新是什么？（可跳过；目标期刊可一并说明）'
      : isBModeThemeStep
        ? '请选择一个项目主题候选'
        : isBModeProjectStep
          ? '确认项目名称、目标与资助类别'
          : card.title
  const cardDescription = isCMode && cStep === 'route'
    ? '选择后统一确认；先选 C 模式任务，再选本文信息处理方式。'
    : isCMode && cStep === 'info'
      ? '单选一项；可粘贴初稿文本或口述研究问题与方法，目标期刊可一并填写。'
      : isBModeThemeStep
        ? '候选由当前研究方向凝练；选定后再填写项目名称与目标，也可直接自定义主题。'
        : isBModeProjectStep
          ? '可修改主题带入的名称与目标；研究方向将在选定项目主题后再检索。'
          : card.description

  const updateFieldValue = (name: string, value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setFieldValues((current) => ({ ...current, [name]: value }))
  }

  const selectTheme = (value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setThemeSelected(value)
    setThemeCustomValue('')
  }

  const updateThemeCustomValue = (value: string) => {
    submittingRef.current = false
    setSubmitting(false)
    setConfirmed([])
    setThemeCustomValue(value)
    if (value.trim()) setThemeSelected('')
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
    if (isBMode && bStep === 'mode') {
      setBStep('theme')
      return
    }
    if (isBMode && bStep === 'theme') {
      const customTheme = themeCustomValue.trim()
      const chosen = themeOptions.find((option) => option.value === themeSelected)
      if (!chosen && !customTheme) return
      const details: ProjectThemeDetails = chosen?.theme ?? {
        name: customTheme || chosen?.label || '',
        goal: chosen?.description || '',
        object: '',
        method: '',
        expected_output: '',
        custom: customTheme,
      }
      setFieldValues((current) => ({
        ...current,
        name: current.name?.trim() ? current.name : details.name,
        goal: current.goal?.trim() ? current.goal : details.goal,
      }))
      setBStep('project')
      return
    }
    const customText = customValue.trim()
    const customTerms = card.multiple
      ? customText.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
      : []
    const hasCustom = Boolean(card.custom && customText)
    if ((selected.length === 0 && !hasCustom) || missingRequired || missingCustom || confirmed.length > 0 || submittingRef.current) return

    submittingRef.current = true
    setSubmitting(true)
    const confirmedValues = hasCustom
      ? card.custom_for
        ? selected
        : card.multiple
          ? [...selected, ...customTerms]
          : [customText]
      : selected
    const answer: TaskAnswer = {
      [card.id]: card.multiple ? confirmedValues : confirmedValues[0],
    }
    if (card.custom_for && hasCustom) answer.custom = customText
    if (isBMode && bStep === 'project') {
      const chosenOption = themeOptions.find((option) => option.value === themeSelected)
      const customTheme = themeCustomValue.trim()
      answer.theme = (chosenOption?.theme ?? {
        name: customTheme || chosenOption?.label || '',
        goal: chosenOption?.description || '',
        object: '',
        method: '',
        expected_output: '',
        custom: customTheme,
      }) as unknown as Record<string, string>
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
    if (isCMode) {
      answer.c_route = cRoute
      answer.c_info_route = cInfoRoute
      if (!cInfoNeedsMaterial) answer.c_material = ''
    }
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
            <p className="site-eyebrow">{cardEyebrow}</p>
            <h1 id={`${card.id}-title`}>{cardTitle}</h1>
            <p>{cardDescription}</p>
          </div>

          {submitting && (
            <div className="wizard-loading" role="status" aria-live="polite">
              <div className="wizard-loading__engine" aria-hidden="true">
                <svg viewBox="0 0 32 32" focusable="false">
                  <circle cx="13" cy="13" r="8" />
                  <path d="m19 19 8 8" />
                </svg>
                <span className="wizard-loading__ring" />
              </div>
              <div className="wizard-loading__copy">
                <strong>正在确认选择</strong>
                <span>正在准备下一步研究流程…</span>
              </div>
            </div>
          )}

          <form onSubmit={submitSelection}>
            {displayOptions.length > 0 && (
              <div className="option-grid" role="group" aria-label={card.multiple ? '可多选选项' : '单选选项'}>
                {displayOptions.map((option) => (
                  <OptionCard
                    key={option.value}
                    option={option}
                    selected={
                      isCMode && cStep === 'route'
                        ? cRoute === option.value
                        : isCMode && cStep === 'info'
                          ? cInfoRoute === option.value
                          : isBModeThemeStep
                            ? themeSelected === option.value
                            : selected.includes(option.value)
                    }
                    onSelect={
                      isCMode && cStep === 'route'
                        ? setCRoute
                        : isCMode && cStep === 'info'
                          ? setCInfoRoute
                          : isBModeThemeStep
                            ? selectTheme
                            : selectOption
                    }
                  />
                ))}
              </div>
            )}
            {isBModeThemeStep && (
              <div className="wizard-custom">
                <label htmlFor={`${card.id}-theme-custom`}>自定义项目主题</label>
                <textarea
                  id={`${card.id}-theme-custom`}
                  value={themeCustomValue}
                  placeholder="写明项目名称、研究对象、拟用方法与预期产出"
                  rows={3}
                  onChange={(event) => updateThemeCustomValue(event.target.value)}
                />
                {themesLoading && <p className="wizard-hint" role="status">正在根据研究方向凝练项目主题候选…</p>}
                {!themesLoading && themeError && <p className="wizard-hint" role="status">{themeError}</p>}
                {!themesLoading && !themeError && themeOptions.length === 0 && (
                  <p className="wizard-hint" role="status">暂无候选，可直接自定义项目主题。</p>
                )}
              </div>
            )}
            {visibleFields.length > 0 && (
              <div className="wizard-conditional-fields">
                {visibleFields.map((field) => {
                  const id = `${card.id}-${field.name}`
                  const value = fieldValues[field.name] ?? field.options?.[0]?.value ?? ''
                  const label = isCMode && cStep === 'info' && field.name === 'c_material' && cInfoRoute === 'oral'
                    ? '现场口述：研究问题与方法'
                    : field.label
                  return (
                    <div key={field.name} className="wizard-field">
                      <label htmlFor={id}>{label}</label>
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
            {card.custom && customVisible && (
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
                {isCMode && cStep === 'info'
                  ? !cInfoRoute
                    ? '请选择一项本文信息处理方式'
                    : cInfoNeedsMaterial && !fieldValues.c_material?.trim()
                      ? '请粘贴初稿材料或口述研究问题与方法'
                      : '已选本文信息处理方式，可补充目标期刊'
                  : isBModeThemeStep
                    ? themeSelected
                      ? '已选一个项目主题，确认后填写项目名称与目标'
                      : themeCustomValue.trim()
                        ? '将使用自定义项目主题，确认后填写项目名称与目标'
                        : '请选择一个主题候选，或直接自定义项目主题'
                    : isBModeProjectStep
                      ? '确认后进入术语卡'
                      : customVisible && card.custom?.required && !customValue.trim()
                        ? '请填写自定义用途，再确认'
                        : selected.length > 0
                          ? `已选 ${selected.length} 项`
                          : card.multiple
                            ? '可多选，选择后统一确认'
                            : '请选择一项或输入内容，再确认'}
              </p>
              <MotionButton
                className="full-power-button"
                type="submit"
                disabled={
                  isCMode && cStep === 'route'
                    ? !cRoute
                    : isCMode && cStep === 'info'
                      ? !cInfoSelected || submitting
                      : isBModeThemeStep
                        ? themesLoading || (!themeSelected && !themeCustomValue.trim())
                        : (selected.length === 0 && !customValue.trim()) || missingRequired || missingCustom || submitting
                }
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
