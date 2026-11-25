import { expect } from '@playwright/test'
import type { Frame, Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

export const SCREENSHOT_DIR = path.resolve(process.cwd(), 'test-results', 'screenshots')
export const DOWNLOAD_DIR = path.resolve(process.cwd(), 'test-results', 'downloads')
export const ADMIN_TOKEN = 'browser-acceptance-admin-token'

export async function screenshot(page: Page, name: string, fullPage = true) {
  mkdirSync(SCREENSHOT_DIR, { recursive: true })
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}.png`), fullPage })
}

export async function startResearch(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '开始研究', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '开始研究', exact: true }).click()
  await expect(page.getByRole('heading', { name: '研究方向或核心问题', exact: true })).toBeVisible()
}

export async function answerDirection(page: Page) {
  await page.getByRole('button', { name: '肝癌免疫治疗耐药机制的最新进展', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '这次洞察用来做什么？', exact: true })).toBeVisible()
}

export async function answerModeA(page: Page) {
  await page.getByRole('button', { name: 'A 选题立项前摸底', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
}

export async function answerTermsAndYears(page: Page) {
  await page.getByRole('button', { name: '肝细胞癌（命中 1280）', exact: true }).click()
  await page.getByRole('button', { name: '免疫治疗耐药（命中 436）', exact: true }).click()
  await expect(page.getByRole('button', { name: '肝细胞癌（命中 1280）', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: '免疫治疗耐药（命中 436）', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '重点关注的时间范围', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'B 近5年', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.locator('.app-message[role="status"]')).toContainText('当前阶段：search')
}

export async function reachDashboard(page: Page) {
  await startResearch(page)
  await answerDirection(page)
  await answerModeA(page)
  await answerTermsAndYears(page)
  await expect(page.getByRole('heading', { name: '文献图谱与检索后调整', exact: true })).toBeVisible({ timeout: 60000 })
}

export async function reachReport(page: Page) {
  await reachDashboard(page)
  await page.getByRole('button', { name: '调整学术术语', exact: true }).click()
  await page.getByRole('button', { name: '按原计划继续（进入交付形式选择）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '希望得到的交付形式', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'A 正式调研报告（Word，含文献依据）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.locator('.app-message[role="status"]')).toContainText('当前阶段：generate')
  await expect(page.getByRole('heading', { name: '调研交付', exact: true })).toBeVisible({ timeout: 60000 })
}

export async function getGraphFrame(page: Page, version: 'desktop' | 'mobile' = 'desktop') {
  const title = version === 'desktop' ? '满血版文献图谱' : '轻量版文献图谱'
  const iframe = page.getByTitle(title)
  await expect(iframe).toBeVisible()
  const element = await iframe.elementHandle()
  const frame = await element?.contentFrame()
  if (!frame) throw new Error(`无法读取 ${title}`)
  if (version === 'desktop') {
    await frame.waitForSelector('#network canvas', { timeout: 30000 })
    await frame.waitForFunction(() => document.querySelectorAll('#relations canvas').length > 0)
  } else {
    await frame.waitForSelector('text=研究方法', { timeout: 30000 })
  }
  return frame
}

export async function expectNoHorizontalOverflow(page: Page, label: string) {
  const result = await page.evaluate(() => {
    const viewport = window.innerWidth
    const offenders = [...document.querySelectorAll<HTMLElement>('body *')]
      .filter((element) => {
        if (element.closest('[aria-hidden="true"]')) return false
        const style = getComputedStyle(element)
        if (style.display === 'none' || style.visibility === 'hidden') return false
        const rect = element.getBoundingClientRect()
        return rect.width > 0 && (rect.left < -1 || rect.right > viewport + 1)
      })
      .slice(0, 12)
      .map((element) => ({
        tag: element.tagName,
        className: String(element.className).slice(0, 100),
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
        text: (element.textContent ?? '').trim().slice(0, 80),
      }))
    return { viewport, documentWidth: document.documentElement.scrollWidth, offenders }
  })
  expect(result.documentWidth, `${label}: 页面横向宽度`).toBeLessThanOrEqual(result.viewport + 1)
  expect(result.offenders, `${label}: 超出视口的元素`).toEqual([])
}

export async function expectGraphNoHorizontalOverflow(frame: Frame, label: string) {
  const result = await frame.evaluate(async () => {
    await Promise.all([...document.querySelectorAll<HTMLElement>('.panel')].flatMap((panel) =>
      panel.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => undefined)),
    ))
    const viewport = window.innerWidth
    const panels = [...document.querySelectorAll<HTMLElement>('.panel')].map((panel) => ({
      id: panel.id,
      clientWidth: panel.clientWidth,
      scrollWidth: panel.scrollWidth,
      overflowingRows: [...panel.querySelectorAll<HTMLElement>('li, blockquote, a, h3')]
        .filter((row) => {
          const panelRect = panel.getBoundingClientRect()
          const rect = row.getBoundingClientRect()
          return rect.left < panelRect.left - 1 || rect.right > panelRect.right + 1
        })
        .slice(0, 6)
        .map((row) => (row.textContent ?? '').trim().slice(0, 120)),
    }))
    return { viewport, documentWidth: document.documentElement.scrollWidth, panels }
  })
  expect.soft(result.documentWidth, `${label}: 图谱文档横向宽度`).toBeLessThanOrEqual(result.viewport + 1)
  for (const panel of result.panels) {
    expect.soft(panel.scrollWidth, `${label}: ${panel.id} 横向溢出`).toBeLessThanOrEqual(panel.clientWidth + 1)
    expect.soft(panel.overflowingRows, `${label}: ${panel.id} 证据行越界`).toEqual([])
  }
  return result
}

type GraphNodeKind = 'network' | 'factor' | 'method' | 'relation'

export async function clickGraphNode(frame: Frame, chartId: string, kind: GraphNodeKind) {
  const locator = frame.locator(`#${chartId}`)
  // 因素、方法树和语义图进入视口会重放动画；先完成滚动并重放，再读取真实坐标。
  if (kind !== 'network') {
    await locator.click({ trial: true })
    await frame.waitForTimeout(850)
  }
  const point = await locator.evaluate((element, input) => {
    const chart = eval('charts')[input.chartId]
    if (!chart) throw new Error(`图表未初始化: ${input.chartId}`)
    if (input.kind === 'method') {
      const symbols = chart.getZr().storage.getDisplayList()
        .filter((target: any) => target?.shape?.symbolType)
        .map((target: any) => {
          const center = target.transformCoordToGlobal(0, 0)
          const hit = chart.getZr().handler.findHover(center[0], center[1])?.target
          return { center, x: target.x, y: target.y, parentX: target.parent?.x, parentY: target.parent?.y, hitType: hit?.type, hitShape: hit?.shape }
        })
      const candidate = symbols.find((item: any) => item.center[0] > 100 && item.center[0] < element.clientWidth - 5 && item.center[1] > 0 && item.center[1] < element.clientHeight - 5 && item.hitShape?.symbolType)
      if (!candidate) throw new Error(`未找到可命中方法结点: ${JSON.stringify({ width: element.clientWidth, height: element.clientHeight, symbols: symbols.slice(0, 12) })}`)
      return { x: candidate.center[0], y: candidate.center[1], label: '可见方法结点', index: null }
    }
    const series = chart.getModel().getSeriesByIndex(0)
    const data = series.getData()
    let index = 0
    if (input.kind === 'factor') {
      const candidates = Array.from({ length: data.count() }, (_, i) => i).filter((i) => {
        const raw = data.getRawDataItem(i)
        return raw && raw.type !== 'outcome' && (raw.papers || []).length > 0
      })
      index = candidates.sort((a, b) => data.getItemLayout(b).dy - data.getItemLayout(a).dy)[0] ?? 0
    } else if (input.kind === 'relation') {
      const relation = eval('DATA').scopes.all.relations.edges[0]
      index = Array.from({ length: data.count() }, (_, i) => i).find((i) => {
        const raw = data.getRawDataItem(i)
        return raw && (raw.id === relation.s || raw.id === relation.t)
      }) ?? 0
    }
    const raw = data.getRawDataItem(index)
    const layout = data.getItemLayout(index)
    const type = series.get('type')
    let pixel
    if (type === 'sankey') {
      pixel = [
        layout.x + layout.dx / 2 + (Number(series.get('left')) || 0),
        layout.y + layout.dy / 2 + (Number(series.get('top')) || 0),
      ]
    } else {
      const value = raw && raw.x != null
        ? [raw.x, raw.y]
        : Array.isArray(layout)
          ? layout
          : [layout.x, layout.y]
      pixel = chart.convertToPixel({ seriesIndex: 0 }, value)
    }
    return { x: pixel[0], y: pixel[1], label: raw?.name || raw?.label || raw?.title || '', index }
  }, { chartId, kind })
  await locator.click({ position: { x: point.x, y: point.y } })
  return point
}

export async function clickSemanticEdge(frame: Frame) {
  const locator = frame.locator('#relations')
  await locator.click({ trial: true })
  await frame.waitForTimeout(850)
  const point = await locator.evaluate(() => {
    const chart = eval('charts').relations
    const option = chart.getOption()
    const data = option.series[0].data
    const edge = option.series[0].links[0]
    const source = data.find((item: any) => item.id === edge.source)
    const target = data.find((item: any) => item.id === edge.target)
    const a = chart.convertToPixel({ seriesIndex: 0 }, [source.x, source.y])
    const b = chart.convertToPixel({ seriesIndex: 0 }, [target.x, target.y])
    return { x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2 }
  })
  await locator.click({ position: point })
}
