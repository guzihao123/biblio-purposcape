import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { InvitePage } from '../src/pages/InvitePage'

function responseWith(status: number, payload: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response
}

describe('InvitePage', () => {
  it('posts the invite code to the configured backend and establishes a session', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(responseWith(201, { session_id: 'session-123' }))
    const onSuccess = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<InvitePage apiBaseUrl="https://api.example.test/" onSuccess={onSuccess} />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('session-123'))
    expect(fetchMock).toHaveBeenCalledWith('https://api.example.test/api/session', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    expect(screen.getByRole('status')).toHaveTextContent('会话已建立')
  })

  it('shows a safe service error without exposing backend details', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responseWith(503, { detail: 'upstream secret error' })),
    )

    render(<InvitePage onSuccess={onSuccess} />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('研究服务暂时不可用，请稍后重试。')
    expect(screen.queryByText(/upstream secret error/)).not.toBeInTheDocument()
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('keeps network failures readable and allows a retry', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<InvitePage />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '无法连接研究服务，请检查网络后重试。',
    )
    expect(screen.getByRole('button', { name: '开始研究' })).toBeEnabled()
  })

  it('starts without an invitation input or secret value', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(responseWith(201, { session_id: 'public-id' }))
    vi.stubGlobal('fetch', fetchMock)

    render(<InvitePage />)
    expect(screen.queryByLabelText('邀请码')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/session', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }))
  })

  it('treats a malformed success payload as a service error', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responseWith(201, { unexpected: true })))

    render(<InvitePage onSuccess={onSuccess} />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '研究服务返回异常，请稍后重试。',
    )
    expect(onSuccess).not.toHaveBeenCalled()
  })
})
