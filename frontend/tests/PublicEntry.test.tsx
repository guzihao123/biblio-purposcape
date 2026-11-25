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

describe('Public entry', () => {
  it('starts research without an invitation code', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(responseWith(201, { session_id: 'public-session' }))
    const onSuccess = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<InvitePage apiBaseUrl="https://api.example.test/" onSuccess={onSuccess} />)
    expect(screen.queryByLabelText('邀请码')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('public-session'))
    expect(fetchMock).toHaveBeenCalledWith('https://api.example.test/api/session', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
  })

  it('shows a safe service error without backend details', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responseWith(503, { detail: 'secret upstream error' })))

    render(<InvitePage onSuccess={onSuccess} />)
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('研究服务暂时不可用，请稍后重试。')
    expect(screen.queryByText(/secret upstream error/)).not.toBeInTheDocument()
    expect(onSuccess).not.toHaveBeenCalled()
  })
})
