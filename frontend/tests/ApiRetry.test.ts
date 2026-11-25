import { afterEach, expect, it, vi } from 'vitest'

import { ApiError, answerTask, getTask } from '../src/api'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('retries a transient 502 before surfacing the task', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: false, status: 502, json: vi.fn() })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ id: 'task-1', state: 'searching', next_card: null, card: null }),
    })
  vi.stubGlobal('fetch', fetchMock)

  await expect(getTask('task-1')).resolves.toMatchObject({ id: 'task-1' })
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

it('does not retry a 409 answer conflict', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 409, json: vi.fn() })
  vi.stubGlobal('fetch', fetchMock)

  await expect(getTask('task-1')).rejects.toBeInstanceOf(ApiError)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('recovers an answer that was applied despite a 5xx response', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/answers/mode')) {
      return { ok: false, status: 502, json: vi.fn() }
    }
    return {
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        id: 'task-1', state: 'collecting_terms', next_card: 'terms', card: null,
      }),
    }
  })
  vi.stubGlobal('fetch', fetchMock)

  await expect(answerTask('task-1', 'mode', { mode: 'A' })).resolves.toMatchObject({
    next_card: 'terms',
  })
})
