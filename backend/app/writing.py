import re
from dataclasses import dataclass, field
from pathlib import Path

from app.analysis import verbatim_quote


BODY_FILES = {
    'A': '综述初稿.md',
    'A_DIALOGUE': '综述初稿.md',
    'B': '综述初稿.md',
    'C1': 'C1_引言.md',
    'C2': 'C2_文献综述.md',
    'D': '调研初稿.md',
    'E': '综述初稿.md',
}

TEMPLATE_FILES = {
    'A': 'A_调研报告骨架.md',
    'A_DIALOGUE': 'A_对话选题骨架.md',
    'B': 'B_立项依据骨架.md',
    'C1': 'C1_引言段落卡骨架.md',
    'C2': 'C2_文献综述骨架.md',
    'D': 'D_主题调研骨架.md',
    'E': 'A_调研报告骨架.md',
}
DEFAULT_TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'templates'

DIALOGUE_CATEGORIES = [
    '理论创新型选题',
    '方法创新型选题',
    '研究对象拓展型选题',
    '数据与实证创新型选题',
    '机制解释型选题',
    '前沿交叉型选题',
    '应用需求驱动型选题',
]

OUTLINE_HEADINGS = {
    'A': ['背景与领域格局', '研究现状与演变', '分歧与争议', '研究空白', '趋势', '可做方向与排序'],
    'A_DIALOGUE': ['领域格局与 5–8 条要点', '七类方向选题（每类两个槽位）', '综合第 1 推荐', '代表文献'],
    'B': ['项目名称与目标', '背景与重大需求', '按技术路线组织的进展', '关键不足', '关键科学问题', '研究内容与技术路线', '创新对应与可行性', '预期成果', '六段论证链'],
    'C1': ['引言逻辑框架', '段落卡', 'Research Gap 分析表', '完整引言', '写作逻辑和学术质量检查'],
    'C2': ['研究范围与检索策略', '分类框架', '综合分析', '文献比较表', '研究空白分析表', '未来方向', '完整综述'],
    'D': ['背景与科学问题', '检索概况', '研究进展', '方法对比', '代表作精读', '研究不足', '趋势', '选题排序', '总结与讨论问题'],
    'E': ['按用户用途定制的提纲'],
}


class WritingInputError(ValueError):
    pass


@dataclass
class WritingEvent:
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass
class WritingTask:
    id: str
    mode: str
    direction: str
    papers: list
    component_data: dict = None
    analysis: dict = field(default_factory=dict)
    search_overview: dict = field(default_factory=dict)
    project: dict = field(default_factory=dict)
    user_results: str = ''
    target_journal: str = ''
    team_context: str = ''
    events: list = field(default_factory=list)


@dataclass
class ComponentOutput:
    mode: str
    data: dict
    markdown: str
    evidence: list
    has_user_results: bool = False

    @property
    def c2(self):
        if self.mode != 'C2':
            return ''
        if self.has_user_results:
            return self.markdown
        return self.markdown + '\n\n比较表模板：无本文结果时只比较文献，不填写或虚构本文发现。'


@dataclass
class OutlineSample:
    outline: str
    sample: str


@dataclass
class BodyOutput:
    text: str
    evidence: list


@dataclass
class WritingOutput:
    components: ComponentOutput
    outline: str
    sample: str
    body: str
    body_path: Path
    evidence: list


class EvidenceAuditor:
    def __init__(self, papers):
        self.papers = {paper.get('ref_no'): paper for paper in papers}
        self.seen = set()

    def audit_items(self, items):
        records = []
        for item in items:
            if not isinstance(item, dict):
                raise WritingInputError('evidence entries must be objects')
            claim = str(item.get('claim') or '').strip()
            refs = item.get('refs') or []
            quotes = item.get('quotes') or {}
            if not claim or not isinstance(refs, list) or not refs:
                raise WritingInputError('evidence requires a claim and at least one reference')
            for ref in refs:
                paper = self.papers.get(ref)
                abstract = str((paper or {}).get('abstract') or '')
                if paper is None or paper.get('claim_eligible') is False or not abstract.strip():
                    raise WritingInputError(f'reference {ref} is not claim-eligible')
                quote = quotes.get(str(ref), quotes.get(ref))
                if not verbatim_quote(abstract, quote):
                    raise WritingInputError(f'evidence quote for reference {ref} is not in the abstract')
                key = (claim, ref, ' '.join(quote.split()))
                if key in self.seen:
                    continue
                self.seen.add(key)
                records.append({
                    'claim': claim,
                    'ref': ref,
                    'quote': quote,
                    'level': paper.get('evidence_level') or 'B',
                })
        return records

    def audit_data(self, value):
        records = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'evidence' and isinstance(item, list):
                    records.extend(self.audit_items(item))
                else:
                    records.extend(self.audit_data(item))
        elif isinstance(value, list):
            for item in value:
                records.extend(self.audit_data(item))
        return records


