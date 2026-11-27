import { useEffect, useState } from 'react'

import { artifactUrl, getReport } from '../api'
import type { ReportPayload } from '../api'
import { ReportText } from '../components/ReportText'

const downloadLabels: Record<string, string> = {
  '综述初稿.docx': '下载 Word 报告',
  '标书-文献综述分析.docx': '下载 Word 报告',
  '调研报告.docx': '下载 Word 报告',
  'report.docx': '下载 Word 报告',
  'C1_引言.docx': '下载 C1 引言 Word',
  'C2_文献综述.docx': '下载 C2 文献综述 Word',
  'slides.pptx': '下载 PPT',
  'dialogue.json': '下载对话要点',
  'verify_report.txt': '查看证据复核',
  'conformance.md': '查看需求对账',
}

export function ReportPage({ taskId }: { taskId: string }) {
  const [report, setReport] = useState<ReportPayload | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    getReport(taskId)
      .then((result) => {
        if (active) setReport(result)
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [taskId])

  if (error) {
    return <main className="full-power-site content-page"><p role="alert" className="app-message app-message--error">报告暂时无法读取，请稍后重试。</p></main>
  }
  if (!report) {
    return <main className="full-power-site content-page"><p className="app-message">正在读取提纲、样章与交付文件…</p></main>
  }

  return (
    <main className="full-power-site content-page">
      <article className="content-shell report-shell">
        <header className="page-heading">
          <p className="site-eyebrow">提纲 → 样章 → 正文</p>
          <h1>调研交付</h1>
          <p>正文与参考文献保持相同引用编号，下载文件中含复核说明。</p>
        </header>
        {report.missing && report.missing.length > 0 && (
          <section className="full-power-card report-section">
            <p role="alert" className="app-message app-message--error">
              部分交付文件缺失或未同步：{report.missing.join('、')}。以下为可用内容，请重新运行任务或联系管理员。
            </p>
          </section>
        )}
        <section className="full-power-card report-section">
          <h2>提纲</h2>
          <ReportText text={report.outline} />
        </section>
        <section className="full-power-card report-section">
          <h2>样章</h2>
          <ReportText text={report.sample} />
        </section>
        <section className="full-power-card report-section">
          <h2>正文</h2>
          <ReportText text={report.body} />
        </section>
        <nav className="download-list" aria-label="交付文件下载">
          {report.artifacts.map((artifact) => {
            const label = downloadLabels[artifact.name]
              ?? (artifact.name.endsWith('.pptx') ? '下载 PPT' : undefined)
              ?? (artifact.name.endsWith('.docx') ? '下载 Word 报告' : undefined)
            if (!label) return null
            return <a key={artifact.name} className="full-power-button" href={artifactUrl(artifact.url)} download>{label}</a>
          })}
        </nav>
      </article>
    </main>
  )
}
