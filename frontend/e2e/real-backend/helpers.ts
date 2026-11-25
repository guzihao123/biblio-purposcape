import { expect } from '@playwright/test'
import type { Frame, Page, TestInfo } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

export const ROOT = path.resolve(process.cwd(), '..')
export const RUN = path.join(ROOT, 'dev', 'real_backend', 'runtime')
export const SHOTS = path.join(process.cwd(), 'e2e', 'real-backend-screenshots')
export const DIRECTION = '肝细胞癌免疫治疗耐药机制'

export async function capture(page: Page, testInfo: TestInfo, name: string) {
  await mkdir(SHOTS, { recursive: true })
  const filename = `${testInfo.title.split(' ')[0]}-${name}.png`
  await page.screenshot({ path: path.join(SHOTS, filename), fullPage: true, animations: 'disabled' })
}

export async function auditLayout(page: Page, testInfo: TestInfo, label: string) {
  const reports = []
  for (const frame of page.frames()) {
    try {
      reports.push(await frame.evaluate(() => {
        const root = document.documentElement
        const offenders: { tag: string; text: string; left: number; right: number; viewport: number }[] = []
        for (const element of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
          if (element.closest('[aria-hidden="true"]') || ['SCRIPT', 'STYLE'].includes(element.tagName)) continue
          // SVG descendants report viewBox coordinates; audit the rendered root SVG instead.
          if (element.closest('svg') && element.tagName.toLowerCase() !== 'svg') continue
          const style = getComputedStyle(element)
          if (style.display === 'none' || style.visibility === 'hidden') continue
          const rect = element.getBoundingClientRect()
          if (rect.width < 1 || rect.height < 1) continue
          if (rect.left < -1 || rect.right > window.innerWidth + 1) {
            offenders.push({ tag: element.tagName, text: (element.innerText || element.getAttribute('title') || '').trim().slice(0, 100), left: Math.round(rect.left), right: Math.round(rect.right), viewport: window.innerWidth })
            if (offenders.length >= 25) break
          }
        }
        return { url: location.pathname, scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, offenders }
      }))
    } catch (error) {
      reports.push({ url: frame.url(), detached: String(error) })
    }
  }
  await writeFile(path.join(RUN, `${testInfo.title.split(' ')[0]}-${label}-layout.json`), JSON.stringify(reports, null, 2))
  for (const report of reports) {
    if ('detached' in report) throw new Error(`Frame unavailable during layout audit: ${report.detached}`)
    expect(report.scrollWidth, `${label} 横向文档溢出 ${report.url}`).toBeLessThanOrEqual(report.clientWidth + 1)
    expect(report.offenders, `${label} 可见元素越界 ${report.url}`).toEqual([])
  }
}

export async function confirm(page: Page) {
  await page.getByRole('button', { name: '确认选择' }).click()
}

export async function enterAnonymous(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '进入你的研究空间' })).toBeVisible()
  await page.getByRole('button', { name: '开始研究' }).click()
  await expect(page.getByRole('heading', { name: '研究方向或核心问题' })).toBeVisible()
  return page.url().match(/\/tasks\/([^/]+)/)?.[1] ?? ''
}

export async function fillDirection(page: Page) {
  await page.getByRole('textbox', { name: '研究方向或核心问题' }).fill(DIRECTION)
  await confirm(page)
  await expect(page.getByRole('heading', { name: '这次洞察用来做什么？' })).toBeVisible()
}