def _refs(refs):
    return ''.join(f'[{ref}]' for ref in dict.fromkeys(refs))


def _evidence_refs(items):
    return _refs([ref for item in items for ref in item.get('refs', [])])


def _render_a_direction(direction):
    rank = direction.get('rank')
    marker = f'第 {rank} 推荐' if rank != 3 else f'储备方向（第 {rank} 推荐）'
    lines = [
        f"### 方向卡·{direction['title']}｜{marker}",
        f"- 核心研究问题：{direction['core_question']}",
        f"- 数据可得性：{direction['data_availability']}",
        f"- 研究价值：{direction['research_value']}",
        f"- 可行性：{direction['feasibility']}",
        f"- 创新潜力：{direction['innovation_potential']}",
        f"- 实施难度：{direction['implementation_difficulty']}",
        f"- 主要风险：{direction['risk']}",
    ]
    if direction.get('first_reason'):
        lines.append(f"- 第 1 推荐理由：{direction['first_reason']}")
    return '\n'.join(lines)


def _render_dialogue_slot(slot, index):
    if slot.get('recommended') is False:
        return f"### 选题 {index}｜未推荐\n- 具体原因：{slot.get('reason', '现有证据不足以形成非重复且可验证的选题。')}"
    return '\n'.join([
        f"### 选题 {index}｜类内第 {slot['rank']} 推荐：{slot['title']}",
        f"- 核心研究问题：{slot['core_question']}",
        f"- 文献依据与机会：{slot['opportunity']} {_evidence_refs(slot.get('evidence', []))}",
        f"- 数据可得性：{slot['data_availability']}",
        f"- 研究价值：{slot['research_value']}（分析）",
        f"- 可行性：{slot['feasibility']}（分析）",
        f"- 创新潜力：{slot['innovation_potential']}（分析）",
        f"- 实施难度：{slot['implementation_difficulty']}（分析）",
        f"- 主要风险：{slot['risk']}",
    ])


def _render_a_dialogue(data):
    lines = ['# 模式 A 仅对话构件', '', '## 领域格局速览表', '', '| 方向 | 池内篇数/占比 | 团队与期刊口径 |', '|---|---|---|']
    for row in data['landscape']:
        lines.append(f"| {row['direction']} | {row['share']} {_refs(row.get('paper_refs', []))} | {row.get('venues', '未统计')} |")
    lines.extend(['', '## 研究空白与要点', '', '| 研究空白 | 机制/数据/方法/需求理由 | 文献证据 |', '|---|---|---|'])
    for row in data['gaps']:
        lines.append(f"| {row['gap']} | {row['reason']} | {_evidence_refs(row['evidence'])} |")
    for category_index, group in enumerate(data['topic_groups'], 1):
        lines.extend(['', f"## {category_index}. {group['category']}", ''])
        for index, slot in enumerate(group['slots'], 1):
            lines.extend([_render_dialogue_slot(slot, index), ''])
    first = data['overall_first']
    lines.extend([
        '## 综合第 1 推荐', '',
        f"推荐选题：{first['topic']} {_evidence_refs(first.get('evidence', []))}",
        f"推荐理由：{first['reason']}",
        f"主要风险：{first['risk']}",
    ])
    return '\n'.join(lines).strip()


def _render_a(data):
    lines = ['# 模式 A 构件', '', '## 领域格局速览表', '', '| 方向 | 池内篇数/占比 | 团队与期刊口径 |', '|---|---|---|']
    for row in data['landscape']:
        lines.append(f"| {row['direction']} | {row['share']} {_refs(row.get('paper_refs', []))} | {row.get('venues', '未统计')} |")
    lines.extend(['', '## 空白证据表', '', '| 研究空白 | 机制/数据/方法/需求理由 | 文献证据 |', '|---|---|---|'])
    for row in data['gaps']:
        lines.append(f"| {row['gap']} | {row['reason']} | {_evidence_refs(row['evidence'])} |")
    lines.append('')
    for direction in data['directions']:
        lines.extend([_render_a_direction(direction), ''])
    return '\n'.join(lines).strip()


