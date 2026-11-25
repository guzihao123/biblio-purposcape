import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { App } from '../src/App'

it('moves from a real public-session response to keyboard-operable mode confirmation', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/session') {
        return {
          ok: true,
          status: 201,
          json: vi.fn().mockResolvedValue({ session_id: 'session-123' }),
        }
      }
      return {
        ok: true,
        status: 201,
        json: vi.fn().mockResolvedValue({
          id: 'task-1',
          state: 'collecting_mode',
          next_card: 'mode',
          card: {
            id: 'mode',
            eyebrow: '用途确认',
            title: '这次洞察用来做什么？',
            description: '选择最贴近当前目标的一项。',
            options: [
              { value: 'A', label: 'A 选题立项前摸底', description: '领域全景', preview: '摸底' },
              { value: 'B', label: 'B 撰写标书/立项依据', description: '项目论证', preview: '标书' },
              { value: 'C', label: 'C 撰写论文引言与讨论', description: '论文写作', preview: '论文' },
              { value: 'D', label: 'D 组会或团队学习', description: '主题调研', preview: '组会' },
            ],
          },
        }),
      }
    }),
  )

  render(<App />)
  await user.click(screen.getByRole('button', { name: '开始研究' }))

  expect(await screen.findByRole('heading', { name: '这次洞察用来做什么？' })).toBeVisible()
  const optionGroup = screen.getByRole('group', { name: '单选选项' })
  const optionLabels = [
    'A 选题立项前摸底',
    'B 撰写标书/立项依据',
    'C 撰写论文引言与讨论',
    'D 组会或团队学习',
  ]
  expect(within(optionGroup).getAllByRole('button')).toHaveLength(4)
  for (const label of optionLabels) {
    expect(within(optionGroup).getByRole('button', { name: label })).toBeVisible()
  }

  const option = within(optionGroup).getByRole('button', { name: 'A 选题立项前摸底' })
  option.focus()
  await user.keyboard(' ')

  expect(option).toHaveFocus()
  expect(option).toHaveAttribute('aria-pressed', 'true')
  expect(
    within(optionGroup).getByRole('button', { name: 'B 撰写标书/立项依据' }),
  ).toHaveAttribute('aria-pressed', 'false')

  await user.click(screen.getByRole('button', { name: '确认选择' }))
  expect(screen.getByRole('status')).toHaveTextContent('已确认：A 选题立项前摸底')
})

it('keeps accessibility pinch zoom enabled in the global viewport', () => {
  const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
  const parsedDocument = new DOMParser().parseFromString(html, 'text/html')
  const viewport = parsedDocument.querySelector<HTMLMetaElement>('meta[name="viewport"]')

  expect(viewport).not.toBeNull()
  expect(viewport?.content).not.toMatch(/user-scalable\s*=\s*no/i)
  expect(viewport?.content).not.toMatch(/maximum-scale\s*=\s*1(?:\.0+)?(?=\s*(?:,|$))/i)
})

it('clears prefixed and unprefixed card backdrop filters on narrow screens', () => {
  const styleElement = document.createElement('style')
  styleElement.textContent = readFileSync(
    resolve(process.cwd(), 'src/styles/full-power.css'),
    'utf8',
  )
  document.head.append(styleElement)

  const narrowScreenRule = Array.from(styleElement.sheet?.cssRules ?? []).find(
    (rule): rule is CSSMediaRule =>
      rule.type === CSSRule.MEDIA_RULE &&
      (rule as CSSMediaRule).conditionText === '(max-width: 760px)',
  )
  expect(narrowScreenRule).toBeDefined()

  const cardRule = Array.from(narrowScreenRule?.cssRules ?? []).find(
    (rule): rule is CSSStyleRule =>
      rule.type === CSSRule.STYLE_RULE &&
      (rule as CSSStyleRule).selectorText === '.full-power-card',
  )
  expect(cardRule).toBeDefined()
  expect(cardRule?.style.getPropertyValue('backdrop-filter')).toBe('none')
  expect(cardRule?.style.getPropertyValue('-webkit-backdrop-filter')).toBe('none')
  styleElement.remove()
})
