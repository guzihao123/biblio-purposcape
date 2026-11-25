import { useState } from 'react'
import type { FormEvent } from 'react'
import { MotionButton } from '../components/MotionButton'
import { PageTransition } from '../components/PageTransition'

interface InvitePageProps {
  apiBaseUrl?: string
  onSuccess?: (sessionId: string) => void
}

export function InvitePage({ apiBaseUrl, onSuccess }: InvitePageProps) {
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sessionEstablished, setSessionEstablished] = useState(false)

  const startResearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setSessionEstablished(false)

    const endpoint = apiBaseUrl
      ? `${apiBaseUrl.replace(/\/+$/, '')}/api/session`
      : `${(import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')}/session`
    setSubmitting(true)

    let response: Response
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
    } catch {
      setError('无法连接研究服务，请检查网络后重试。')
      setSubmitting(false)
      return
    }

    if (!response.ok) {
      setError('研究服务暂时不可用，请稍后重试。')
      setSubmitting(false)
      return
    }

    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      setError('研究服务返回异常，请稍后重试。')
      setSubmitting(false)
      return
    }

    const sessionId =
      typeof payload === 'object' && payload !== null && 'session_id' in payload
        ? (payload as { session_id?: unknown }).session_id
        : undefined

    if (typeof sessionId !== 'string' || sessionId.length === 0) {
      setError('研究服务返回异常，请稍后重试。')
      setSubmitting(false)
      return
    }

    setSessionEstablished(true)
    setSubmitting(false)
    onSuccess?.(sessionId)
  }

  return (
    <PageTransition>
      <main className="full-power-site invite-page">
      <div className="site-orbit site-orbit--one" aria-hidden="true" />
      <div className="site-orbit site-orbit--two" aria-hidden="true" />
      <div className="invite-layout">
        <section className="invite-hero" aria-labelledby="invite-hero-title">
          <div className="site-brand" aria-label="研究图谱">
            <span className="site-brand__mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>研究图谱</span>
          </div>
          <p className="site-eyebrow">文献研究 · 公开访问</p>
          <h1 id="invite-hero-title">
            让研究问题
            <span>显露出它的全貌。</span>
          </h1>
          <p className="invite-hero__lede">
            从这一次的研究目标出发，确认方向，让零散文献成为可以理解的脉络。
          </p>
          <ol className="invite-sequence" aria-label="进入步骤">
            <li>
              <span>01</span>
              <div>
                <strong>开始研究</strong>
                <p>建立仅属于本次访问的匿名会话</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>确认研究用途</strong>
                <p>用一张清晰卡片确定本次目标</p>
              </div>
            </li>
          </ol>
        </section>

        <section className="full-power-card invite-card" aria-labelledby="invite-card-title">
          <div className="invite-card__signal" aria-hidden="true">
            <span />
            公开通道可用
          </div>
          <div className="invite-card__heading">
            <p className="site-eyebrow">欢迎回来</p>
            <h2 id="invite-card-title">进入你的研究空间</h2>
            <p>无需邀请码，点击即可开始本次文献探索。</p>
          </div>

          <form onSubmit={startResearch} noValidate aria-busy={submitting}>
            {error && (
              <p className="invite-message invite-message--error" role="alert">
                {error}
              </p>
            )}
            {sessionEstablished && (
              <p className="invite-message invite-message--success" role="status">
                会话已建立，正在进入研究空间。
              </p>
            )}
            <MotionButton className="full-power-button invite-submit" type="submit" disabled={submitting}>
              {submitting ? '正在建立会话…' : '开始研究'}
              <span aria-hidden="true">↗</span>
            </MotionButton>
          </form>

          <div className="invite-card__footer">
            <span className="status-dot" aria-hidden="true" />
            匿名会话凭证由浏览器安全保存
          </div>
        </section>
      </div>
      </main>
    </PageTransition>
  )
}
