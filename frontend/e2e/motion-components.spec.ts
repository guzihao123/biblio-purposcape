import { expect, test } from '@playwright/test'

test('tabs, steps, panel, download and click ripple are real and selectable', async ({ page }) => {
  await page.goto('/motion-lab.html')
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'pageEnter')

  const selectedButton = page.locator('.motion-button--selected')
  const rippleStarted = page.evaluate(() => new Promise<boolean>((resolve) => {
    const ripple = document.querySelector('.motion-button--selected .motion-button__ripple')!
    const timer = window.setTimeout(() => resolve(false), 2000)
    ripple.addEventListener('animationstart', (event) => {
      if ((event as AnimationEvent).animationName !== 'ripple') return
      window.clearTimeout(timer)
      resolve(true)
    })
  }))
  const bounds = await selectedButton.boundingBox()
  await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2)
  await page.mouse.down()
  expect(await rippleStarted).toBe(true)
  await page.mouse.up()

  const indicator = page.locator('.motion-tab-indicator')
  await page.getByRole('tab', { name: '近三年' }).click()
  await expect.poll(() => indicator.evaluate((element) => parseFloat(getComputedStyle(element).left))).toBeGreaterThan(0)
  await expect(page.locator('.motion-tabs')).toHaveCSS('transform', 'none')

  await page.getByRole('button', { name: '下一阶段' }).click()
  await expect(page.locator('output')).toHaveText('当前：真实检索')

  await page.getByRole('button', { name: '打开证据面板' }).click()
  await expect(page.locator('.motion-panel')).toBeVisible()
  await expect(page.locator('.motion-panel')).toHaveCSS('animation-name', 'panelSweep')
  await expect(page.locator('.motion-panel__line').first()).toHaveCSS('animation-name', 'lineFade')

  await page.getByRole('button', { name: '生成报告' }).click()
  await expect(page.locator('.download-feedback__status')).toContainText('报告已就绪，可下载')
  await expect(page.locator('.download-feedback')).toHaveClass(/is-complete/)
})

test('narrow screens remove decorative transforms but keep functional indicator position', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 760 })
  await page.goto('/motion-lab.html')
  await expect(page.locator('.motion-button__ripple')).toHaveCSS('display', 'none')
  await expect(page.locator('.full-power-option.is-selected')).toHaveCSS('animation-name', 'selectedGlowReduced')
  await expect(page.locator('.full-power-option.is-selected')).toHaveCSS('transform', 'none')

  await page.getByRole('tab', { name: '近三年' }).click()
  await expect.poll(() => page.locator('.motion-tab-indicator').evaluate((element) => parseFloat(getComputedStyle(element).left))).toBeGreaterThan(0)
  await expect(page.locator('.motion-tabs')).toHaveCSS('transform', 'none')

  await page.getByRole('button', { name: '打开证据面板' }).click()
  await expect(page.locator('.motion-panel')).toBeVisible()
  expect(await page.locator('.motion-panel').evaluate((element) => getComputedStyle(element, '::before').display)).toBe('none')
  await expect(page.locator('.motion-panel')).toHaveCSS('position', 'relative')
  await page.getByRole('button', { name: '生成报告' }).click()
  await expect(page.locator('.download-feedback__status')).toContainText('报告已就绪，可下载')
})

test('reduced-motion removes animation and sweep without blocking keyboard flow', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/motion-lab.html')
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'none')
  await expect(page.locator('.motion-button__ripple')).toHaveCSS('display', 'none')
  await expect(page.locator('.full-power-option.is-selected')).toHaveCSS('animation-name', 'none')

  await page.getByRole('button', { name: '打开证据面板' }).click()
  await expect(page.locator('.motion-panel')).toBeVisible()
  expect(await page.locator('.motion-panel').evaluate((element) => getComputedStyle(element, '::before').display)).toBe('none')
  await expect(page.locator('.motion-panel')).toHaveCSS('position', 'relative')
  await expect(page.locator('.motion-panel')).toHaveCSS('animation-name', 'none')
  await page.getByRole('button', { name: '生成报告' }).click()
  await expect(page.locator('.download-feedback__status')).toContainText('报告已就绪，可下载')
})

test('primary action remains reachable and keyboard operable', async ({ page }) => {
  await page.goto('/')
  const startButton = page.getByRole('button', { name: '开始研究' })
  await startButton.focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('heading', { name: '研究方向或核心问题' })).toBeVisible()

  const direction = page.getByRole('button', { name: '肝癌免疫治疗耐药机制的最新进展' })
  await direction.focus()
  await page.keyboard.press('Space')
  await expect(direction).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '确认选择' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '这次洞察用来做什么？' })).toBeVisible()

  const optionA = page.getByRole('button', { name: 'A 选题立项前摸底' })
  await optionA.focus()
  await page.keyboard.press('Space')
  await expect(optionA).toHaveAttribute('aria-pressed', 'true')

  const confirm = page.getByRole('button', { name: '确认选择' })
  await confirm.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。' })).toBeVisible()
})