def _render_b(task, data):
    project = task.project
    lines = [
        '# 模式 B 构件', '',
        f"项目名称：{project['name']}",
        f"资助类别/学科属性：{project.get('funding', '未指定')}",
        f"一句话目标：{project['goal']}", '',
        '## 刚性需求段', '',
        f"{data['demand']['text']} {_evidence_refs(data['demand']['evidence'])}", '',
        '## 已有研究对本项目技术路线的支撑', '',
        '| 资产 | 对应研究内容 | 文献证据 |', '|---|---|---|',
    ]
    for row in data['assets']:
        lines.append(f"| {row['name']} | {row['research_content']} | {_evidence_refs(row['evidence'])} |")
    lines.extend(['', '## 不足↔科学问题↔研究内容一一对解表', '', '| 不足 | 科学问题 | 研究内容 | 文献证据 |', '|---|---|---|---|'])
    for row in data['mappings']:
        lines.append(f"| {row['limitation']} | {row['scientific_question']} | {row['research_content']} | {_evidence_refs(row['evidence'])} |")
    lines.extend(['', '## 六段论证链', ''])
    for name in ('研究需求', '已有进展', '现有不足', '关键科学问题', '项目切入点', '预期贡献'):
        row = data['chain'][name]
        lines.append(f"### {name}\n{row['text']} {_evidence_refs(row['evidence'])}\n")
    lines.extend(['## 研究内容与技术路线', ''])
    lines.extend(f"- {item}" for item in project['research_contents'])
    lines.extend([f"- 技术路线：{project['technical_route']}", f"- 可行性：{project['feasibility']}", f"- 预期成果：{project['expected_outcomes']}", '', '## 创新点与已有工作差异表', '', '| 创新点 | 与已有工作的差异 | 文献证据 |', '|---|---|---|'])
    for row in data['innovations']:
        lines.append(f"| {row['innovation']} | {row['difference']} | {_evidence_refs(row['evidence'])} |")
    return '\n'.join(lines).strip()


def _render_c1_card(card):
    return f"### 段落卡·{card['function']}\n- 核心论点：{card['claim']} {_evidence_refs(card['evidence'])}"


def _render_c1(data):
    lines = ['# 模式 C1 构件', '', '## 引言逻辑框架与段落卡', '']
    for card in data['paragraph_cards']:
        lines.extend([_render_c1_card(card), ''])
    lines.extend(['## Research Gap 分析表', '', '| 具体不足 | 文献证据 | 本文回应 |', '|---|---|---|'])
    for row in data['gaps']:
        lines.append(f"| {row['gap']} | {_evidence_refs(row['evidence'])} | {row['response']} |")
    return '\n'.join(lines).strip()


def _render_c2(data):
    lines = ['# 模式 C2 构件', '', '## 分类框架', '']
    lines.extend(f"- {item}" for item in data['classification'])
    lines.extend(['', '## 文献比较表', '', '| 文献 | 研究问题 | 数据 | 核心方法 | 主要发现 | 局限性 |', '|---|---|---|---|---|---|'])
    for row in data['comparison']:
        lines.append(f"| {row['literature']} | {row['research_question']} | {row['data']} | {row['method']} | {row['findings']} | {row['limitation']} |")
    lines.extend(['', '## 研究空白分析表', '', '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 可深入研究的问题 |', '|---|---|---|---|---|'])
    for row in data['gaps']:
        lines.append(f"| {row['direction']} | {row['progress']} | {row['limitation']} | {row['evidence_text']} | {row['future_question']} |")
    return '\n'.join(lines).strip()


def _render_search_overview(overview):
    databases = '、'.join(overview.get('databases', [])) or '未记录'
    queries = '；'.join(overview.get('queries', [])) or '未记录'
    return f"检索数据库：{databases}；检索式：{queries}；限定起始年：{overview.get('from_year', '不限')}；写作池：{overview.get('pool_count', 0)} 篇。"


def _render_reading_card(card):
    return '\n'.join([
        f"### 精读页·[{card['ref']}] {card['title']}",
        f"- 选篇理由：{card['reason']}",
        f"- 研究问题：{card['research_question']}",
        f"- 数据：{card['data']}",
        f"- 方法：{card['method']}",
        f"- 主要发现：{card['findings']}",
        f"- 局限：{card['limitations']}",
        f"- 对团队研究的启发：{card['team_relevance']}",
        f"- 阅读深度：{card['reading_depth']}",
    ])