export async function chooseMode(page: Page, mode: 'A' | 'B' | 'C' | 'D', testInfo?: TestInfo) {
  const names = {
    A: 'A 选题立项前摸底', B: 'B 撰写标书/立项依据',
    C: 'C 撰写论文引言与讨论', D: 'D 组会或团队学习',
  }
  await page.getByRole('button', { name: names[mode], exact: true }).click()
  if (mode === 'B') {
    await expect(page.getByRole('button', { name: '确认选择' })).toBeDisabled()
    const values = {
      '项目名称': '肝细胞癌免疫治疗耐药的多机制对解与联合验证',
      '一句话目标': '连接髓系代谢、IL-8/CXCR2 与乳酸化调控证据并形成分层验证方案',
      '研究内容（3–4 项）': '研究内容（一）髓系代谢机制解析\n研究内容（二）IL-8/CXCR2 动态验证\n研究内容（三）乳酸化机制与联合干预评价',
      '技术路线（输入→方法→验证→输出）': '证据对解→分层观察→机制验证→联合评价',
      '可行性（数据/工具/团队/预实验）': '只确认文献方法线索；团队、预实验与数据权限未提供。',
      '预期成果': '机制对解框架、分层验证流程与联合评价方案。',
    }
    for (const [label, value] of Object.entries(values)) await page.getByLabel(label, { exact: true }).fill(value)
    if (testInfo) {
      await page.setViewportSize({ width: 390, height: 760 })
      await auditLayout(page, testInfo, '390-b-project')
      await capture(page, testInfo, '390-b-project')
      await page.setViewportSize({ width: 1280, height: 800 })
    }
  }
  if (mode === 'C') {
    if (testInfo) {
      await page.setViewportSize({ width: 390, height: 760 })
      await auditLayout(page, testInfo, '390-c-mode')
      await capture(page, testInfo, '390-c-mode')
    }
    await confirm(page)
    await expect(page.getByRole('heading', { name: '本次最需要完成哪一项？' })).toBeVisible()
    await expect(page.getByRole('button', { name: '确认选择' })).toBeDisabled()
    if (testInfo) {
      await auditLayout(page, testInfo, '390-c-route')
      await capture(page, testInfo, '390-c-route')
    }
    await page.getByRole('button', { name: '从零写引言和文献综述（两个都选）', exact: true }).click()
    await confirm(page)
    await expect(page.getByLabel('本文信息')).toBeVisible()
    await page.getByLabel('本文信息').fill('比较三条耐药机制，采用分层机制验证，预期形成可追溯研究框架。')
    await page.getByLabel('目标期刊（可跳过）').fill('Hepatology')
    if (testInfo) {
      await auditLayout(page, testInfo, '390-c-info')
      await capture(page, testInfo, '390-c-info')
    }
  }
  if (mode === 'D') {
    const team = page.getByLabel('团队目前的研究方向/在研问题（可跳过）')
    await expect(team).toBeVisible()
    await team.fill('肿瘤免疫与代谢交叉团队，正在建立耐药机制的共同评价框架。')
    if (testInfo) {
      await page.setViewportSize({ width: 390, height: 760 })
      await auditLayout(page, testInfo, '390-d-team')
      await capture(page, testInfo, '390-d-team')
    }
  }
  await confirm(page)
  await expect(page.getByRole('heading', { name: /候选学术术语/ })).toBeVisible()
  if (testInfo && (mode === 'C' || mode === 'D')) await auditLayout(page, testInfo, `390-${mode.toLowerCase()}-terms`)
}

export async function finishCollection(page: Page) {
  await page.getByRole('button', { name: /肝细胞癌免疫治疗耐药（命中 4/ }).click()
  await confirm(page)
  await expect(page.getByRole('heading', { name: '重点关注的时间范围' })).toBeVisible()
  await page.getByRole('button', { name: /^C 近10年/ }).click()
}

export async function submitYearsAndWaitDashboard(page: Page, taskId: string) {
  const submitted = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/tasks/${taskId}/answers/years` && response.status() === 200)
  const polling = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === `/api/tasks/${taskId}` && response.status() === 200)
  await confirm(page)
  const submissionResponse = await submitted
  const submission = await submissionResponse.json()
  expect(submission.state).toBe('searching')
  expect(submission.progress.stage).toBe('search')
  await writeFile(path.join(RUN, `${taskId}-search-submission.json`), JSON.stringify(submission, null, 2))
  await expect(page.getByRole('heading', { name: submission.progress.message, exact: true })).toBeVisible()
  await expect(page.locator('p[role="status"]')).toContainText('当前阶段：search')
  const response = await polling
  const payload = await response.json()
  expect(['searching', 'dashboard_ready']).toContain(payload.state)
  await writeFile(path.join(RUN, `${taskId}-first-poll.json`), JSON.stringify(payload, null, 2))
  await expect(page.getByRole('heading', { name: '文献图谱与检索后调整' })).toBeVisible({ timeout: 90000 })
}

export async function continueAndDeliver(page: Page, taskId: string, form: 'A' | 'B' | 'C') {
  await page.getByRole('button', { name: '按原计划继续（进入交付形式选择）', exact: true }).click()
  await confirm(page)
  await expect(page.getByRole('heading', { name: '希望得到的交付形式' })).toBeVisible()
  const names = { A: 'A 正式调研报告（Word，含文献依据）', B: 'B 仅对话中给要点和代表文献', C: 'C 展示 PPT' }
  await page.getByRole('button', { name: names[form], exact: true }).click()
  await confirm(page)
  await expect(page.getByRole('heading', { name: '调研交付' })).toBeVisible({ timeout: 120000 })
  const response = await page.request.get(`/api/tasks/${taskId}`)
  expect(response.status()).toBe(200)
  const task = await response.json()
  await writeFile(path.join(RUN, `${taskId}-final-task.json`), JSON.stringify(task, null, 2))
  expect(task.state).toBe('done')
  expect(task.progress.checkpoint.stage).toBe('generate')
  return task
}

export async function verifyReport(page: Page) {
  for (const heading of ['提纲', '样章', '正文', '复核与覆盖边界']) await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  const sections = page.locator('.report-section')
  await expect(sections.nth(0).locator('pre')).not.toBeEmpty()
  await expect(sections.nth(1).locator('pre')).not.toBeEmpty()
  await expect(sections.nth(2)).toContainText('## 参考文献')
  await expect(sections.nth(2)).toContainText('[1]')
  await expect(sections.nth(3)).not.toContainText('[FAIL]')
}

export async function downloadArtifact(page: Page, taskId: string, label: string, filename: string, keyboard = false) {
  const link = page.getByRole('link', { name: label, exact: true })
  await expect(link).toBeVisible()
  const href = await link.getAttribute('href')
  expect(href).toContain(`/api/tasks/${taskId}/artifacts/`)
  expect(href).toContain('signature=')
  const direct = await page.request.get(href!)
  expect(direct.status()).toBe(200)
  expect(direct.headers()['content-disposition'] || '').toContain('attachment')
  expect((await direct.body()).length).toBeGreaterThan(100)
  const pending = page.waitForEvent('download')
  if (keyboard) {
    await link.focus()
    await page.keyboard.press('Enter')
  } else {
    await link.click()
  }
  const download = await pending
  expect(download.suggestedFilename()).toBe(filename)
  expect(await download.failure()).toBeNull()
  const directory = path.join(RUN, 'downloads', taskId)
  await mkdir(directory, { recursive: true })
  const destination = path.join(directory, filename)
  await download.saveAs(destination)
  return destination
}

export async function desktopFrame(page: Page): Promise<Frame> {
  const iframe = await page.locator('iframe[title="满血版文献图谱"]').elementHandle()
  const frame = await iframe?.contentFrame()
  if (!frame) throw new Error('Desktop graph frame was not created')
  await frame.locator('#pageTitle').waitFor()
  return frame
}

export async function clickTreeNode(frame: Frame, chartId: string, name: string) {
  await frame.locator(`#${chartId}`).click({ trial: true })
  await frame.waitForFunction(id => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(id))
    return chart && chart.getZr().animation.isFinished()
  }, chartId)
  const point = await frame.evaluate(({ chartId, name }) => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(chartId))
    const symbol = chart.getZr().storage.getDisplayList().find((item: any) =>
      item._textContent?.style?.text?.startsWith(name),
    )
    if (!symbol) throw new Error(`No rendered tree node: ${chartId}/${name}`)
    const transform = symbol.getComputedTransform()
    return [transform[4], transform[5]]
  }, { chartId, name })
  await frame.locator(`#${chartId} canvas`).first().click({ position: { x: point[0], y: point[1] } })
}

