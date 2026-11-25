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
        'custom': {'label': '研究方向或核心问题', 'placeholder': '例如：城市内涝对地下车库财产损失的影响评估'},
        'options': [
            _option('肝癌免疫治疗耐药机制的最新进展', '肝癌免疫治疗耐药机制的最新进展', '医学·机制现状类', '也可直接输入自己的方向'),
            _option('城市内涝对地下车库财产损失的影响评估', '城市内涝对地下车库财产损失的影响评估', '城建防灾·影响评估类', '也可直接输入自己的方向'),
            _option('大语言模型在材料科学实验设计中的应用', '大语言模型在材料科学实验设计中的应用', 'AI×新领域·技术方向类', '也可直接输入自己的方向'),
            _option('课后服务参与对中小学生学业成效的影响', '课后服务参与对中小学生学业成效的影响', '教育·干预效果类', '也可直接输入自己的方向'),
        ],
    }


def _mode_card():
    return {
        'id': 'mode',
        'eyebrow': '用途确认',
        'title': '这次洞察用来做什么？',
        'description': '选择最贴近当前目标的一项。',
        'options': [
            _option('A', 'A 选题立项前摸底', '领域全景、研究空白与可做方向', '选题立项前摸底'),
            _option('B', 'B 撰写标书/立项依据', '组织项目论证链与立项素材', '标书与立项依据'),
            _option('C', 'C 撰写论文引言与讨论', '分别组织 C1 引言与 C2 文献综述素材', '论文写作'),
            _option('D', 'D 组会或团队学习', '系统调研、方法比较与代表作精读', '组会主题调研'),
        ],
        'conditional_fields': {
            'B': [
                {'name': 'name', 'label': '项目名称', 'group': 'project', 'required': True},
                {'name': 'goal', 'label': '一句话目标', 'group': 'project', 'required': True},
                {'name': 'funding', 'label': '资助类别/学科属性（可跳过）', 'group': 'project'},
                {'name': 'research_contents', 'label': '研究内容（3–4 项）', 'group': 'project', 'kind': 'textarea', 'required': True},
                {'name': 'technical_route', 'label': '技术路线（输入→方法→验证→输出）', 'group': 'project', 'required': True},
                {'name': 'feasibility', 'label': '可行性（数据/工具/团队/预实验）', 'group': 'project', 'kind': 'textarea', 'required': True},
                {'name': 'expected_outcomes', 'label': '预期成果', 'group': 'project', 'kind': 'textarea', 'required': True},
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
                {'name': 'user_results', 'label': '本文信息', 'placeholder': '核心研究问题、拟用方法、结果与预期创新（可跳过）', 'kind': 'textarea'},
                {'name': 'target_journal', 'label': '目标期刊（可跳过）', 'placeholder': '输入目标期刊'},
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
        options[0]['label'] += '（推荐）'
    else:
        recommended = {'A': 3, 'B': 3, 'C': 1}.get(mode, 3)
        options[recommended]['label'] += '（推荐）'
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
    options = [
        _option('A', 'A 正式调研报告（Word，含文献依据）', '带参考文献与复核边界的 Word 报告', 'Word'),
        _option('B', 'B 仅对话中给要点和代表文献', '5–8 条要点与不超过 10 篇代表文献', '对话'),
        _option('C', 'C 展示 PPT', '8–12 页；D 模式为 20–30 页组会汇报', 'PPT'),
    ]
    if mode == 'D':
        options = [options[2], options[0], options[1]]
    elif mode == 'A':
        options = [options[1], options[0], options[2]]
    return {
        'id': 'delivery',
        'eyebrow': '交付形式确认',
        'title': '希望得到的交付形式',
        'description': '这是最后一问；答完后直接生成，不再插入确认。',
        'options': options,
    }


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
            'checkpoint': progress.get('checkpoint'),
        },
    }
