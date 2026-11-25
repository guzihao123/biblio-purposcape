import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { MotionTabs } from '../src/components/MotionTabs'

const tabs = [
  { value: 'desktop', label: '满血版' },
  { value: 'mobile', label: '轻量版' },
]

function ControlledTabs() {
  const [value, setValue] = useState('desktop')
  return (
    <>
      <MotionTabs tabs={tabs} value={value} onChange={setValue} />
      <output aria-label="当前图谱">{value}</output>
    </>
  )
}

describe('MotionTabs keyboard interaction', () => {
  it('uses roving tabindex and synchronizes focus, selection and controlled value', async () => {
    const user = userEvent.setup()
    render(<ControlledTabs />)
    const full = screen.getByRole('tab', { name: '满血版' })
    const light = screen.getByRole('tab', { name: '轻量版' })

    expect(full).toHaveAttribute('tabindex', '0')
    expect(light).toHaveAttribute('tabindex', '-1')
    full.focus()
    await user.keyboard('{ArrowRight}')
    expect(light).toHaveFocus()
    expect(light).toHaveAttribute('aria-selected', 'true')
    expect(light).toHaveAttribute('tabindex', '0')
    expect(full).toHaveAttribute('aria-selected', 'false')
    expect(full).toHaveAttribute('tabindex', '-1')
    expect(screen.getByLabelText('当前图谱')).toHaveTextContent('mobile')

    await user.keyboard('{ArrowLeft}')
    expect(full).toHaveFocus()
    expect(full).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowLeft}')
    expect(light).toHaveFocus()
    expect(light).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowRight}')
    expect(full).toHaveFocus()
    expect(full).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{End}')
    expect(light).toHaveFocus()
    expect(light).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    expect(full).toHaveFocus()
    expect(full).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('当前图谱')).toHaveTextContent('desktop')
  })

  it('keeps only the externally selected tab in the keyboard tab order', () => {
    const { rerender } = render(<MotionTabs tabs={tabs} value="desktop" />)
    const full = screen.getByRole('tab', { name: '满血版' })
    const light = screen.getByRole('tab', { name: '轻量版' })
    expect(full).toHaveAttribute('tabindex', '0')
    expect(light).toHaveAttribute('tabindex', '-1')

    rerender(<MotionTabs tabs={tabs} value="mobile" />)
    expect(full).toHaveAttribute('tabindex', '-1')
    expect(full).toHaveAttribute('aria-selected', 'false')
    expect(light).toHaveAttribute('tabindex', '0')
    expect(light).toHaveAttribute('aria-selected', 'true')
  })
})