def _render_d(task, data):
    lines = ['# 模式 D 构件', '', '## 检索概况', '', _render_search_overview(task.search_overview), '', '## 研究进展', '']
    for row in data['progress']:
        lines.append(f"- {row['direction']}：{row['summary']}")
    lines.extend(['', '## 方法对比表', '', '| 数据获取方法族 | 具体技术 | 数据 | 优势 | 局限 | 文献 |', '|---|---|---|---|---|---|'])
    for row in data['method_comparison']:
        lines.append(f"| {row['family']} | {row['technique']} | {row['data']} | {row['strength']} | {row['limitation']} | {_refs(row['refs'])} |")
    lines.append('')
    for card in data['reading_cards']:
        lines.extend([_render_reading_card(card), ''])
    lines.extend(['## 选题排序', ''])
    for row in data['ranking']:
        lines.append(f"- 第 {row['rank']} 推荐：{row['topic']}；理由：{row['reason']}；主要风险：{row['risk']}")
    lines.extend(['', '## 组会讨论问题', ''])
    lines.extend(f"- {question}" for question in data['discussion_questions'])
    return '\n'.join(lines).strip()


def _b_sample(task, data):
    lines = ['# 样章：刚性需求段与对解表', '', f"项目名称：{task.project['name']}", '', '## 刚性需求段', '', f"{data['demand']['text']} {_evidence_refs(data['demand']['evidence'])}", '', '## 不足↔科学问题↔研究内容一一对解表', '', '| 不足 | 科学问题 | 研究内容 | 文献证据 |', '|---|---|---|---|']
    for row in data['mappings']:
        lines.append(f"| {row['limitation']} | {row['scientific_question']} | {row['research_content']} | {_evidence_refs(row['evidence'])} |")
    return '\n'.join(lines)


def _c2_sample(data):
    comparison = data['comparison'][0]
    gap = data['gaps'][0]
    return '\n'.join([
        '# 样章：文献比较与差异分析', '',
        '| 文献 | 研究问题 | 数据 | 核心方法 | 主要发现 | 局限性 |',
        '|---|---|---|---|---|---|',
        f"| {comparison['literature']} | {comparison['research_question']} | {comparison['data']} | {comparison['method']} | {comparison['findings']} | {comparison['limitation']} |",
        '',
        f"差异分析：{gap['direction']}已有进展体现为{gap['progress']}，但{gap['limitation']} {gap['evidence_text']}；可深入研究的问题是{gap['future_question']}",
    ])


def _validate_component_shape(task, mode):
    data = task.component_data
    if mode == 'A_DIALOGUE':
        if not 3 <= len(data.get('gaps', [])) <= 5:
            raise WritingInputError('mode A_DIALOGUE requires 3–5 gap evidence rows')
        groups = data.get('topic_groups', [])
        if [group.get('category') for group in groups] != DIALOGUE_CATEGORIES:
            raise WritingInputError('mode A_DIALOGUE requires the seven ordered categories')
        for group in groups:
            if len(group.get('slots', [])) != 2:
                raise WritingInputError('each A_DIALOGUE category requires two slots')
            for slot in group['slots']:
                if slot.get('recommended') is False:
                    continue
                required = {
                    'title', 'core_question', 'data_availability', 'research_value',
                    'feasibility', 'innovation_potential', 'implementation_difficulty',
                    'rank', 'opportunity', 'risk',
                }
                if required - set(slot):
                    raise WritingInputError('A_DIALOGUE topic slot is missing required fields')
    elif mode == 'A':
        if not 3 <= len(data.get('directions', [])) <= 5:
            raise WritingInputError('mode A requires 3–5 direction cards')
        if not 3 <= len(data.get('gaps', [])) <= 5:
            raise WritingInputError('mode A requires 3–5 gap evidence rows')
    elif mode == 'B':
        required = {'研究需求', '已有进展', '现有不足', '关键科学问题', '项目切入点', '预期贡献'}
        if set(data.get('chain', {})) != required:
            raise WritingInputError('mode B requires a complete six-link chain')
    elif mode == 'C1':
        if not 4 <= len(data.get('paragraph_cards', [])) <= 6:
            raise WritingInputError('mode C1 requires 4–6 paragraph cards')
    elif mode == 'D':
        if not 3 <= len(data.get('reading_cards', [])) <= 5:
            raise WritingInputError('mode D requires 3–5 reading cards')


