import { useEffect } from 'react'

import { answerTask, getTask } from '../api'
import type { TaskView } from '../api'
import { MotionSteps } from '../components/MotionSteps'
import { TaskWizard } from '../components/TaskWizard'
import type { TaskAnswer } from '../components/TaskWizard'
import { DashboardPage } from './DashboardPage'
import { ReportPage } from './ReportPage'

interface TaskPageProps {
  task: TaskView
  onTask: (task: TaskView) => void
}

const activeStates = new Set(['searching', 'generating', 'verifying'])

export function TaskPage({ task, onTask }: TaskPageProps) {
  useEffect(() => {
    if (!activeStates.has(task.state)) return
    const timer = window.setInterval(() => {
      getTask(task.id).then(onTask).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [task.id, task.state, onTask])

  const submit = async (answer: TaskAnswer) => {
    if (!task.card) return
    onTask(await answerTask(task.id, task.card.id, answer))
  }

  if (task.state === 'done') return <ReportPage taskId={task.id} />
  if (task.state === 'dashboard_ready' || task.state === 'adjusting') {
    return <DashboardPage task={task} onTask={onTask} />
  }
  if (activeStates.has(task.state)) {
    return (
      <main className="full-power-site content-page">
        <section className="content-shell narrow-shell">
          <p className="site-eyebrow">任务正在执行</p>
          <h1>{task.progress?.message || '正在处理研究任务'}</h1>
          <MotionSteps
            steps={['确认设定', '双范围检索', '图谱调整', '生成交付']}
            current={task.state === 'searching' ? 1 : 3}
            interactive={false}
          />
          <p className="app-message" role="status">
            当前阶段：{task.progress?.stage ?? task.state}；页面会自动更新，无需重复提交。
          </p>
        </section>
      </main>
    )
  }
  if (task.state === 'error') {
    return (
      <main className="full-power-site content-page">
        <p role="alert" className="app-message app-message--error">
          {task.progress?.message || '任务执行失败，请稍后重试。'}
        </p>
      </main>
    )
  }
  if (task.card) return <TaskWizard card={task.card} onSubmit={submit} />
  return <main className="full-power-site content-page"><p className="app-message">正在准备下一步…</p></main>
}
