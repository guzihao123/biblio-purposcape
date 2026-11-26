from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import SkillVersion, TaskAnswer, TaskEvent
from app.schemas import CardId


def _option(value, label, description, preview):
    return {'value': value, 'label': label, 'description': description, 'preview': preview}


def _mode_answer(db, task_id):
    answer = db.query(TaskAnswer).filter_by(task_id=task_id, card_id='mode').one_or_none()
    return str((answer.value if answer else {}).get('mode', 'A'))


def _direction_card():
    return {
        'id': 'direction',
        'eyebrow': '方向确认',
        'title': '研究方向或核心问题',
        'description': '请用一句话写出你要摸底的方向，也可以直接选择示例。',
        'custom': {'label': '研究方向或核心问题', 'placeholder': '例如：道路交通事故严重程度致因识别与风险评估研究'},
        'options': [
            _option('道路交通事故严重程度致因识别与风险评估研究', '道路交通事故严重程度致因识别与风险评估研究', '交通安全·事故致因类', '也可直接输入自己的方向'),
            _option('城市交叉口交通信号配时优化与拥堵治理研究', '城市交叉口交通信号配时优化与拥堵治理研究', '交通控制·运行管理类', '也可直接输入自己的方向'),
            _option('车路协同环境下交通流预测与智能管控方法研究', '车路协同环境下交通流预测与智能管控方法研究', '智能交通·技术方向类', '也可直接输入自己的方向'),
            _option('公共交通优先与城市停车需求管理策略研究', '公共交通优先与城市停车需求管理策略研究', '交通规划·需求管理类', '也可直接输入自己的方向'),
        ],
    }


def _mode_card():
    return {
        'id': 'mode',
        'eyebrow': '用途确认',
        'title': '这次洞察用来做什么？',
        'description': '选择最贴近当前目标的一项；选 B 先凝练项目主题，选 E 请写明自定义用途。',
        'options': [
            _option('A', 'A 选题立项前摸底', '领域全景、研究空白与可做方向', '选题立项前摸底'),
            _option('B', 'B 撰写标书/立项依据', '先选项目主题，再填写项目名称与目标', '标书与立项依据'),
            _option('C', 'C 撰写论文引言与文献综述', '分别组织 C1 引言与 C2 文献综述素材', '论文写作'),
            _option('D', 'D 组会或团队学习', '系统调研、方法比较与代表作精读', '组会主题调研'),
            _option(
                'E', 'E 其他用途（自定义）',
                '自由描述用途，按基线形态交付：综述初稿 + 空白点清单 + 3 个可做方向',
                '其他用途',
            ),
        ],
        'custom': {
            'label': '自定义用途',
            'placeholder': '例如：为学院写一份面向政策制定的交通安全证据简报（写明交付对象、关注重点与期望产出）',
            'required': True,
        },
        'custom_for': ['E'],
        'conditional_fields': {
            'B': [
                {'name': 'name', 'label': '项目名称', 'group': 'project', 'required': True},
                {'name': 'goal', 'label': '一句话目标', 'group': 'project', 'required': True},
                {'name': 'funding', 'label': '资助类别/学科属性（可跳过）', 'group': 'project'},
                {
                    'name': 'b_input_path', 'label': '标书输入路径', 'kind': 'select',
                    'options': [
                        {'value': 'direction', 'label': '仅方向/主题，由系统凝练项目'},
                        {'value': 'draft', 'label': '已有申请书/研究方案草稿'},
                    ],
                },
                {
                    'name': 'project_draft', 'label': '申请书/研究方案草稿（可粘贴核心内容）',
                    'kind': 'textarea',
                    'placeholder': '粘贴研究内容、技术路线、可行性、预期成果等核心段落；选择草稿路径时必填',
                },
                {
                    'name': 'policy_materials',
                    'label': '政策/报告/统计材料（可粘贴全文或链接，可跳过）',
                    'kind': 'textarea',
                    'placeholder': '可粘贴多段材料；每段用键：值写标题、发布机构、文号、成文日期、链接，随后粘贴原文。也可只填官方链接（需已配置授权抓取器）。',
                },
            ],
            'C': [
                {
                    'name': 'c_route', 'label': 'C模式任务', 'kind': 'select',
                    'options': [
                        {'value': 'C1', 'label': '从零写引言'},
                        {'value': 'C2', 'label': '从零写文献综述'},
                        {'value': 'C1+C2', 'label': '从零写引言和文献综述（两个都选）'},
                    ],
                },
                {
                    'name': 'c_info_route', 'label': '本文信息', 'kind': 'select',
                    'options': [
                        {
                            'value': 'skip', 'label': '跳过，按通用口径写框架',
                            'description': '不提供本文细节，只给框架与占位提示，并在交付中注明。',
                        },
                        {
                            'value': 'upload', 'label': '已有论文初稿，提供文件',
                            'description': '用户提供论文文件或粘贴内容后，先提取研究目标、方法、数据与创新，再决定补检索。',
                        },
                        {
                            'value': 'oral', 'label': '现场口述研究问题与方法',
                            'description': '用户直接说明研究问题、方法与创新，据此填写本文研究思路与贡献相关内容。',
                        },
                    ],
                },
                {
                    'name': 'c_material',
                    'label': '本文材料（粘贴题目、摘要、方法、结果、创新）',
                    'placeholder': '按题目/摘要/方法/结果/创新分段粘贴；目标期刊可写“目标期刊：名称”；现场口述时写研究问题与方法',
                    'kind': 'textarea',
                },
            ],
            'D': [
                {'name': 'team_context', 'label': '团队目前的研究方向/在研问题（可跳过）', 'kind': 'textarea'},
            ],
        },
    }


