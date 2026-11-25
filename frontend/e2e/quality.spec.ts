import { expect, test } from '@playwright/test'

import { startResearch } from './acceptance-helpers'

test('性能模式在自动、流畅优先、画质优先之间循环', async ({ page }) => {
  await startResearch(page)

  const toggle = page.getByRole('button', { name: '性能模式', exact: true })
  await expect(toggle).toContainText('性能：自动')

  await toggle.click()
  await expect(toggle).toContainText('性能：流畅')
  await expect(page.locator('.scene-backdrop')).toHaveAttribute('data-quality', 'lite')

  await toggle.click()
  await expect(toggle).toContainText('性能：画质')
  await expect(page.locator('.scene-backdrop')).toHaveAttribute('data-quality', 'full')

  await toggle.click()
  await expect(toggle).toContainText('性能：自动')
})