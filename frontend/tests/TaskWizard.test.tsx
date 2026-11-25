import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TaskWizard } from '../src/components/TaskWizard'

const modeCard = {
  id: 'mode',
  eyebrow: '用途确认',
  title: '这次洞察用来做什么？',
  description: '选择最贴近当前目标的一项。',
  options: [
    {
      value: 'A',
      label: 'A 选题立项前摸底',
      description: '看清研究空白与切入位置',
      preview: 'Research landscape',
    },
    {
      value: 'B',
      label: 'B 撰写标书/立项依据',
      description: '组织研究基础与论证线索',
      preview: 'Grant rationale',
    },
    {
      value: 'C',
      label: 'C 撰写论文引言与讨论',
      description: '梳理研究脉络与对话位置',
      preview: 'Introduction & discussion',
    },
    {
      value: 'D',
      label: 'D 组会或团队学习',
      description: '快速建立主题认知框架',
      preview: 'Group meeting review',
    },
  ],
  onSubmit: vi.fn(),
}

describe('TaskWizard', () => {
  it('submits the selected Chinese option and keeps multi-select explicit', async () => {
    const user = userEvent.setup()
    modeCard.onSubmit.mockClear()
    render(<TaskWizard card={modeCard} onSubmit={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /A 选题立项前摸底/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    expect(modeCard.onSubmit).toHaveBeenCalledWith({ mode: 'A' })
    expect(screen.getByRole('status')).toHaveTextContent('已确认：A 选题立项前摸底')
  })

  it('submits every selected term as an array only after explicit confirmation', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const termsCard = {
      id: 'terms',
      eyebrow: '术语确认',
      title: '哪些候选术语需要纳入？',
      description: '可多选，确认前可继续调整。',
      multiple: true,
      options: [
        {
          value: '城市内涝',
          label: '城市内涝',
          description: '降雨与积水问题',
          preview: 'Urban flooding',
        },
        {
          value: '地下车库',
          label: '地下车库',
          description: '地下空间与防护场景',
          preview: 'Underground parking',
        },
        {
          value: '韧性城市',
          label: '韧性城市',
          description: '适应与恢复能力',
          preview: 'Resilient cities',
        },
      ],
    }

    render(<TaskWizard card={termsCard} onSubmit={onSubmit} />)

    await user.click(screen.getByRole('button', { name: '城市内涝' }))
    await user.click(screen.getByRole('button', { name: '地下车库' }))
    expect(onSubmit).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith({ terms: ['城市内涝', '地下车库'] })
  })

  it('prevents duplicate confirmation when the button is clicked twice quickly', async () => {
    const user = userEvent.setup()
    modeCard.onSubmit.mockClear()
    render(<TaskWizard card={modeCard} />)

    await user.click(screen.getByRole('button', { name: /A 选题立项前摸底/ }))
    const confirm = screen.getByRole('button', { name: '确认选择' })
    await user.dblClick(confirm)
    await user.click(confirm)

    expect(modeCard.onSubmit).toHaveBeenCalledTimes(1)
  })

  it('prevents duplicate confirmation while an async submission is pending', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockReturnValue(new Promise((resolve) => setTimeout(resolve, 30)))
    render(<TaskWizard card={{ ...modeCard, onSubmit }} />)

    await user.click(screen.getByRole('button', { name: /A 选题立项前摸底/ }))
    const confirm = screen.getByRole('button', { name: '确认选择' })
    await user.dblClick(confirm)
    await user.click(confirm)

    await new Promise((resolve) => setTimeout(resolve, 40))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('allows the same selection to be retried after a rejected submission', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce(undefined)
    render(<TaskWizard card={{ ...modeCard, onSubmit }} />)

    await user.click(screen.getByRole('button', { name: /A 选题立项前摸底/ }))
    const confirm = screen.getByRole('button', { name: '确认选择' })
    await user.click(confirm)
    await user.click(confirm)

    expect(onSubmit).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status')).toHaveTextContent('已确认：A 选题立项前摸底')
  })

  it('submits conditional B project fields and C submodule inputs', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const card = {
      ...modeCard,
      onSubmit: undefined,
      conditional_fields: {
        B: [
          { name: 'name', label: '项目名称', placeholder: '输入项目名称', group: 'project', required: true },
          { name: 'goal', label: '一句话目标', placeholder: '输入目标', group: 'project', required: true },
        ],
        C: [
          {
            name: 'c_route', label: 'C模式任务', kind: 'select' as const,
            options: [
              { value: 'C1', label: '从零写引言' },
              { value: 'C2', label: '从零写文献综述' },
              { value: 'C1+C2', label: '从零写引言和文献综述（两个都选）' },
            ],
          },
          { name: 'user_results', label: '本文信息', placeholder: '研究问题、方法与结果（可跳过）', kind: 'textarea' as const },
          { name: 'target_journal', label: '目标期刊（可跳过）', placeholder: '输入期刊名' },
        ],
      },
    }
    const { unmount } = render(<TaskWizard card={card} onSubmit={onSubmit} />)

    await user.click(screen.getByRole('button', { name: /B 撰写标书/ }))
    expect(screen.getByRole('button', { name: '确认选择' })).toBeDisabled()
    await user.type(screen.getByLabelText('项目名称'), '联合校准项目')
    await user.type(screen.getByLabelText('一句话目标'), '建立联合校准方法')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(onSubmit).toHaveBeenCalledWith({
      mode: 'B',
      project: { name: '联合校准项目', goal: '建立联合校准方法' },
    })
    unmount()

    const cSubmit = vi.fn()
    render(<TaskWizard card={card} onSubmit={cSubmit} />)
    await user.click(screen.getByRole('button', { name: /C 撰写论文/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '本次最需要完成哪一项？' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: /从零写引言和文献综述/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '本文的核心研究问题、拟用方法与预期创新是什么？（可跳过；目标期刊可一并说明）' })).toBeVisible()
    await user.type(screen.getByLabelText('本文信息'), '研究区域迁移机制')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(cSubmit).toHaveBeenCalledWith({
      mode: 'C',
      c_route: 'C1+C2',
      user_results: '研究区域迁移机制',
      target_journal: '',
    })
  })

  it('submits custom direction text and comma-separated custom terms', async () => {
    const user = userEvent.setup()
    const directionSubmit = vi.fn()
    const { unmount } = render(
      <TaskWizard
        card={{
          id: 'direction',
          eyebrow: '方向确认',
          title: '研究方向或核心问题',
          description: '输入一句话方向。',
          custom: { label: '研究方向或核心问题', placeholder: '输入方向' },
          options: [],
        }}
        onSubmit={directionSubmit}
      />,
    )

    await user.type(screen.getByRole('textbox', { name: '研究方向或核心问题' }), '城市内涝韧性')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(directionSubmit).toHaveBeenCalledWith({ direction: '城市内涝韧性' })
    unmount()

    const termsSubmit = vi.fn()
    render(
      <TaskWizard
        card={{
          id: 'terms',
          eyebrow: '术语确认',
          title: '候选术语',
          description: '多个术语用逗号分隔。',
          multiple: true,
          custom: { label: '自定义学术术语', placeholder: '输入术语' },
          options: [],
        }}
        onSubmit={termsSubmit}
      />,
    )
    await user.type(screen.getByLabelText('自定义学术术语'), 'urban flooding, underground garage')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(termsSubmit).toHaveBeenCalledWith({ terms: ['urban flooding', 'underground garage'] })
  })
})