def _citation_refs(text):
    return {int(ref) for ref in re.findall(r'\[(\d+)\]', text)}


def _validate_citation_coverage(text, evidence):
    available = {item['ref'] for item in evidence}
    missing = sorted(_citation_refs(text) - available)
    if missing:
        raise WritingInputError(f'citation {missing[0]} has no evidence ledger entry')


def _label_abstract_citations(text, evidence):
    levels = {}
    for item in evidence:
        levels.setdefault(item['ref'], set()).add(item['level'])

    def replace(match):
        following = text[match.end():]
        if following.startswith(('（据摘要）', '（部分据摘要）')):
            return match.group(0)
        refs = [int(ref) for ref in re.findall(r'\[(\d+)\]', match.group(0))]
        cited_levels = {level for ref in refs for level in levels.get(ref, set())}
        if 'B' not in cited_levels:
            return match.group(0)
        label = '（部分据摘要）' if cited_levels - {'B'} else '（据摘要）'
        return match.group(0) + label

    return re.sub(r'(?:\[\d+\])+', replace, text)


class WritingService:
    def __init__(self, workspace_root, model=None, template_root=None, template_overrides=None):
        self.workspace_root = Path(workspace_root)
        self.model = model
        self.template_root = Path(template_root) if template_root is not None else DEFAULT_TEMPLATE_ROOT
        self.template_overrides = template_overrides

    def _mode_template(self, mode):
        if self.template_overrides is not None:
            try:
                return self.template_overrides[mode]
            except KeyError as error:
                raise WritingInputError(f'pinned mode template is unavailable: {mode}') from error
        path = self.template_root / TEMPLATE_FILES[mode]
        try:
            return path.read_text(encoding='utf-8')
        except OSError as error:
            raise WritingInputError(f'mode template is unavailable: {path.name}') from error

    def _generate_components(self, task):
        if self.model is None:
            raise WritingInputError('component data or a component model is required')
        response = self.model.complete_json(
            '你是科研写作构件生成器。只使用输入摘要，所有文献事实必须附 refs 和逐字摘要 quotes；不得虚构研究空白、项目基础或用户结果。按指定模式返回 JSON 对象 {"components": ...}。',
            {
                'stage': 'components',
                'mode': task.mode,
                'mode_template': self._mode_template(task.mode.upper()),
                'direction': task.direction,
                'papers': task.papers,
                'analysis': task.analysis,
                'search_overview': task.search_overview,
                'project': task.project,
                'user_results': task.user_results,
                'team_context': task.team_context,
            },
        )
        if not isinstance(response, dict) or not isinstance(response.get('components'), dict):
            raise WritingInputError('component model must return a components object')
        return response['components']

    def produce_components(self, task):
        mode = task.mode.upper()
        if mode not in OUTLINE_HEADINGS:
            raise WritingInputError(f'unsupported writing mode: {task.mode}')
        if task.component_data is None:
            task.component_data = self._generate_components(task)
        _validate_component_shape(task, mode)
        auditor = EvidenceAuditor(task.papers)
        evidence = auditor.audit_data(task.component_data)
        if mode == 'A_DIALOGUE':
            markdown = _render_a_dialogue(task.component_data)
        elif mode == 'A':
            markdown = _render_a(task.component_data)
        elif mode == 'B':
            markdown = _render_b(task, task.component_data)
        elif mode == 'C1':
            markdown = _render_c1(task.component_data)
        elif mode == 'C2':
            markdown = _render_c2(task.component_data)
        elif mode == 'D':
            markdown = _render_d(task, task.component_data)
        else:
            markdown = str(task.component_data.get('markdown') or '')
        _validate_citation_coverage(markdown, evidence)
        markdown = _label_abstract_citations(markdown, evidence)
        return ComponentOutput(
            mode=mode,
            data=task.component_data,
            markdown=markdown,
            evidence=evidence,
            has_user_results=bool(str(task.user_results or '').strip()),
        )

    def produce_outline_and_sample(self, task, components):
        headings = '\n'.join(f'{index}. {heading}' for index, heading in enumerate(OUTLINE_HEADINGS[components.mode], 1))
        outline = f"# {task.direction}｜模式 {components.mode} 提纲\n\n{headings}\n\n## 构件与证据索引\n\n{components.markdown}"
        if components.mode == 'A_DIALOGUE':
            sample = '# 样章：七类双选题之完整选题卡\n\n' + _render_dialogue_slot(components.data['topic_groups'][0]['slots'][0], 1)
        elif components.mode == 'A':
            sample = '# 样章：方向卡\n\n' + _render_a_direction(components.data['directions'][0])
        elif components.mode == 'B':
            sample = _b_sample(task, components.data)
        elif components.mode == 'C1':
            sample = '# 样章：完整段落卡\n\n' + _render_c1_card(components.data['paragraph_cards'][0])
        elif components.mode == 'C2':
            sample = _c2_sample(components.data)
        elif components.mode == 'D':
            sample = '# 样章：检索概况与精读页\n\n## 检索概况\n\n' + _render_search_overview(task.search_overview) + '\n\n' + _render_reading_card(components.data['reading_cards'][0])
        else:
            sample = str(components.data.get('sample') or '')
        _validate_citation_coverage(sample, components.evidence)
        outline = _label_abstract_citations(outline, components.evidence)
        sample = _label_abstract_citations(sample, components.evidence)
        return OutlineSample(outline=outline, sample=sample)

    def write_body(self, task, components, outline_sample, body_writer):
        if body_writer is None and self.model is not None:
            def body_writer(context):
                response = self.model.complete_json(
                    '你是科研正文写作器。先读已完成的构件、提纲和样章，再写连贯正文。每个文献事实必须在 evidence 中给出 refs 与逐字摘要 quotes；分析判断标明“分析”，不得虚构用户结果、全文细节或参考文献。',
                    {
                        'stage': 'body',
                        'mode': task.mode,
                        'mode_template': self._mode_template(task.mode.upper()),
                        'direction': task.direction,
                        'components': components.data,
                        'outline': outline_sample.outline,
                        'sample': outline_sample.sample,
                        'papers': task.papers,
                        'analysis': task.analysis,
                        'project': task.project,
                        'user_results': task.user_results,
                        'team_context': task.team_context,
                    },
                )
                if isinstance(response, dict) and isinstance(response.get('body'), str):
                    return {'text': response['body'], 'evidence': response.get('evidence') or []}
                return response
        if body_writer is None:
            raise WritingInputError('a body composer is required; no prose was fabricated')
        result = body_writer({
            'task': task,
            'components': components,
            'outline': outline_sample.outline,
            'sample': outline_sample.sample,
        })
        if not isinstance(result, dict) or not isinstance(result.get('text'), str):
            raise WritingInputError('body composer must return text and evidence')
        auditor = EvidenceAuditor(task.papers)
        evidence = auditor.audit_items(result.get('evidence') or [])
        text = result['text']
        _validate_citation_coverage(text, evidence)
        text = _label_abstract_citations(text, evidence)
        return BodyOutput(text=text, evidence=evidence)

    def produce(self, task, body_writer=None):
        components = self.produce_components(task)
        task_dir = self.workspace_root / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / 'components.md').write_text(components.markdown, encoding='utf-8')
        task.events.append(WritingEvent(kind='components_ready'))

        outline_sample = self.produce_outline_and_sample(task, components)
        (task_dir / 'outline.md').write_text(outline_sample.outline, encoding='utf-8')
        task.events.append(WritingEvent(kind='outline_ready'))
        (task_dir / 'sample.md').write_text(outline_sample.sample, encoding='utf-8')
        task.events.append(WritingEvent(kind='sample_ready'))

        body = self.write_body(task, components, outline_sample, body_writer)
        body_path = task_dir / BODY_FILES[components.mode]
        body_path.write_text(body.text, encoding='utf-8')
        evidence = components.evidence + body.evidence
        ledger = ['| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |', '|---|---|---|---|']
        seen = set()
        for item in evidence:
            key = (item['claim'], item['ref'], item['quote'])
            if key in seen:
                continue
            seen.add(key)
            claim = item['claim'].replace('|', '\\|')
            quote = item['quote'].replace('|', '\\|')
            ledger.append(f"| {claim} | {item['ref']} | {quote} | {item['level']} |")
        (task_dir / 'evidence_ledger.md').write_text('\n'.join(ledger) + '\n', encoding='utf-8')
        task.events.append(WritingEvent(kind='body_ready'))
        return WritingOutput(
            components=components,
            outline=outline_sample.outline,
            sample=outline_sample.sample,
            body=body.text,
            body_path=body_path,
            evidence=evidence,
        )