export async function clickSankeyNode(frame: Frame, chartId: string, name: string) {
  await frame.locator(`#${chartId}`).click({ trial: true })
  await frame.waitForFunction(id => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(id))
    return chart && chart.getZr().animation.isFinished()
  }, chartId)
  const point = await frame.evaluate(({ chartId, name }) => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(chartId))
    const data = chart.getModel().getSeriesByIndex(0).getData()
    const index = Array.from({ length: data.count() }, (_, i) => i).find(i => data.getName(i) === name)
    if (index == null) throw new Error(`No Sankey data node: ${chartId}/${name}`)
    const nodes = chart.getZr().storage.getDisplayList().filter((item: any) =>
      item.type === 'rect' && item.shape?.r === 0 && item.parent?.type !== 'text',
    )
    const node = nodes[index]
    if (!node) throw new Error(`No rendered Sankey node: ${chartId}/${name}`)
    const x = node.shape.x + node.shape.width / 2
    const y = node.shape.y + node.shape.height / 2
    const t = node.getComputedTransform()
    return [t[0] * x + t[2] * y + t[4], t[1] * x + t[3] * y + t[5]]
  }, { chartId, name })
  await frame.locator(`#${chartId} canvas`).first().click({ position: { x: point[0], y: point[1] } })
}

export async function clickChart(frame: Frame, chartId: string, index = 0, edge = false) {
  await frame.locator(`#${chartId}`).click({ trial: true })
  await frame.waitForFunction(id => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(id))
    return chart && chart.getZr().animation.isFinished()
  }, chartId)
  const point = await frame.evaluate(({ chartId, index, edge }) => {
    const engine = (window as unknown as { echarts: any }).echarts
    const chart = engine.getInstanceByDom(document.getElementById(chartId))
    if (!chart) throw new Error(`No ECharts instance: ${chartId}`)
    const series = chart.getModel().getSeriesByIndex(0)
    let layout
    if (edge) {
      const graph = series.getGraph()
      layout = graph.getEdgeByIndex(index).getLayout()
      if (Array.isArray(layout?.[0])) {
        const a = layout[0], b = layout[layout.length - 1]
        layout = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
      }
    } else {
      layout = series.getData().getItemLayout(index)
    }
    if (layout && !Array.isArray(layout)) layout = [layout.x + (layout.dx || 0) / 2, layout.y + (layout.dy || 0) / 2]
    if (!layout) throw new Error(`No chart layout: ${chartId}/${index}`)
    return chart.convertToPixel({ seriesIndex: 0 }, layout) || layout
  }, { chartId, index, edge })
  await frame.locator(`#${chartId} canvas`).first().click({ position: { x: point[0], y: point[1] } })
}
