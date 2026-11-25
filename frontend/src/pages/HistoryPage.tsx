import { useEffect, useState } from 'react'

import { listTasks } from '../api'
import type { TaskView } from '../api'

const stateLabels: Record<string, string> = {
  done: '已完成',
  searching: '检索中',
  generating: '生成中',
  verifying: '复核中',
  error: '需要处理',
  dashboard_ready: '待调整',
  adjusting: '待交付确认',
}

export function HistoryPage({ onOpen }: { onOpen: (taskId: string) => void }) {
  const [tasks, setTasks] = useState<TaskView[]>([])
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    listTasks()
      .then((result) => {
        if (active) setTasks(result.tasks)
      })
      .catch(() => {
        if (active) setError(true)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <main className="full-power-site content-page">
      <section className="content-shell">
        <header className="page-heading">
          <p className="site-eyebrow">当前匿名会话</p>
          <h1>研究历史</h1>
          <p>这里只显示当前会话创建的任务，其他访问者无法查看。</p>
        </header>
        {error && <p role="alert" className="app-message app-message--error">历史记录暂时无法读取。</p>}
        {!error && tasks.length === 0 && <p className="app-message">当前会话还没有研究任务。</p>}
        <div className="history-list">
          {tasks.map((task) => (
            <button key={task.id} type="button" className="full-power-card history-item" onClick={() => onOpen(task.id)}>
              <span>
                <strong>{task.direction ?? `研究任务 ${task.id.slice(0, 8)}`}</strong>
                <small>{task.created_at ? new Date(task.created_at).toLocaleString('zh-CN') : '时间未记录'}</small>
              </span>
              <span className="history-state">{stateLabels[task.state] ?? task.state}</span>
            </button>
          ))}
        </div>
      </section>
    </main>
  )
}
