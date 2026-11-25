import { useState } from 'react'

export function DownloadFeedback() {
  const [complete, setComplete] = useState(false)
  return (
    <div className={`download-feedback${complete ? ' is-complete' : ''}`}>
      <button type="button" className="motion-button" onClick={() => setComplete(true)}>
        {complete ? '已生成报告' : '生成报告'}
      </button>
      {complete && (
        <span className="download-feedback__status" role="status">
          <span className="download-feedback__check" aria-hidden="true">✓</span>
          报告已就绪，可下载
        </span>
      )}
    </div>
  )
}
