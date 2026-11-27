import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '../src/App'
import type { TaskCard } from '../src/components/TaskWizard'

function responseWith(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response
}

const directionCard: TaskCard = {
  id: 'direction',
  eyebrow: '方向确认',
  title: '研究方向或核心问题',
  description: '输入一句话方向。',
  custom: { label: '研究方向或核心问题', placeholder: '输入方向' },
  options: [],
}

const modeCard: TaskCard = {
  id: 'mode',
  eyebrow: '用途确认',
  title: '这次洞察用来做什么？',
  description: '选择用途。',
  options: [
    { value: 'A', label: 'A 选题立项前摸底', description: '领域全景', preview: '摸底' },
    { value: 'B', label: 'B 撰写标书/立项依据', description: '项目论证', preview: '标书' },
    { value: 'C', label: 'C 撰写论文引言与讨论', description: '论文写作', preview: '论文' },
    { value: 'D', label: 'D 组会或团队学习', description: '主题调研', preview: '组会' },
  ],
}

const termsCard: TaskCard = {
  id: 'terms',
  eyebrow: '术语确认',
  title: '以下候选学术术语，选 1 个或多个用于检索。',
  description: '多个术语用逗号分隔。',
  multiple: true,
  custom: { label: '自定义学术术语', placeholder: '输入术语' },
  options: [],
}

const yearsCard: TaskCard = {
  id: 'years',
  eyebrow: '年限确认',
  title: '重点关注的时间范围',
  description: '选择年限。',
  options: [
    { value: 'A', label: 'A 近3年（最新前沿）', description: '近三年', preview: '前沿' },
    { value: 'B', label: 'B 近5年', description: '近五年', preview: '五年' },
    { value: 'C', label: 'C 近10年（含演进脉络）', description: '近十年', preview: '脉络' },
    { value: 'D', label: 'D 不限，覆盖经典与最新（推荐）', description: '不限', preview: '全部' },
  ],
}

const adjustmentCard: TaskCard = {
  id: 'adjustment',
  eyebrow: '检索后调整',
  title: '看完分布，要不要调整？',
  description: '可多选。',
  multiple: true,
  options: [
    { value: 'terms', label: '调整学术术语', description: '重检索', preview: '术语' },
    { value: 'years', label: '调整年限范围', description: '限定范围', preview: '年限' },
    { value: 'mode', label: '调整洞察用途', description: '用途', preview: '用途' },
    { value: 'continue', label: '按原计划继续（进入交付形式选择）', description: '冻结设定', preview: '继续' },
  ],
}

const deliveryCard: TaskCard = {
  id: 'delivery',
  eyebrow: '交付形式确认',
  title: '希望得到的交付形式',
  description: '最后一问。',
  options: [
    { value: 'A', label: 'A 正式调研报告（Word，含文献依据）', description: 'Word', preview: 'Word' },
    { value: 'B', label: 'B 仅对话中给要点和代表文献', description: '对话', preview: '对话' },
    { value: 'C', label: 'C 展示 PPT', description: 'PPT', preview: 'PPT' },
  ],
}

function taskWith(card: TaskCard | null, state: string, nextCard: string | null) {
  return {
    id: 'task-1',
    session_id: 'session-1',
    skill_version_id: 'version-1',
    state,
    next_card: nextCard,
    card,
    created_at: '2026-11-24T00:00:00Z',
    updated_at: '2026-11-24T00:00:00Z',
    progress: null,
  }
}

beforeEach(() => {
  window.history.replaceState({}, '', '/')
})

describe('complete web flow', () => {
  it('creates a task and completes direction, mode, terms and year confirmation', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/session') return responseWith(201, { session_id: 'session-1' })
      if (url === '/api/tasks' && method === 'POST') return responseWith(201, taskWith(directionCard, 'collecting_mode', 'direction'))
      if (url.includes('/answers/direction')) return responseWith(200, taskWith(modeCard, 'collecting_mode', 'mode'))
      if (url.includes('/answers/mode')) return responseWith(200, taskWith(termsCard, 'collecting_terms', 'terms'))
      if (url.includes('/answers/terms')) return responseWith(200, taskWith(yearsCard, 'collecting_years', 'years'))
      if (url.includes('/answers/years')) {
        return responseWith(200, {
          ...taskWith(null, 'searching', null),
          job_id: 'job-1',
          progress: { stage: 'search', message: '正在检索与整理论文池', percent: 45, checkpoint: null },
        })
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))
    await user.type(await screen.findByRole('textbox', { name: '研究方向或核心问题' }), '城市内涝韧性')
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    await user.click(await screen.findByRole('button', { name: 'A 选题立项前摸底' }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    await user.type(await screen.findByLabelText('自定义学术术语'), 'urban flooding, underground garage')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    await user.click(await screen.findByRole('button', { name: 'A 近3年（最新前沿）' }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    expect(await screen.findByText('正在检索与整理论文池')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '45')
    expect(screen.getByText('阶段：search')).toBeVisible()
    expect(screen.getByText('45%')).toBeVisible()
    const bodies = fetchMock.mock.calls.map(([, init]) => init?.body).filter(Boolean)
    expect(bodies).toContain(JSON.stringify({ value: { direction: '城市内涝韧性' } }))
    expect(bodies).toContain(JSON.stringify({ value: { terms: ['urban flooding', 'underground garage'] } }))
  })

  it('shows dashboard, honors original-plan continuation and opens the report with downloads', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/session') return responseWith(201, { session_id: 'session-1' })
      if (url === '/api/tasks' && method === 'POST') return responseWith(201, taskWith(adjustmentCard, 'dashboard_ready', 'adjustment'))
      if (url === '/api/tasks/task-1/dashboard') {
        return responseWith(200, {
          data: { overview: '不限年限共 50 篇；免疫微环境与预测标志物占比较高。' },
          artifacts: [
            { name: 'desktop.html', url: '/signed/desktop', size: 100 },
            { name: 'mobile.html', url: '/signed/mobile', size: 90 },
          ],
        })
      }
      if (url.includes('/answers/adjustment')) return responseWith(200, taskWith(deliveryCard, 'adjusting', 'delivery'))
      if (url.includes('/answers/delivery')) return responseWith(200, taskWith(null, 'done', null))
      if (url === '/api/tasks/task-1/report') {
        return responseWith(200, {
          outline: '1. 领域格局\n2. 研究空白\n3. 方向卡',
          sample: '方向卡·动态多组学耐药分型',
          body: '领域正文与第1推荐 [1]（据摘要）。\n\n## 参考文献\n\n[1] 真实文献',
          references: '[1] 真实文献',
          verification: { clean: true, report: '全部 9 项无失败', conformance: '通过' },
          artifacts: [{ name: '综述初稿.docx', url: '/signed/draft.docx', size: 1000 }],
        })
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))
    expect(await screen.findByText(/不限年限共 50 篇/)).toBeVisible()
    expect(screen.getByTitle('满血版文献图谱')).toHaveAttribute('src', '/signed/desktop')

    await user.click(screen.getByRole('button', { name: /按原计划继续/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    await user.click(await screen.findByRole('button', { name: /B 仅对话中给要点和代表文献/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    expect(await screen.findByText('方向卡·动态多组学耐药分型')).toBeVisible()
    expect(screen.getByText(/领域正文与第1推荐/)).toBeVisible()
    expect(screen.queryByText('全部 9 项无失败')).not.toBeInTheDocument()
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '下载 Word 报告' })).toHaveAttribute('href', '/signed/draft.docx')
  })
})
