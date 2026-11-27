import { useState } from 'react'
import type { FormEvent } from 'react'
import schoolBadge from '../assets/jspi-badge.png'
import { MotionButton } from '../components/MotionButton'
import { PageTransition } from '../components/PageTransition'
import { SchoolBadgeIntro } from '../components/SchoolBadgeIntro'


// 临时隐藏制作团队区域；恢复时改为 true，标题、学院说明与四张成员卡均保留在源码中。
const SHOW_TEAM_SECTION = false

interface InvitePageProps {
  apiBaseUrl?: string
  onSuccess?: (sessionId: string) => void
  onBadgeIntroActiveChange?: (active: boolean) => void
}


export function InvitePage({ apiBaseUrl, onSuccess, onBadgeIntroActiveChange }: InvitePageProps) {
  const [badgeTarget, setBadgeTarget] = useState<HTMLDivElement | null>(null)
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
      <SchoolBadgeIntro
        source={schoolBadge}
        target={badgeTarget}
        onActiveChange={onBadgeIntroActiveChange}
      />
      <div className="site-orbit site-orbit--one" aria-hidden="true" />
      <div className="site-orbit site-orbit--two" aria-hidden="true" />
      <div className="invite-layout">
        <section className="invite-hero" aria-labelledby="invite-hero-title">
          <div className="invite-identity">
            <div ref={setBadgeTarget} className="school-badge">
              <img
                src={schoolBadge}
                alt="江苏警官学院校徽"
                width="88"
                height="88"
                fetchPriority="high"
              />
            </div>
            <div className="invite-identity__copy">
              <div className="site-brand" aria-label="研究图谱">
                <span className="site-brand__mark" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                <span>研究图谱</span>
              </div>
              <p className="invite-identity__school">江苏警官学院</p>
            </div>
          </div>
          <div className="site-brand site-brand--panorama">
            <span className="site-brand__copy">
              <span className="site-brand__title">
                <span className="site-brand__phrase">智研通——</span>
                <span className="site-brand__phrase">面向科研全过程的</span>
                <span className="site-brand__phrase">智能调研、</span>
                <span className="site-brand__phrase">知识分析与成果生成平台</span>
              </span>
              <span className="site-brand__english" lang="en">biblio-purpose-landscape</span>
            </span>
            <span className="site-brand__aura" aria-hidden="true" />
            <span className="site-brand__beam" aria-hidden="true" />
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

      {SHOW_TEAM_SECTION && (
      <section className="team-section" aria-labelledby="team-title">
        <div className="team-section__heading">
          <div>
            <p className="site-eyebrow">江苏警官学院 · JIANGSU POLICE INSTITUTE</p>
            <h2 id="team-title">制作团队 <span lang="en">PROJECT TEAM</span></h2>
          </div>
          <p>
            智慧交通管理学院 × 刑事科学技术学院
            <span lang="en">Intelligent Traffic Management × Criminal Science and Technology</span>
          </p>
        </div>
        <ul className="team-grid" aria-label="团队成员与分工 / Team members and roles">
          <li className="full-power-card team-card">
            <div className="team-card__affiliation">
              <p className="team-card__college">智慧交通管理学院</p>
              <p className="team-card__college-en" lang="en">School of Intelligent Traffic Management</p>
            </div>
            <div className="team-card__person">
              <h3>梁轩铖</h3>
              <span className="team-card__role">项目经理</span>
            </div>
            <p className="team-card__role-en" lang="en">Project Manager</p>
            <div className="team-card__description">
              <p>统筹项目规划、团队协作与进度推进。</p>
              <p lang="en">Planning, coordination and project delivery.</p>
            </div>
          </li>
          <li className="full-power-card team-card">
            <div className="team-card__affiliation">
              <p className="team-card__college">智慧交通管理学院</p>
              <p className="team-card__college-en" lang="en">School of Intelligent Traffic Management</p>
            </div>
            <div className="team-card__person">
              <h3>陈治霖</h3>
              <span className="team-card__role">成果展示</span>
            </div>
            <p className="team-card__role-en" lang="en">Project Presentation</p>
            <div className="team-card__description">
              <p>整理研究成果，完成演示内容与视觉呈现。</p>
              <p lang="en">Research synthesis, demos and visual presentation.</p>
            </div>
          </li>
          <li className="full-power-card team-card">
            <div className="team-card__affiliation">
              <p className="team-card__college">刑事科学技术学院</p>
              <p className="team-card__college-en" lang="en">School of Criminal Science and Technology</p>
            </div>
            <div className="team-card__person">
              <h3>顾梓豪</h3>
              <span className="team-card__role">全栈开发</span>
            </div>
            <p className="team-card__role-en" lang="en">Full-stack Developer</p>
            <div className="team-card__description">
              <p>覆盖前端交互、后端服务与系统联调。</p>
              <p lang="en">Frontend, backend services and integration.</p>
            </div>
          </li>
          <li className="full-power-card team-card">
            <div className="team-card__affiliation">
              <p className="team-card__college">江苏警官学院</p>
              <p className="team-card__college-en" lang="en">Jiangsu Police Institute</p>
            </div>
            <div className="team-card__person">
              <h3>张圣智</h3>
              <span className="team-card__role">成果展示</span>
            </div>
            <p className="team-card__role-en" lang="en">Project Presentation</p>
            <div className="team-card__description">
              <p>支持成果梳理、展示设计与汇报呈现。</p>
              <p lang="en">Showcase design and presentation support.</p>
            </div>
          </li>
        </ul>
      </section>
      )}
      </main>
    </PageTransition>
  )
}
