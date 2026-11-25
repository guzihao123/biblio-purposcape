import { createRoot } from 'react-dom/client'
import { TaskWizard } from '../src/components/TaskWizard'
import '../src/styles/full-power.css'
import '../src/styles/motion.css'
import '../src/styles/app.css'

createRoot(document.getElementById('root')!).render(
  <TaskWizard
    card={{
      id: 'direction',
      eyebrow: '回执溢出验收',
      title: '确认回执是否容纳真实长文本',
      description: '这是仅在真实浏览器中运行的 e2e 组件页，不修改应用组件。',
      options: [{
        value: 'sample',
        label: '示例研究方向',
        description: '用于验证键盘、选中状态与确认回执。',
      }],
      custom: {
        label: '研究方向或核心问题',
        placeholder: '输入长中文、长英文题名或 DOI',
      },
    }}
    onSubmit={() => undefined}
  />,
)
