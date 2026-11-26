import { act, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { CONNECTION_EVENT } from '../src/api'
import { ConnectionBanner } from '../src/components/ConnectionBanner'

it('shows retry progress and clears when the service answers', () => {
  render(<ConnectionBanner />)
  act(() => {
    window.dispatchEvent(new CustomEvent(CONNECTION_EVENT, {
      detail: { phase: 'retrying', attempt: 2, delayMs: 1000 },
    }))
  })
  expect(screen.getByRole('status')).toHaveTextContent('第 2 次')
  expect(screen.getByRole('status')).toHaveTextContent('1 秒后')

  act(() => {
    window.dispatchEvent(new CustomEvent(CONNECTION_EVENT, { detail: { phase: 'online' } }))
  })
  expect(screen.queryByRole('status')).toBeNull()
})