def _terms_card(db, task, version, answers=None, candidate_event=None):
    if answers is None:
        event = db.query(TaskEvent).filter_by(
            task_id=task.id,
            event_type='terms_candidates',
        ).order_by(TaskEvent.id.desc()).first()
    else:
        event = candidate_event
    payload = {}
    if event is not None:
        payload = event.get('payload', {}) if isinstance(event, dict) else event.payload
    candidates = payload.get('options', [])
    if event is None and version is not None:
        candidates = version.content.get('cards', {}).get('candidate_terms', [])
    return {
        'id': 'terms',
        'eyebrow': '术语确认',
        'title': '以下候选学术术语，选 1 个或多个用于检索。',
        'description': '候选词来自当前 Skill 版本；也可直接输入术语，多个术语用逗号分隔。',
        'multiple': True,
        'custom': {'label': '自定义学术术语', 'placeholder': '例如：urban flooding, underground garage'},
        'options': candidates,
    }


def _years_card(mode):
    year = datetime.now(timezone.utc).year
    options = [
        _option('A', f'A 近3年（最新前沿）', f'--from-year {year - 3}；池子最小', '最新前沿'),
        _option('B', 'B 近5年', f'--from-year {year - 5}；默认档', '近5年'),
        _option('C', 'C 近10年（含演进脉络）', f'--from-year {year - 10}；池子变大', '含演进脉络'),
        _option('D', 'D 不限，覆盖经典与最新', '不加 --from-year；只出不限年限范围', '覆盖经典与最新'),
    ]
    if mode == 'D':
        options = [options[3], options[0], options[1], options[2]]
    return {
        'id': 'years',
        'eyebrow': '年限确认',
        'title': '重点关注的时间范围',
        'description': '限定范围与不限范围分别检索；选择不限时只出不限范围。',
        'options': options,
    }


def _adjustment_card():
    return {
        'id': 'adjustment',
        'eyebrow': '检索后调整',
        'title': '看完分布，要不要调整？',
        'description': '看完这些图谱，要调整哪些设定？可多选；按原计划继续具有一票否决权。',
        'multiple': True,
        'options': [
            _option('terms', '调整学术术语', '重出术语卡并重建双范围', '重新检索'),
            _option('years', '调整年限范围', '只重建限定范围，不限范围复用', '限定范围更新'),
            _option('mode', '调整洞察用途', '重载模式卡并重选写作池', '模式更新'),
            _option('continue', '按原计划继续（进入交付形式选择）', '冻结设定并选择交付形式', '进入最后一问'),
        ],
    }


