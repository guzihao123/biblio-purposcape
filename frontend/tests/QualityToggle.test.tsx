import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

import { App } from '../src/App'

function mockApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/session') {
        return { ok: true, status: 201, json: vi.fn().mockResolvedValue({ session_id: 'session-123' }) }
      }
      return {
        ok: true,
        status: 201,
        json: vi.fn().mockResolvedValue({
          id: 'task-1',
          state: 'collecting_mode',
          next_card: 'mode',
          card: { id: 'mode', title: '用途确认', options: [] },
        }),
      }
    }),
  )
}

beforeEach(() => {
  window.localStorage.clear()
  mockApi()
})

it('cycles the performance mode from auto to lite to full', async () => {
  const user = userEvent.setup()
  render(<App />)
  await user.click(screen.getByRole('button', { name: '开始研究' }))

  const toggle = await screen.findByRole('button', { name: '性能模式' })
  expect(toggle).toHaveTextContent('性能：自动')

  await user.click(toggle)
  expect(toggle).toHaveTextContent('性能：流畅')
  expect(window.localStorage.getItem('pl-quality-mode')).toBe('lite')

  await user.click(toggle)
  expect(toggle).toHaveTextContent('性能：画质')
  expect(window.localStorage.getItem('pl-quality-mode')).toBe('full')

  await user.click(toggle)
  expect(toggle).toHaveTextContent('性能：自动')
  expect(window.localStorage.getItem('pl-quality-mode')).toBe('auto')
})