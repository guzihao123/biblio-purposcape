import { createRoot } from 'react-dom/client'

import { MotionButton } from './components/MotionButton'
import { MotionTabs } from './components/MotionTabs'
import { MotionSteps } from './components/MotionSteps'
import { MotionPanel } from './components/MotionPanel'
import { DownloadFeedback } from './components/DownloadFeedback'
import { PageTransition } from './components/PageTransition'
import './styles/full-power.css'
import './styles/motion.css'
import './styles/astral.css'

function MotionLab() {
  return (
    <PageTransition>
      <main className="full-power-site motion-lab">
        <h1>全站交互动效验收</h1>
        <section aria-label="按钮与卡片">
          <MotionButton className="full-power-button" selected>选中按钮</MotionButton>
          <button type="button" className="full-power-option is-selected">选中卡片</button>
        </section>
        <MotionTabs tabs={[{ value: 'all', label: '不限年限' }, { value: 'limited', label: '近三年' }]} />
        <MotionSteps steps={['确认方向', '真实检索', '图谱生成', '交付下载']} />
        <MotionPanel title="摘要证据" lines={['第一条证据原文', '第二条证据原文', '第三条证据原文']} />
        <DownloadFeedback />
      </main>
    </PageTransition>
  )
}

createRoot(document.getElementById('root')!).render(<MotionLab />)
