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

const cConditionalFields = [
  {
    name: 'c_route', label: 'C模式任务', kind: 'select' as const,
    options: [
      { value: 'C1', label: '从零写引言' },
      { value: 'C2', label: '从零写文献综述' },
      { value: 'C1+C2', label: '从零写引言和文献综述（两个都选）' },
    ],
  },
  {
    name: 'c_info_route', label: '本文信息', kind: 'select' as const,
    options: [
      { value: 'skip', label: '跳过，按通用口径写框架' },
      { value: 'upload', label: '已有论文初稿，提供文件' },
      { value: 'oral', label: '现场口述研究问题与方法' },
    ],
  },
  {
    name: 'c_material', label: '本文材料（粘贴题目、摘要、方法、结果、创新）',
    placeholder: '分段粘贴', kind: 'textarea' as const,
  },
  { name: 'target_journal', label: '目标期刊（可跳过）', placeholder: '输入期刊名' },
]

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

  it('submits conditional B project fields after choosing a project theme, and C submodule inputs', async () => {
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
        C: cConditionalFields,
      },
    }
    const loadProjectThemes = vi.fn().mockResolvedValue([
      {
        value: 'theme-1',
        label: '联合校准项目主题',
        description: '建立联合校准方法',
        preview: '研究对象：车库\n方法：联合建模\n预期产出：校准协议',
        theme: {
          name: '联合校准项目主题',
          goal: '建立联合校准方法',
          object: '车库',
          method: '联合建模',
          expected_output: '校准协议',
        },
      },
    ])
    const { unmount } = render(<TaskWizard card={card} onSubmit={onSubmit} loadProjectThemes={loadProjectThemes} />)

    await user.click(screen.getByRole('button', { name: /B 撰写标书/ }))
    expect(screen.queryByLabelText('项目名称')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '请选择一个项目主题候选' })).toBeVisible()
    await user.click(await screen.findByRole('button', { name: '联合校准项目主题' }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '确认项目名称、目标与资助类别' })).toBeVisible()
    expect(screen.getByLabelText('项目名称')).toHaveValue('联合校准项目主题')
    expect(screen.getByLabelText('一句话目标')).toHaveValue('建立联合校准方法')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(onSubmit).toHaveBeenCalledWith({
      mode: 'B',
      project: { name: '联合校准项目主题', goal: '建立联合校准方法' },
      theme: {
        name: '联合校准项目主题',
        goal: '建立联合校准方法',
        object: '车库',
        method: '联合建模',
        expected_output: '校准协议',
      },
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
    expect(screen.getByRole('button', { name: /跳过，按通用口径写框架/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /已有论文初稿，提供文件/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /现场口述研究问题与方法/ })).toBeVisible()
    expect(screen.getByText('不提供本文细节，只给框架与占位提示，并在交付中注明。')).toBeVisible()
    expect(screen.getByText('用户提供论文文件或粘贴内容后，先提取研究目标、方法、数据与创新，再决定补检索。')).toBeVisible()
    expect(screen.getByText('用户直接说明研究问题、方法与创新，据此填写本文研究思路与贡献相关内容。')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认选择' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /已有论文初稿，提供文件/ }))
    expect(screen.getByRole('button', { name: '确认选择' })).toBeDisabled()
    await user.type(screen.getByLabelText('本文材料（粘贴题目、摘要、方法、结果、创新）'), '题目：区域迁移机制\n方法：空间滞后模型\n创新：动态分型')
    await user.type(screen.getByLabelText('目标期刊（可跳过）'), 'Journal of Hepatology')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(cSubmit).toHaveBeenCalledWith({
      mode: 'C',
      c_route: 'C1+C2',
      c_info_route: 'upload',
      c_material: '题目：区域迁移机制\n方法：空间滞后模型\n创新：动态分型',
      target_journal: 'Journal of Hepatology',
    })
  })

  it('submits skip and oral C info cards without inventing material for skip', async () => {
    const card = { ...modeCard, onSubmit: undefined, conditional_fields: { C: cConditionalFields } }
    for (const [label, route, material] of [
      ['跳过，按通用口径写框架', 'skip', ''],
      ['现场口述研究问题与方法', 'oral', '研究问题：耐药分型\n方法：单细胞与空间转录组'],
    ] as const) {
      const onSubmit = vi.fn()
      const user = userEvent.setup()
      const { unmount } = render(<TaskWizard card={card} onSubmit={onSubmit} />)
      await user.click(screen.getByRole('button', { name: /C 撰写论文/ }))
      await user.click(screen.getByRole('button', { name: '确认选择' }))
      await user.click(screen.getByRole('button', { name: /从零写文献综述/ }))
      await user.click(screen.getByRole('button', { name: '确认选择' }))
      await user.click(screen.getByRole('button', { name: new RegExp(label) }))
      if (route === 'oral') {
        expect(screen.getByRole('button', { name: '确认选择' })).toBeDisabled()
        await user.type(screen.getByLabelText('现场口述：研究问题与方法'), material)
        expect(screen.getByRole('button', { name: '确认选择' })).toBeEnabled()
      }
      await user.click(screen.getByRole('button', { name: '确认选择' }))
      expect(onSubmit).toHaveBeenCalledWith({
        mode: 'C',
        c_route: 'C2',
        c_info_route: route,
        c_material: material,
        target_journal: '',
      })
      unmount()
    }
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

  it('submits E with its generic custom purpose field and keeps the option selected', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(
      <TaskWizard
        card={{
          ...modeCard,
          onSubmit: undefined,
          custom: { label: '自定义用途', placeholder: '写明用途', required: true },
          custom_for: ['E'],
          options: [
            ...modeCard.options,
            { value: 'E', label: 'E 其他用途（自定义）', description: '自由用途', preview: '其他' },
          ],
        }}
        onSubmit={onSubmit}
      />,
    )

    expect(screen.queryByLabelText('自定义用途')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'E 其他用途（自定义）' }))
    expect(screen.getByLabelText('自定义用途')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认选择' })).toBeDisabled()
    await user.type(screen.getByLabelText('自定义用途'), '为学院写政策证据简报')
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    expect(onSubmit).toHaveBeenCalledWith({
      mode: 'E',
      custom: '为学院写政策证据简报',
    })
  })

  it('allows a custom B project theme when no candidates are available', async () => {
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
      },
    }
    render(<TaskWizard card={card} onSubmit={onSubmit} loadProjectThemes={async () => []} />)

    await user.click(screen.getByRole('button', { name: /B 撰写标书/ }))
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '请选择一个项目主题候选' })).toBeVisible()
    await user.type(await screen.findByLabelText('自定义项目主题'), '自定义项目主题')
    await user.click(screen.getByRole('button', { name: '确认选择' }))
    expect(await screen.findByRole('heading', { name: '确认项目名称、目标与资助类别' })).toBeVisible()
    expect(screen.getByLabelText('项目名称')).toHaveValue('自定义项目主题')
    await user.type(screen.getByLabelText('一句话目标'), '形成可验证方案')
    await user.click(screen.getByRole('button', { name: '确认选择' }))

    expect(onSubmit).toHaveBeenCalledWith({
      mode: 'B',
      project: { name: '自定义项目主题', goal: '形成可验证方案' },
      theme: {
        name: '自定义项目主题',
        goal: '',
        object: '',
        method: '',
        expected_output: '',
        custom: '自定义项目主题',
      },
    })
  })
})
