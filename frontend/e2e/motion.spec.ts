import { expect, test } from '@playwright/test'

test('page entry, buttons and selected cards expose full-power motion', async ({ page }) => {
  await page.goto('/')
  const entry = page.locator('[data-motion="page-enter"]')
  await expect(entry).toHaveCSS('animation-name', 'pageEnter')

  const startButton = page.getByRole('button', { name: '开始研究' })
  await expect(startButton).toHaveClass(/motion-button/)
  await startButton.hover()
  const transform = await startButton.evaluate((element) => getComputedStyle(element).transform)
  expect(transform).not.toBe('none')

  await startButton.click()
  await page.getByRole('textbox', { name: '研究方向或核心问题' }).fill('肝癌免疫治疗耐药机制的最新进展')
  await page.getByRole('button', { name: '确认选择' }).click()
  const optionA = page.getByRole('button', { name: 'A 选题立项前摸底' })
  await optionA.click()
  await expect(optionA).toHaveClass(/is-selected/)
  await expect(optionA).toHaveCSS('animation-name', 'selectedGlow')
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'pageEnter')
})

test('reduced-motion removes decorative animation without blocking the primary flow', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'none')

  const startButton = page.getByRole('button', { name: '开始研究' })
  await expect(startButton).toHaveCSS('animation-name', 'none')
  await startButton.click()
  await page.getByRole('textbox', { name: '研究方向或核心问题' }).fill('肝癌免疫治疗耐药机制的最新进展')
  await page.getByRole('button', { name: '确认选择' }).click()
  const optionA = page.getByRole('button', { name: 'A 选题立项前摸底' })
  await optionA.click()
  await expect(optionA).toHaveAttribute('aria-pressed', 'true')
  await expect(optionA).toHaveCSS('animation-name', 'none')
})
