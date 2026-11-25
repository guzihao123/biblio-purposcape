import { expect, test } from '@playwright/test'
import { mkdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import {
  ADMIN_TOKEN,
  DOWNLOAD_DIR,
  answerDirection,
  answerModeA,
  answerTermsAndYears,
  clickGraphNode,
  clickSemanticEdge,
  expectGraphNoHorizontalOverflow,
  expectNoHorizontalOverflow,
  getGraphFrame,
  reachDashboard,
  screenshot,
  startResearch,
} from './acceptance-helpers'

test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  ;(page as any).__acceptanceConsoleErrors = errors
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
})

test.afterEach(async ({ page }, testInfo) => {
  const errors = ((page as any).__acceptanceConsoleErrors ?? []) as string[]
  await testInfo.attach('browser-console-errors', {
    body: JSON.stringify(errors, null, 2),
    contentType: 'application/json',
  })
  expect(errors, '浏览器控制台与未捕获异常应为空').toEqual([])
})

test('01 Skill 管理页完成加载、草稿、回归、发布与回退', async ({ page }) => {
  await page.goto('/admin/skill')
  await page.getByRole('button', { name: '开始研究', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Skill 版本管理', exact: true })).toBeVisible()
  await page.getByLabel('管理员令牌', { exact: true }).fill(ADMIN_TOKEN)
  await page.getByRole('button', { name: '加载版本', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('版本已加载')
  await expect(page.locator('.version-item')).toHaveCount(1)
  await expect(page.locator('.app-message').filter({ hasText: '当前发布：' })).toBeVisible()

  await page.getByRole('button', { name: '创建草稿', exact: true }).click()
  await expect(page.getByRole('heading', { name: /^当前草稿：/ })).toBeVisible()
  await page.getByText('查看配置与差异来源', { exact: true }).click()
  await expect(page.locator('.admin-draft pre')).toContainText('parent_id')
  await expect(page.getByRole('button', { name: '发布草稿', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '运行回归', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('回归已通过，可以发布')
  await expect(page.getByRole('button', { name: '发布草稿', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '发布草稿', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已发布 ')
  await expect(page.locator('.version-item')).toHaveCount(2)

  await page.getByRole('button', { name: /^回退到 / }).click()
  await expect(page.getByRole('status')).toContainText('已回退到 ')
  await expect(page.locator('.version-item')).toHaveCount(2)
  await expectNoHorizontalOverflow(page, 'Skill 管理页')
  await screenshot(page, '01-skill-admin')
})

test('02 匿名 A 主流程、检索状态、继续否决、报告下载与历史', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('无需邀请码，点击即可开始本次文献探索。', { exact: true })).toBeVisible()
  await expectNoHorizontalOverflow(page, '匿名入口')
  await screenshot(page, '02-anonymous-entry')
  await page.getByRole('button', { name: '开始研究', exact: true }).click()
  await expect(page.getByRole('heading', { name: '研究方向或核心问题', exact: true })).toBeVisible()

  const qualityToggle = page.getByRole('button', { name: '性能模式', exact: true })
  await expect(qualityToggle).toContainText('性能：自动')
  await qualityToggle.click()
  await expect(qualityToggle).toContainText('性能：流畅')
  await expect(page.locator('.scene-backdrop')).toHaveAttribute('data-quality', 'lite')
  await qualityToggle.click()
  await expect(qualityToggle).toContainText('性能：画质')
  await expect(page.locator('.scene-backdrop')).toHaveAttribute('data-quality', 'full')
  await qualityToggle.click()
  await expect(qualityToggle).toContainText('性能：自动')

  await answerDirection(page)
  await expect(page.getByRole('button', { name: 'B 撰写标书/立项依据', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'C 撰写论文引言与讨论', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'D 组会或团队学习', exact: true })).toBeVisible()
  await screenshot(page, '02-purpose-card')
  await answerModeA(page)
  await answerTermsAndYears(page)
  await expect(page.getByText('双范围检索', { exact: true })).toBeVisible()
  await screenshot(page, '02-searching')

  await expect(page.getByRole('heading', { name: '文献图谱与检索后调整', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByRole('button', { name: '调整学术术语', exact: true }).click()
  await page.getByRole('button', { name: '按原计划继续（进入交付形式选择）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '希望得到的交付形式', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'A 正式调研报告（Word，含文献依据）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.locator('.app-message[role="status"]')).toContainText('当前阶段：generate')
  await expect(page.getByRole('heading', { name: '调研交付', exact: true })).toBeVisible({ timeout: 60000 })

  const sections = page.locator('.report-section')
  await expect(sections).toHaveCount(4)
  await expect(sections.nth(0)).toContainText('背景与演进')
  await expect(sections.nth(1)).toContainText('免疫微环境')
  await expect(sections.nth(2)).toContainText('## 参考文献')
  await expect(sections.nth(2)).toContainText('[1] ZHANG')
  await expect(sections.nth(3)).toContainText('[PASS]')
  await expect(sections.nth(3)).toContainText('覆盖边界')
  await expect(sections.nth(3)).toHaveClass(/is-verified/)
  await expectNoHorizontalOverflow(page, '报告页')
  await screenshot(page, '02-report')

  mkdirSync(DOWNLOAD_DIR, { recursive: true })
  const downloads = [
    ['下载 Word 报告', 'report.docx'],
    ['下载 PPT', 'slides.pptx'],
    ['下载对话要点', 'dialogue.json'],
    ['查看证据复核', 'verify_report.txt'],
    ['查看需求对账', 'conformance.md'],
  ] as const
  for (const [label, filename] of downloads) {
    const waiting = page.waitForEvent('download')
    await page.getByRole('link', { name: label, exact: true }).click()
    const download = await waiting
    const target = path.join(DOWNLOAD_DIR, filename)
    await download.saveAs(target)
    expect(statSync(target).size, `${filename} 应有实际内容`).toBeGreaterThan(40)
    if (filename.endsWith('.docx') || filename.endsWith('.pptx')) {
      expect(readFileSync(target).subarray(0, 2).toString()).toBe('PK')
    }
  }

  await page.getByRole('button', { name: '研究历史', exact: true }).click()
  await expect(page.getByRole('heading', { name: '研究历史', exact: true })).toBeVisible()
  const historyItem = page.locator('.history-item').first()
  await expect(historyItem).toContainText('肝癌免疫治疗耐药机制的最新进展')
  await expect(historyItem).toContainText('已完成')
  await screenshot(page, '02-history')
  await historyItem.click()
  await expect(page.getByRole('heading', { name: '调研交付', exact: true })).toBeVisible()
})

test('03 满血/轻量切换及结点、因素、方法、语义关系真实点击回溯', async ({ page }, testInfo) => {
  await reachDashboard(page)
  const responses: unknown[] = []
  for (const [tabName, title, version] of [
    ['满血版', '满血版文献图谱', 'desktop'],
    ['轻量版', '轻量版文献图谱', 'mobile'],
  ] as const) {
    await page.getByRole('tab', { name: tabName, exact: true }).click()
    await expect(page.getByRole('tab', { name: tabName, exact: true })).toHaveAttribute('aria-selected', 'true')
    const iframe = page.getByTitle(title)
    await expect(iframe).toBeVisible()
    const src = await iframe.getAttribute('src')
    expect(src, `${title} 应有真实制品 URL`).toBeTruthy()
    const response = await page.request.get(new URL(src!, page.url()).href)
    const headers = response.headers()
    responses.push({ title, url: response.url(), status: response.status(), headers })
    expect(response.status(), `${title} 制品应可获取`).toBe(200)
    expect(headers['content-disposition'] ?? '', `${title} 应允许 iframe 内嵌而不是下载`).toContain('inline')
    const embedded = await getGraphFrame(page, version)
    await expect(embedded.locator('body')).toContainText(version === 'desktop' ? '文章引用关系网络' : '研究方法')
    await screenshot(page, tabName === '满血版' ? '03-desktop-embedded' : '03-light-dashboard', false)
  }
  await testInfo.attach('graph-iframe-responses', {
    body: JSON.stringify(responses, null, 2),
    contentType: 'application/json',
  })

  // 所有交互均在宿主应用的真实 iframe 内执行，不以独立制品页面替代。
  await page.getByRole('tab', { name: '满血版', exact: true }).click()
  const full = await getGraphFrame(page, 'desktop')
  await expect(full.locator('h2').filter({ hasText: '文章引用关系网络' })).toBeVisible()
  await expect(full.locator('h2').filter({ hasText: '因素 → 结局' })).toBeVisible()
  await expect(full.locator('h2').filter({ hasText: '研究方法思维导图' })).toBeVisible()
  await expect(full.locator('h2').filter({ hasText: '语义关系图谱' })).toBeVisible()

  await clickGraphNode(full, 'network', 'network')
  await expect(full.locator('#netPanel')).toContainText('Sphingolipid')
  await expect(full.locator('#netPanel')).toContainText('被引')
  await expectGraphNoHorizontalOverflow(full, '网络结点证据')

  await clickGraphNode(full, 'knowledge', 'factor')
  await expect(full.locator('#kgPanel h3')).toContainText('因素：')
  await expect(full.locator('#kgPanel')).toContainText('关联论文')
  await expect(full.locator('#kgPanel li').first()).toBeVisible()
  await expectGraphNoHorizontalOverflow(full, '因素证据')

  await clickGraphNode(full, 'methods', 'method')
  await expect(full.locator('#mmPanel h3')).not.toHaveText('方法论文')
  await expect(full.locator('#mmPanel')).toContainText('使用该方法的论文')
  await expect(full.locator('#mmPanel li').first()).toBeVisible()
  await expectGraphNoHorizontalOverflow(full, '方法证据')

  await clickGraphNode(full, 'relations', 'relation')
  await expect(full.locator('#relPanel')).toContainText('关系（')
  await expect(full.locator('#relPanel li').first()).toBeVisible()
  await clickSemanticEdge(full)
  await expect(full.locator('#relPanel')).toContainText('摘要证据')
  await expect(full.locator('#relPanel blockquote')).toBeVisible()
  const graphOverflow = await expectGraphNoHorizontalOverflow(full, '语义关系证据')
  await testInfo.attach('graph-overflow-after-clicks', {
    body: JSON.stringify(graphOverflow, null, 2),
    contentType: 'application/json',
  })
  await screenshot(page, '03-semantic-evidence', false)
  await full.locator('#netPanel').screenshot({ path: 'test-results/screenshots/03-network-evidence-panel.png' })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '轻量版', exact: true }).click()
  const mobile = await getGraphFrame(page, 'mobile')
  await expect(mobile.locator('body')).toContainText('研究方法')
  await expect(mobile.locator('body')).toContainText('因素')
  await expectGraphNoHorizontalOverflow(mobile, '390px 轻量图谱')
  await screenshot(page, '03-mobile-embedded', false)
})

test('04 B 项目主题候选、名称/目标/资助与系统生成字段', async ({ page }) => {
  await startResearch(page)
  await answerDirection(page)
  await page.getByRole('button', { name: 'B 撰写标书/立项依据', exact: true }).click()
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '请选择一个项目主题候选', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '肝癌免疫治疗耐药的髓系代谢机制与分层验证', exact: true })).toBeVisible()
  await screenshot(page, '04-b-theme-candidates')
  await page.getByRole('button', { name: '肝癌免疫治疗耐药的髓系代谢机制与分层验证', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '确认项目名称、目标与资助类别', exact: true })).toBeVisible()
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('肝癌免疫治疗耐药的髓系代谢机制与分层验证')
  await expect(page.getByLabel('一句话目标', { exact: true })).toHaveValue('识别可干预的髓系代谢机制并形成分层验证方案。')
  await page.getByLabel('资助类别/学科属性（可跳过）', { exact: true }).fill('国家自然科学基金·医学部')
  await expect(page.getByLabel('研究内容（3–4 项）', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('技术路线（输入→方法→验证→输出）', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '确认选择', exact: true })).toBeEnabled()
  const waiting = page.waitForRequest((request) => request.url().includes('/answers/mode') && request.method() === 'POST')
  await screenshot(page, '04-project-fields')
  await expectNoHorizontalOverflow(page, 'B 项目字段')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  const request = await waiting
  const value = request.postDataJSON().value
  expect(value.mode).toBe('B')
  expect(value.project.name).toContain('髓系代谢')
  expect(value.project.goal).toContain('可干预')
  expect(value.project.funding).toContain('国家自然科学基金')
  expect(value.theme.object).toContain('患者队列')
  expect(value.theme.method).toContain('空间转录组')
  expect(value.theme.expected_output).toContain('验证方案')
  expect(value.project.research_contents).toBeUndefined()
  expect(value.project.technical_route).toBeUndefined()
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
})


test('04B E 其他用途自定义输入进入术语卡', async ({ page }) => {
  await startResearch(page)
  await answerDirection(page)
  await page.getByRole('button', { name: 'E 其他用途（自定义）', exact: true }).click()
  await expect(page.getByLabel('自定义用途', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认选择', exact: true })).toBeDisabled()
  await page.getByLabel('自定义用途', { exact: true }).fill('为学院写一份面向政策制定的交通安全证据简报，重点关注事故致因与可干预措施。')
  const waiting = page.waitForRequest((request) => request.url().includes('/answers/mode') && request.method() === 'POST')
  await screenshot(page, '04b-e-custom')
  await expectNoHorizontalOverflow(page, 'E 自定义用途')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  const request = await waiting
  const value = request.postDataJSON().value
  expect(value.mode).toBe('E')
  expect(value.custom).toContain('政策制定')
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
})

test('05 C 的用途、C模式任务、本文信息三选一固定卡与 C1+C2 提交', async ({ page }) => {
  await startResearch(page)
  await page.getByRole('textbox', { name: '研究方向或核心问题', exact: true }).fill('肝癌免疫治疗耐药机制的最新进展')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await page.getByRole('button', { name: 'C 撰写论文引言与讨论', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByText('C模式任务', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '本次最需要完成哪一项？', exact: true })).toBeVisible()
  await screenshot(page, '05-c-route')
  await page.getByRole('button', { name: '从零写引言和文献综述（两个都选）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByText('本文信息', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /本文的核心研究问题、拟用方法与预期创新/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /跳过，按通用口径写框架/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /已有论文初稿，提供文件/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /现场口述研究问题与方法/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认选择', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: /已有论文初稿，提供文件/ }).click()
  await page.getByLabel('本文材料（粘贴题目、摘要、方法、结果、创新）', { exact: true }).fill(
    '题目：空间免疫微环境与耐药\n摘要：研究耐药分层\n方法：单细胞与空间转录组\n结果：待补充\n创新：动态分型',
  )
  await page.getByLabel('目标期刊（可跳过）', { exact: true }).fill('Journal of Hepatology')
  const waiting = page.waitForRequest((request) => request.url().includes('/answers/mode') && request.method() === 'POST')
  await screenshot(page, '05-c-info')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  const request = await waiting
  const value = request.postDataJSON().value
  expect(value.mode).toBe('C')
  expect(value.c_route).toBe('C1+C2')
  expect(value.c_info_route).toBe('upload')
  expect(value.c_material).toContain('空间转录组')
  expect(value.target_journal).toBe('Journal of Hepatology')
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
})

test('06 D 团队背景提交与不限年限推荐', async ({ page }) => {
  await startResearch(page)
  await answerDirection(page)
  await page.getByRole('button', { name: 'D 组会或团队学习', exact: true }).click()
  const team = page.getByLabel('团队目前的研究方向/在研问题（可跳过）', { exact: true })
  await expect(team).toBeVisible()
  await team.fill('团队关注肝癌免疫微环境，正在研究空间多组学耐药分型与联合干预。')
  const waiting = page.waitForRequest((request) => request.url().includes('/answers/mode') && request.method() === 'POST')
  await screenshot(page, '06-team-context')
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  const request = await waiting
  expect(request.postDataJSON().value.team_context).toContain('空间多组学')
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '肝细胞癌（命中 1280）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '重点关注的时间范围', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'D 不限，覆盖经典与最新', exact: true })).toBeVisible()
})

test('07 窄屏完整流程、轻量图谱、报告及主要页面横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expectNoHorizontalOverflow(page, '390px 匿名入口')
  await screenshot(page, '07-narrow-entry', false)
  await page.getByRole('button', { name: '开始研究', exact: true }).click()
  await answerDirection(page)
  await expectNoHorizontalOverflow(page, '390px 用途卡')
  await answerModeA(page)
  await expectNoHorizontalOverflow(page, '390px 术语卡')
  await answerTermsAndYears(page)
  await expect(page.getByRole('heading', { name: '文献图谱与检索后调整', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByRole('tab', { name: '轻量版', exact: true }).click()
  await expect(page.getByRole('tab', { name: '轻量版', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTitle('轻量版文献图谱')).toBeVisible()
  await expectNoHorizontalOverflow(page, '390px 图谱与调整卡')
  await screenshot(page, '07-narrow-dashboard', false)

  await page.getByRole('button', { name: '按原计划继续（进入交付形式选择）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await page.getByRole('button', { name: 'A 正式调研报告（Word，含文献依据）', exact: true }).click()
  await page.getByRole('button', { name: '确认选择', exact: true }).click()
  await expect(page.getByRole('heading', { name: '调研交付', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.locator('.report-section').nth(2)).toContainText('## 参考文献')
  await expectNoHorizontalOverflow(page, '390px 报告页')
  await screenshot(page, '07-narrow-report', false)
})

test('08 reduced-motion 与键盘完成入口、方向和用途操作', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'none')
  const start = page.getByRole('button', { name: '开始研究', exact: true })
  await start.focus()
  await expect(start).toHaveCSS('animation-name', 'none')
  await page.keyboard.press('Space')
  await expect(page.getByRole('heading', { name: '研究方向或核心问题', exact: true })).toBeVisible()
const direction = page.getByRole('group', { name: '单选选项' }).getByRole('button').first()
  await direction.focus()
  await page.keyboard.press('Space')
  await expect(direction).toHaveAttribute('aria-pressed', 'true')
  await expect(direction).toHaveCSS('animation-name', 'none')
  const confirm = page.getByRole('button', { name: '确认选择', exact: true })
  await confirm.focus()
  await expect(confirm).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '这次洞察用来做什么？', exact: true })).toBeVisible()
  const mode = page.getByRole('button', { name: 'A 选题立项前摸底', exact: true })
  await mode.focus()
  await page.keyboard.press('Space')
  await expect(mode).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '确认选择', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '以下候选学术术语，选 1 个或多个用于检索。', exact: true })).toBeVisible()
  await expect(page.locator('[data-motion="page-enter"]')).toHaveCSS('animation-name', 'none')
  await screenshot(page, '08-reduced-keyboard')
})

test('09 图谱 tabs 支持标准方向键切换', async ({ page }) => {
  await reachDashboard(page)
  const full = page.getByRole('tab', { name: '满血版', exact: true })
  const light = page.getByRole('tab', { name: '轻量版', exact: true })
  await expect(full).toHaveAttribute('tabindex', '0')
  await expect(light).toHaveAttribute('tabindex', '-1')
  await full.focus()
  await page.keyboard.press('ArrowRight')
  await expect(light).toBeFocused()
  await expect(light).toHaveAttribute('aria-selected', 'true')
  await expect(light).toHaveAttribute('tabindex', '0')
  await expect(full).toHaveAttribute('aria-selected', 'false')
  await expect(full).toHaveAttribute('tabindex', '-1')
  const mobile = await getGraphFrame(page, 'mobile')
  await expect(mobile.locator('body')).toContainText('研究方法')
  await screenshot(page, '09-tabs-after-arrow-right', false)

  await page.keyboard.press('ArrowLeft')
  await expect(full).toBeFocused()
  await expect(full).toHaveAttribute('aria-selected', 'true')
  await getGraphFrame(page, 'desktop')
  await page.keyboard.press('End')
  await expect(light).toBeFocused()
  await expect(light).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Home')
  await expect(full).toBeFocused()
  await expect(full).toHaveAttribute('aria-selected', 'true')
  await getGraphFrame(page, 'desktop')
})

test('10 桌面与窄屏确认回执容纳长中英文及 DOI', async ({ page }, testInfo) => {
  const failures: string[] = []
  const measurements: unknown[] = []
  const longText = `评估肝癌免疫治疗耐药机制与空间免疫微环境的动态关系，并回溯英文长题名及 DOI：https://doi.org/10.1126/sciadv.${'adv0558'.repeat(18)}`
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/e2e/receipt-harness.html')
    const input = page.getByLabel('研究方向或核心问题', { exact: true })
    await input.fill(longText)
    await page.getByRole('button', { name: '确认选择', exact: true }).click()
    const receipt = page.locator('.wizard-receipt')
    await expect(receipt).toBeVisible()
    await expect(receipt).toContainText('已确认：')
    await expect(receipt).toContainText(longText)
    await receipt.evaluate(async (element) => {
      await Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined)))
    })
    const metrics = await receipt.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return {
        viewport: window.innerWidth,
        left: rect.left,
        right: rect.right,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        documentWidth: document.documentElement.scrollWidth,
      }
    })
    measurements.push(metrics)
    if (metrics.right > width + 1 || metrics.left < -1) failures.push(`${width}px 回执边界越出视口: ${JSON.stringify(metrics)}`)
    if (metrics.scrollWidth > metrics.clientWidth + 1) failures.push(`${width}px 回执内容横向溢出: ${JSON.stringify(metrics)}`)
    if (metrics.documentWidth > width + 1) failures.push(`${width}px 页面横向溢出: ${JSON.stringify(metrics)}`)
    await receipt.scrollIntoViewIfNeeded()
    await screenshot(page, `10-receipt-${width}`, false)
  }
  await testInfo.attach('receipt-metrics', {
    body: JSON.stringify(measurements, null, 2),
    contentType: 'application/json',
  })
  expect(failures).toEqual([])
})