def _delivery_card(mode):
    forms = {
        'A': ('A 正式调研报告（Word，含文献依据）', '带参考文献、复核边界与可下载 Word 文件', 'Word'),
        'B': ('B 仅对话中给要点和代表文献', '5–8 条要点与不超过 10 篇代表文献', 'A 模式含七类各 2 个选题槽位及未推荐原因；其他模式 5–8 条要点'),
        'C': ('C 展示 PPT', '8–12 页；D 模式约 20–30 页组会汇报', 'D 模式约 20–30 页，含真实图表与团队讨论；其他模式 8–12 页'),
    }
    order = ['A', 'B', 'C']
    if mode == 'D':
        order = ['C', 'A', 'B']
    elif mode == 'A':
        order = ['B', 'A', 'C']
    options = []
    for form in order:
        label, description, preview = forms[form]
        options.append(_option(form, label, description, preview))
    card = {
        'id': 'delivery',
        'eyebrow': '交付形式确认',
        'title': '希望得到的交付形式',
        'description': '这是最后一问；答完后直接生成，不再插入确认。',
        'options': options,
    }
    if mode == 'D':
        card['options'].append(_option(
            'OTHER', 'D 其他（自定义交付形态）',
            '说明期望形态；无法生成时使用最接近的替代',
            '其他形态',
        ))
        card['custom'] = {
            'label': '自定义交付形态',
            'placeholder': '例如：一页纸决策简报 + 附录、可打印长图等',
            'required': True,
        }
        card['custom_for'] = ['OTHER']
    return card


def card_for(db, task, answers=None, candidate_event=None, version_content=None):
    if not task.next_card:
        return None
    card = CardId(task.next_card)
    version = (
        db.get(SkillVersion, task.skill_version_id) if task.skill_version_id and version_content is None
        else SimpleNamespace(content=version_content or {})
    )
    mode = _mode_answer(db, task.id) if answers is None else str((answers.get('mode') or {}).get('mode', 'A'))
    builders = {
        CardId.DIRECTION: lambda: _direction_card(),
        CardId.MODE: lambda: _mode_card(),
        CardId.TERMS: lambda: _terms_card(db, task, version, answers=answers, candidate_event=candidate_event),
        CardId.YEARS: lambda: _years_card(mode),
        CardId.ADJUSTMENT: lambda: _adjustment_card(),
        CardId.DELIVERY: lambda: _delivery_card(mode),
    }
    return builders[card]()


def task_payload(db, task):
    progress = task.progress
    direction_answer = db.query(TaskAnswer).filter_by(task_id=task.id, card_id='direction').one_or_none()
    direction = (direction_answer.value if direction_answer else {}).get('direction')
    return {
        'id': task.id,
        'session_id': task.session_id,
        'skill_version_id': task.skill_version_id,
        'direction': direction,
        'state': task.state,
        'next_card': task.next_card,
        'card': card_for(db, task),
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'updated_at': task.updated_at.isoformat() if task.updated_at else None,
        'progress': None if progress is None else {
            'stage': progress.stage,
            'message': progress.message,
            'percent': int(getattr(progress, 'percent', 0) or 0),
            'checkpoint': progress.checkpoint,
        },
    }


def remote_task_payload(db, task, candidate_event=None, version_content=None):
    answers = task.get('answers') or {}
    direction = answers.get('direction')
    if isinstance(direction, str):
        direction_value = direction
    elif isinstance(direction, dict):
        direction_value = direction.get('direction')
    else:
        direction_value = None
    progress = task.get('progress') or {}
    surrogate = SimpleNamespace(
        id=task['id'],
        next_card=task.get('next_card'),
        state=task.get('state'),
        skill_version_id=task.get('skill_version_id'),
        created_at=task.get('created_at'),
        updated_at=task.get('updated_at'),
    )
    return {
        'id': task['id'],
        'session_id': task['session_id'],
        'skill_version_id': task.get('skill_version_id'),
        'direction': direction_value,
        'state': task['state'],
        'next_card': task.get('next_card'),
        'card': card_for(db, surrogate, answers=answers, candidate_event=candidate_event, version_content=version_content),
        'created_at': task.get('created_at'),
        'updated_at': task.get('updated_at'),
        'progress': {
            'stage': progress.get('stage', 'collecting'),
            'message': progress.get('message', ''),
            'percent': int(progress.get('percent') or 0),
            'checkpoint': progress.get('checkpoint'),
        },
    }
