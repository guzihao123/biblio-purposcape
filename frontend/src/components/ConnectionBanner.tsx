import { useEffect, useState } from 'react'

import { CONNECTION_EVENT, cancelPendingRequests } from '../api'
import type { ConnectionNotice } from '../api'

export function ConnectionBanner() {
  const [notice, setNotice] = useState<ConnectionNotice | null>(null)

  useEffect(() => {
    const handle = (event: Event) => {
      const detail = (event as CustomEvent<ConnectionNotice>).detail
      setNotice(detail.phase === 'online' ? null : detail)
    }
    window.addEventListener(CONNECTION_EVENT, handle)
    return () => window.removeEventListener(CONNECTION_EVENT, handle)
  }, [])

  if (!notice) return null
  const text = notice.phase === 'failed'
    ? '暂时连接不上服务，请稍后重试。'
    : `服务唤醒中，网络不稳定，正在重试（第 ${notice.attempt ?? 1} 次，约 ${Math.max(1, Math.round((notice.delayMs ?? 500) / 1000))} 秒后）…`

  return (
    <div className={`connection-banner connection-banner--${notice.phase}`} role="status" aria-live="polite">
      <span className="connection-banner__dot" aria-hidden="true" />
      <span>{text}</span>
      <button type="button" onClick={cancelPendingRequests}>取消等待</button>
    </div>
  )
}
