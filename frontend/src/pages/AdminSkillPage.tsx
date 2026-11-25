import { useState } from 'react'

import {
  createSkillDraft,
  listSkillVersions,
  publishSkillVersion,
  regressSkillVersion,
  rollbackSkillVersion,
} from '../api'
import type { SkillVersion } from '../api'
import { MotionButton } from '../components/MotionButton'

export function AdminSkillPage() {
  const [token, setToken] = useState('')
  const [versions, setVersions] = useState<SkillVersion[]>([])
  const [activeId, setActiveId] = useState('')
  const [draft, setDraft] = useState<SkillVersion | null>(null)
  const [regressionPassed, setRegressionPassed] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const active = versions.find((version) => version.id === activeId) ?? versions.find((version) => version.state === 'published')

  const run = async (action: () => Promise<void>) => {
    setError('')
    try {
      await action()
    } catch {
      setError('操作失败，请检查管理员令牌、回归结果与版本状态。')
    }
  }

  const load = () => run(async () => {
    const result = await listSkillVersions(token)
    setVersions(result.versions)
    setActiveId(result.versions.find((version) => version.state === 'published')?.id ?? '')
    setMessage('版本已加载')
  })

  return (
    <main className="full-power-site content-page">
      <section className="content-shell">
        <header className="page-heading">
          <p className="site-eyebrow">草稿 → 回归 → 发布 → 回退</p>
          <h1>Skill 版本管理</h1>
          <p>运行中的任务继续使用启动版本。令牌只用于本次页面操作，不写入浏览器存储。</p>
        </header>
        <div className="full-power-card admin-token">
          <label htmlFor="admin-token">管理员令牌</label>
          <input
            id="admin-token"
            type="password"
            value={token}
            autoComplete="off"
            onChange={(event) => setToken(event.target.value)}
          />
          <MotionButton type="button" className="full-power-button" onClick={load} disabled={!token}>加载版本</MotionButton>
        </div>
        {message && <p className="app-message" role="status">{message}</p>}
        {error && <p className="app-message app-message--error" role="alert">{error}</p>}
        {active && <p className="app-message">当前发布：{active.id}</p>}
        {active && (
          <MotionButton
            type="button"
            className="full-power-button"
            onClick={() => run(async () => {
              const created = await createSkillDraft(token, active.id, active.content)
              setDraft(created)
              setRegressionPassed(false)
              setVersions((current) => [...current.filter((version) => version.id !== created.id), created])
              setMessage(`已创建草稿 ${created.id}`)
            })}
          >创建草稿</MotionButton>
        )}
        {draft && (
          <section className="full-power-card admin-draft">
            <h2>当前草稿：{draft.id}</h2>
            <details>
              <summary>查看配置与差异来源</summary>
              <pre>{JSON.stringify({ parent_id: draft.parent_id, content: draft.content }, null, 2)}</pre>
            </details>
            <div className="admin-actions">
              <MotionButton type="button" className="full-power-button" onClick={() => run(async () => {
                const report = await regressSkillVersion(token, draft.id)
                setRegressionPassed(report.passed)
                setMessage(report.passed ? '回归已通过，可以发布' : `回归未通过：${(report.errors ?? []).join('；')}`)
              })}>运行回归</MotionButton>
              <MotionButton type="button" className="full-power-button" disabled={!regressionPassed} onClick={() => run(async () => {
                const published = await publishSkillVersion(token, draft.id)
                setVersions((current) => current.map((version) => {
                  if (version.id === published.id) return published
                  if (version.id === activeId) return { ...version, state: 'archived' }
                  return version
                }))
                setActiveId(published.id)
                setDraft(null)
                setRegressionPassed(false)
                setMessage(`已发布 ${published.id}`)
              })}>发布草稿</MotionButton>
            </div>
          </section>
        )}
        <section className="version-list" aria-label="历史版本">
          {versions.map((version) => (
            <article key={version.id} className="full-power-card version-item">
              <strong>{version.id}</strong>
              <span>版本 {version.version} · {version.state}</span>
              {version.state === 'archived' && version.id !== activeId && (
                <MotionButton type="button" className="full-power-button" onClick={() => run(async () => {
                  const restored = await rollbackSkillVersion(token, version.id)
                  setVersions((current) => current.map((item) => {
                    if (item.id === restored.id) return restored
                    if (item.id === activeId) return { ...item, state: 'archived' }
                    return item
                  }))
                  setActiveId(restored.id)
                  setMessage(`已回退到 ${restored.id}`)
                })}>回退到 {version.id}</MotionButton>
              )}
            </article>
          ))}
        </section>
      </section>
    </main>
  )
}
