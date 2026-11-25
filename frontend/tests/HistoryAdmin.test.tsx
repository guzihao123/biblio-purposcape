import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AdminSkillPage } from '../src/pages/AdminSkillPage'
import { HistoryPage } from '../src/pages/HistoryPage'

function responseWith(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response
}

describe('HistoryPage', () => {
  it('lists only API-returned session tasks and opens the selected task', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responseWith(200, {
      tasks: [
        { id: 'task-a', state: 'done', next_card: null, created_at: '2026-11-24T00:00:00Z', direction: '城市内涝' },
        { id: 'task-b', state: 'searching', next_card: null, created_at: '2026-11-23T00:00:00Z', direction: '肝癌免疫' },
      ],
    })))

    render(<HistoryPage onOpen={onOpen} />)
    await user.click(await screen.findByRole('button', { name: /城市内涝/ }))
    expect(onOpen).toHaveBeenCalledWith('task-a')
    expect(screen.getByText(/肝癌免疫/)).toBeVisible()
  })
})

describe('AdminSkillPage', () => {
  it('uses a transient admin token for draft, regression, publish and rollback', async () => {
    const user = userEvent.setup()
    const published = {
      id: 'v1', version: 1, state: 'published', parent_id: null,
      content: { cards: { order: ['direction', 'mode', 'terms', 'years', 'adjustment', 'delivery'] } },
      regression_report: { passed: true },
    }
    const draft = { ...published, id: 'v2', version: 2, state: 'draft', parent_id: 'v1' }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/admin/skill/versions') return responseWith(200, { versions: [published] })
      if (url === '/api/admin/skill/drafts' && method === 'POST') return responseWith(201, draft)
      if (url === '/api/admin/skill/versions/v2/regression') return responseWith(200, { passed: true, checks: { hcc: 'passed' } })
      if (url === '/api/admin/skill/versions/v2/publish') return responseWith(200, { ...draft, state: 'published' })
      if (url === '/api/admin/skill/versions/v1/rollback') return responseWith(200, published)
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminSkillPage />)
    await user.type(screen.getByLabelText('管理员令牌'), 'admin-secret')
    await user.click(screen.getByRole('button', { name: '加载版本' }))
    expect(await screen.findByText(/当前发布：v1/)).toBeVisible()

    await user.click(screen.getByRole('button', { name: '创建草稿' }))
    await user.click(await screen.findByRole('button', { name: '运行回归' }))
    await user.click(await screen.findByRole('button', { name: '发布草稿' }))
    expect(await screen.findByText(/当前发布：v2/)).toBeVisible()

    await user.click(screen.getByRole('button', { name: '回退到 v1' }))
    expect(await screen.findByText(/当前发布：v1/)).toBeVisible()
    expect(localStorage.getItem('admin_token')).toBeNull()
    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.headers).toMatchObject({ 'X-Admin-Token': 'admin-secret' })
    }
  })
})
