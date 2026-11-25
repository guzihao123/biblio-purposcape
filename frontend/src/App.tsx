import { useCallback, useEffect, useRef, useState } from 'react'

import { createTask, getTask } from './api'
import type { TaskView } from './api'
import { InvitePage } from './pages/InvitePage'
import { TaskPage } from './pages/TaskPage'
import { HistoryPage } from './pages/HistoryPage'
import { AdminSkillPage } from './pages/AdminSkillPage'

type Route =
  | { type: 'home' }
  | { type: 'task'; id: string }
  | { type: 'history' }
  | { type: 'admin' }

function readRoute(): Route {
  const path = window.location.pathname
  if (path === '/history') return { type: 'history' }
  if (path === '/admin/skill') return { type: 'admin' }
  const match = path.match(/^\/tasks\/([^/]+)/)
  return match ? { type: 'task', id: match[1] } : { type: 'home' }
}

export function App() {
  const [sessionReady, setSessionReady] = useState(false)
  const [route, setRoute] = useState<Route>(readRoute)
  const [task, setTask] = useState<TaskView | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const startingRef = useRef(false)
  const idempotencyKeyRef = useRef<string | null>(null)

  useEffect(() => {
    const update = () => setRoute(readRoute())
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])

  const updateTask = useCallback((next: TaskView) => setTask(next), [])

  const openTask = useCallback(async (id: string) => {
    setError('')
    try {
      const loaded = await getTask(id)
      setTask(loaded)
      setRoute({ type: 'task', id })
      window.history.pushState({}, '', `/tasks/${id}`)
    } catch {
      setError('任务暂时无法打开，请稍后重试。')
    }
  }, [])

  const startTask = useCallback(async (newResearch = false) => {
    if (startingRef.current) return
    if (newResearch || !idempotencyKeyRef.current) {
      idempotencyKeyRef.current = globalThis.crypto?.randomUUID?.()
        ?? `research-${Date.now()}-${Math.random().toString(36).slice(2)}`
    }
    const idempotencyKey = idempotencyKeyRef.current
    startingRef.current = true
    setLoading(true)
    setError('')
    try {
      const created = await createTask(idempotencyKey)
      idempotencyKeyRef.current = null
      setTask(created)
      setRoute({ type: 'task', id: created.id })
      window.history.pushState({}, '', `/tasks/${created.id}`)
    } catch {
      // Keep the same key for a later retry after a timeout or server failure.
      setError('研究任务暂时无法创建，请稍后重试。')
    } finally {
      setLoading(false)
      startingRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!sessionReady) return
    if (route.type === 'home') void startTask()
    if (route.type === 'task' && task?.id !== route.id) void openTask(route.id)
  }, [sessionReady, route, task?.id, startTask, openTask])

  if (!sessionReady) {
    return <InvitePage onSuccess={() => setSessionReady(true)} />
  }

  return (
    <div className="app-root">
      <nav className="app-nav" aria-label="应用导航">
        <span className="app-nav__brand">研究图谱</span>
        <button type="button" onClick={() => {
          setRoute({ type: 'history' })
          window.history.pushState({}, '', '/history')
        }}>研究历史</button>
        <button type="button" onClick={() => {
          setRoute({ type: 'admin' })
          window.history.pushState({}, '', '/admin/skill')
        }}>Skill 管理</button>
        <button type="button" onClick={() => void startTask(true)}>新建研究</button>
      </nav>
      {error && <p className="app-message app-message--error" role="alert">{error}</p>}
      {loading && <p className="app-message" role="status">正在创建研究任务…</p>}
      {route.type === 'history' && <HistoryPage onOpen={(id) => void openTask(id)} />}
      {route.type === 'admin' && <AdminSkillPage />}
      {route.type === 'task' && task?.id === route.id && <TaskPage task={task} onTask={updateTask} />}
    </div>
  )
}
