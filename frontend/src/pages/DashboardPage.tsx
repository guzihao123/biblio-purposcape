import { useEffect, useState } from 'react'

import { answerTask, artifactUrl, getDashboard } from '../api'
import type { DashboardPayload, TaskView } from '../api'
import { MotionTabs } from '../components/MotionTabs'
import { TaskWizard } from '../components/TaskWizard'
import type { TaskAnswer } from '../components/TaskWizard'

interface DashboardPageProps {
  task: TaskView
  onTask: (task: TaskView) => void
}

export function DashboardPage({ task, onTask }: DashboardPageProps) {
  const [payload, setPayload] = useState<DashboardPayload | null>(null)
  const [version, setVersion] = useState('desktop')
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    getDashboard(task.id)
      .then((result) => {
        if (active) setPayload(result)
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [task.id])

  const artifacts = payload?.artifacts ?? []
  const selected = artifacts.find((artifact) => artifact.name === `${version}.html`)
    ?? artifacts.find((artifact) => artifact.name === 'index.html')

  const submit = async (answer: TaskAnswer) => {
    if (!task.card) return
    onTask(await answerTask(task.id, task.card.id, answer))
  }

  return (
    <main className="full-power-site content-page">
      <section className="content-shell">
        <header className="page-heading">
          <p className="site-eyebrow">七类图谱 · 双范围</p>
          <h1>文献图谱与检索后调整</h1>
          <p>{payload?.data?.overview ?? '正在读取真实图谱与统计口径…'}</p>
        </header>
        {error && <p role="alert" className="app-message app-message--error">图谱暂时无法读取，请稍后重试。</p>}
        {selected && (
          <section className="full-power-card dashboard-frame">
            <MotionTabs
              tabs={[{ value: 'desktop', label: '满血版' }, { value: 'mobile', label: '轻量版' }]}
              value={version}
              onChange={setVersion}
            />
            <iframe
              key={artifactUrl(selected.url)}
              title={version === 'desktop' ? '满血版文献图谱' : '轻量版文献图谱'}
              src={artifactUrl(selected.url)}
              sandbox="allow-scripts allow-same-origin"
            />
          </section>
        )}
        {task.card && <TaskWizard card={task.card} onSubmit={submit} />}
      </section>
    </main>
  )
}
