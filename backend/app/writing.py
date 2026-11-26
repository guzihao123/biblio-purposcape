import re
from dataclasses import dataclass, field
from pathlib import Path

from app.analysis import verbatim_quote
from app.progress_reporter import report_stage_phase


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

_EVIDENCE_SHAPE = 'EVIDENCE={"claim":"论断","refs":[论文 ref_no],"quotes":{"<ref_no>":"摘要逐字原句"}}'
_COMPONENT_EVIDENCE_NOTE = '；evidence 必须是 EVIDENCE 列表，' + _EVIDENCE_SHAPE

B_SYSTEM_GENERATED_PLACEHOLDER = '（由系统根据项目主题与文献生成，见正文）'
B_PROJECT_GENERATION_RULE = (
    'B 模式用户只提供项目名称、一句话目标与资助类别/学科属性；'
    '研究内容（3–4 项）、技术路线（输入→方法→验证→输出）、可行性（数据/工具/预实验）、预期成果'
    '必须由你基于项目主题与本次论文池生成实质内容，不得留空、不得只写占位符或复述用户输入。'
    'project.theme 中给出的研究对象、方法与预期产出是本次项目主题的组成部分，研究内容与技术路线必须与之对应。'
    'B 正文必须完整保留「研究内容（3–4 项）」「技术路线」「可行性」「预期成果」章节。'
)
B_DRAFT_RULE = (
    'B 模式若提供 project_draft，草稿是项目论证的分析依据：逐项核对草稿的研究内容、技术路线、可行性与预期成果'
    '是否得到本次论文/材料证据支撑；在「关键不足」或「创新对应与可行性」章节内增加一段'
    '“草稿支撑度与修改建议”，指出证据缺口和具体修改方向。不得把草稿内容当作已证实事实，'
    '不得虚构评审意见、预实验或团队基础；未提供 project_draft 时按项目主题正常生成。'
)
B_MATERIAL_RULE = (
    'B 模式非论文材料按 [M] 分通道著录：只能使用 materials 与 material_index 中给出的逐字摘录支撑'
    '政策/报告/统计事实；正文引用写成「（据材料 M1）」，不得把 [M] 写成论文 [n] 编号，'
    '不得把材料摘录写进 evidence 台账；未提供材料时不得编造政策/报告/统计内容，也不得写（据材料 M…）。'
)
_MATERIAL_CITATION_RE = re.compile(r'（据材料\s*M(\d+)）')
E_CUSTOM_PURPOSE_RULE = (
    'E 模式是用户自定义用途：custom_purpose 是本次写作的唯一用途依据，必须先把用途转成可核对的写作要求并逐条落实。'
    '同时保留 E 基线形态：综述初稿 + 空白点清单 + 3 个可做方向；'
    '用户用途无法在现有证据下实现时，在正文中说明原因并给出最接近的替代，不得虚构结论或交付物。'
)

LENGTH_TARGETS = {
    'A': '1500-2500',
    'A_DIALOGUE': '1500-2500',
    'B': '2000-3000',
    'C1': '800-1200',
    'C2': '800-1200',
    'D': '3000-6000',
    'E': '1500-2500',
}

FORMAT_RULES = {
    'A': '研究空白证据表每行必须以「空白1：」「空白2：」…开头，并在同一行写 [n] 引用与理由类型；方向卡保留「第 N 推荐」「核心研究问题」「数据可得性」。',
    'A_DIALOGUE': '每类选题的两张卡与综合第 1 推荐必须保留推荐理由与主要风险。',
    'E': '先用「## 用途落实」逐条说明如何落实 custom_purpose，再给综述要点、空白点清单与 3 个可做方向；空白证据与引用要求同 A 基线。',
}

STYLE_REFERENCE_FILE = '写法参考卡.md'
C1_SKIP_RULE = (
    'C 模式 c_info_route=skip：研究空白必须根据池内文献逐行实写并附 [n] 证据；'
    '只有“研究思路与方法”“研究贡献”两张段落卡和完整引言第 4/5 段允许写占位，'
    '不得把研究空白、文献比较或未来方向写成占位，也不得虚构本文结果。'
)
C1_MATERIAL_RULE = (
    'C 模式 c_info_route=upload/oral：从 user_material 提取本文研究问题、方法与预期创新，'
    '用于 Research Gap 的“本文回应”、第 4/5 段与贡献句；'
    '本文材料只作为用户自述，不产生 [n]，不冒充外部文献证据或全文事实。'
)
C2_SKIP_RULE = (
    'C 模式 c_info_route=skip：C2 不要求本文结果；研究主题与检索范围、综合分析、技术路线比较、'
    '研究空白和未来方向必须按池内文献证据实写，不得留占位，也不得写成 Discussion。'
)
C2_MATERIAL_RULE = (
    'C 模式 c_info_route=upload/oral：本文材料只可在“未来研究方向”中呼应本文问题，'
    '不得进入文献比较表或研究空白分析表的文献证据列，不得为本文材料编造 [n] 引用。'
)
C1_STYLE_RULE = (
    '仅当用户提供 target_journal 时：读取 style_reference_note，按目标期刊学科定位调整引言口径；'
    '若参考卡已降级，明确写“按通用口径写”，不得抄写任何范文原句或虚构范文结构。'
)

COMPONENT_SCHEMAS = {
    'A': (
        '{"landscape":[{"direction":"…","share":"篇数/占比","paper_refs":[1],"venues":"团队/期刊口径"}],'
        '"gaps":[{"gap":"…","reason":"机制/数据/方法/需求型理由","evidence":[EVIDENCE]}],'
        '"directions":[{"rank":1,"title":"…","core_question":"…","data_availability":"…",'
        '"research_value":"…","feasibility":"…","innovation_potential":"…",'
        '"implementation_difficulty":"…","risk":"…","first_reason":"第 1 推荐必填，其余可为空串",'
        '"evidence":[EVIDENCE]}]}；gaps 3–5 行；directions 3–5 张且 rank 从 1 连续编号'
        + _COMPONENT_EVIDENCE_NOTE
    ),
    'A_DIALOGUE': (
        '{"landscape":[{"direction":"…","share":"篇数/占比","paper_refs":[1],"venues":"…"}],'
        '"gaps":[{"gap":"…","reason":"…","evidence":[EVIDENCE]}],'
        '"topic_groups":[{"category":"理论创新型选题","slots":[SLOT,SLOT]},'
        '{"category":"方法创新型选题","slots":[SLOT,SLOT]},'
        '{"category":"研究对象拓展型选题","slots":[SLOT,SLOT]},'
        '{"category":"数据与实证创新型选题","slots":[SLOT,SLOT]},'
        '{"category":"机制解释型选题","slots":[SLOT,SLOT]},'
        '{"category":"前沿交叉型选题","slots":[SLOT,SLOT]},'
        '{"category":"应用需求驱动型选题","slots":[SLOT,SLOT]}],'
        '"overall_first":{"topic":"…","reason":"…","risk":"…","evidence":[EVIDENCE]}}；'
        '主题七类必须按上述顺序出现且每类恰好 2 个槽位；'
        'SLOT={"title":"…","core_question":"…","data_availability":"…","research_value":"…",'
        '"feasibility":"…","innovation_potential":"…","implementation_difficulty":"…",'
        '"rank":1,"opportunity":"…","risk":"…","evidence":[EVIDENCE]} 或 {"recommended":false,"reason":"…"}'
        + _COMPONENT_EVIDENCE_NOTE
    ),
    'B': (
        '{"demand":{"text":"…","evidence":[EVIDENCE]},'
        '"assets":[{"name":"…","research_content":"研究内容（1）","evidence":[EVIDENCE]}],'
        '"mappings":[{"limitation":"…","scientific_question":"…","research_content":"…","evidence":[EVIDENCE]}],'
        '"chain":{"研究需求":{"text":"…","evidence":[EVIDENCE]},"已有进展":{"text":"…","evidence":[EVIDENCE]},'
        '"现有不足":{"text":"…","evidence":[EVIDENCE]},"关键科学问题":{"text":"…","evidence":[EVIDENCE]},'
        '"项目切入点":{"text":"…","evidence":[EVIDENCE]},"预期贡献":{"text":"…","evidence":[EVIDENCE]}},'
        '"innovations":[{"innovation":"…","difference":"…","evidence":[EVIDENCE]}]}；chain 六个键必须原样齐全'
        + _COMPONENT_EVIDENCE_NOTE
    ),
    'C1': (
        '{"paragraph_cards":[{"function":"背景重要性","claim":"…","evidence":[EVIDENCE]}],'
        '"gaps":[{"gap":"…","evidence":[EVIDENCE],"response":"本文如何回应"}]}；'
        'paragraph_cards 4–6 张，function 依次覆盖背景重要性、研究进展、现有研究不足、研究思路与方法、研究贡献'
        + _COMPONENT_EVIDENCE_NOTE
    ),
    'C2': (
        '{"scope":{"topic":"…","objects":"…","time_range":"…","disciplines":"…","evidence_boundary":"…"},'
        '"keywords":[{"concept":"…","cn":"…","en_synonyms":"…","boolean":"…","use":"…"}],'
        '"search_strategy":{"databases":"只列实际接入并执行","queries":["实际检索式"],'
        '"tracing":"实际执行的追溯/追踪","screening":"实际筛选标准",'
        '"systematic_review":false,"prisma":false},'
        '"classification":["…"],'
        '"comparison":[{"literature":"[n] 作者 年","research_question":"…",'
        '"data":"…","method":"…","findings":"…","limitation":"…"}],'
        '"synthesis":[{"direction":"…","progress":"…","representative_methods":"…","scenarios":"…","limit":"…"}],'
        '"route_comparison":[{"route":"…","problem":"…","performance":"…","conditions":"…",'
        '"limitation":"…","complementarity":"…"}],'
        '"gaps":[{"direction":"…","progress":"…","limitation":"…","evidence_text":"[n] 摘要证据","future_question":"…"}],'
        '"future_directions":[{"direction":"…","basis":"…","question":"…"}]}；'
        'classification 按理论基础、研究对象、研究问题、技术方法、数据与实验、研究结论、研究局限七维给出；'
        'synthesis、route_comparison、future_directions 各至少 2 项且基于已有进展与不足；'
        '新增字段不得引入文献比较表与研究空白表之外的 [n]，引用只用可审计编号'
    ),
    'D': (
        '{"progress":[{"direction":"…","summary":"…"}],'
        '"method_comparison":[{"family":"数据获取方法族","technique":"具体技术","data":"…",'
        '"strength":"…","limitation":"…","refs":[1]}],'
        '"reading_cards":[{"ref":1,"title":"…","reason":"…","research_question":"…","data":"…",'
        '"method":"…","findings":"…","limitations":"…","team_relevance":"…","reading_depth":"仅摘要"}],'
        '"ranking":[{"rank":1,"topic":"…","reason":"…","risk":"…"}],'
        '"discussion_questions":["…"]}；reading_cards 3–5 张'
    ),
    'E': (
        '{"markdown":"按 custom_purpose 组织的 Markdown 构件（含 [n] 引用与证据）；'
        '至少覆盖综述要点、空白点清单与 3 个可做方向","evidence":[EVIDENCE]}'
        + _COMPONENT_EVIDENCE_NOTE
    ),
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
    c_info_route: str = ''
    target_journal: str = ''
    team_context: str = ''
    project_draft: str = ''
    project_input_path: str = 'direction'
    materials: list = field(default_factory=list)
    custom_purpose: str = ''
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
        refs = row.get('paper_refs', [])
        ref_text = '（篇号 {}）'.format('、'.join(str(ref) for ref in refs)) if refs else ''
        lines.append(f"| {row['direction']} | {row['share']} {ref_text} | {row.get('venues', '未统计')} |")
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
        refs = row.get('paper_refs', [])
        ref_text = '（篇号 {}）'.format('、'.join(str(ref) for ref in refs)) if refs else ''
        lines.append(f"| {row['direction']} | {row['share']} {ref_text} | {row.get('venues', '未统计')} |")
    lines.extend(['', '## 空白证据表', '', '| 研究空白 | 机制/数据/方法/需求理由 | 文献证据 |', '|---|---|---|'])
    for row in data['gaps']:
        lines.append(f"| {row['gap']} | {row['reason']} | {_evidence_refs(row['evidence'])} |")
    lines.append('')
    for direction in data['directions']:
        lines.extend([_render_a_direction(direction), ''])
    return '\n'.join(lines).strip()


def _render_material_index(materials):
    lines = ['## 非论文材料索引（[M] 与论文 [n] 分通道）', '']
    for item in materials:
        lines.append('- {} {}｜{}｜{}｜{}｜链接：{}'.format(
            item.get('citation', ''), item.get('title', ''), item.get('issuer', ''),
            item.get('document_number', ''), item.get('issued_at', ''),
            item.get('link') or '未提供',
        ))
        for excerpt in item.get('excerpts', [])[:3]:
            lines.append('  - 逐字摘录（{}）：{}'.format(excerpt.get('anchor', ''), excerpt.get('text', '')))
        if item.get('repost_note'):
            lines.append('  - 转载注明：{}'.format(item['repost_note']))
    lines.extend(['', '正文引用格式：（据材料 M1）；[M] 不进入 [n] 台账与 verify 检查。'])
    return '\n'.join(lines)


def _render_b(task, data):
    project = task.project
    theme = project.get('theme') if isinstance(project.get('theme'), dict) else {}
    lines = [
        '# 模式 B 构件', '',
        f"项目名称：{project['name']}",
        f"资助类别/学科属性：{project.get('funding', '未指定')}",
        f"一句话目标：{project['goal']}", '',
    ]
    if theme:
        lines.extend([
            '## 项目主题（用户选定）', '',
            f"- 研究对象：{theme.get('object') or '未提供'}",
            f"- 方法：{theme.get('method') or '未提供'}",
            f"- 预期产出：{theme.get('expected_output') or '未提供'}",
        ])
        if theme.get('custom'):
            lines.append(f"- 自定义补充：{theme['custom']}")
        lines.append('')
    lines.extend([
        '## 刚性需求段', '',
        f"{data['demand']['text']} {_evidence_refs(data['demand']['evidence'])}", '',
        '## 已有研究对本项目技术路线的支撑', '',
        '| 资产 | 对应研究内容 | 文献证据 |', '|---|---|---|',
    ])
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
    raw_contents = project.get('research_contents') or []
    if isinstance(raw_contents, str):
        raw_contents = re.split(r'[\n；;]+', raw_contents)
    research_contents = [str(item).strip() for item in raw_contents if str(item).strip()]
    if research_contents:
        lines.extend(f"- {item}" for item in research_contents)
    else:
        lines.append(f"- 研究内容：{B_SYSTEM_GENERATED_PLACEHOLDER}")
    for label, key in (
        ('技术路线', 'technical_route'),
        ('可行性', 'feasibility'),
        ('预期成果', 'expected_outcomes'),
    ):
        value = str(project.get(key) or '').strip()
        lines.append(f"- {label}：{value or B_SYSTEM_GENERATED_PLACEHOLDER}")
    lines.extend(['', '## 创新点与已有工作差异表', '', '| 创新点 | 与已有工作的差异 | 文献证据 |', '|---|---|---|'])
    for row in data['innovations']:
        lines.append(f"| {row['innovation']} | {row['difference']} | {_evidence_refs(row['evidence'])} |")
    materials = getattr(task, 'materials', None) or []
    if materials:
        lines.extend(['', _render_material_index(materials)])
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


def _render_c2(data, task=None):
    comparison = data.get('comparison') or []
    gaps = data.get('gaps') or []
    overview = getattr(task, 'search_overview', {}) or {}
    scope = data.get('scope') if isinstance(data.get('scope'), dict) else {}
    strategy = data.get('search_strategy') if isinstance(data.get('search_strategy'), dict) else {}

    time_label = f"{overview.get('from_year')} 起" if overview.get('from_year') else '不限起始年'
    boundary_label = (
        f"检索池 {overview.get('pool_count', 0)} 篇，摘要深度；未覆盖数据库见 search_log.md"
    )
    lines = ['# 模式 C2 构件', '', '## 研究主题与检索范围', '']
    lines.extend([
        f"- 综述主题与核心概念：{scope.get('topic') or getattr(task, 'direction', '') or '未记录'}",
        f"- 研究对象与应用场景：{scope.get('objects') or '按文献分类框架归纳'}",
        f"- 时间范围与学科范围：{scope.get('time_range') or time_label}；{scope.get('disciplines') or '学科范围见检索日志'}",
        f"- 检索时间、数据库、时间范围与筛选标准：{strategy.get('screening') or '按 search_log.md 实写'}",
        f"- 证据边界：{scope.get('evidence_boundary') or boundary_label}",
    ])

    lines.extend(['', '## 关键词和检索策略', '', '| 概念 | 中文词 | 英文词/同义词 | 组合与布尔逻辑 | 实际用途 |', '|---|---|---|---|---|'])
    keyword_rows = data.get('keywords') or []
    if not keyword_rows:
        keyword_rows = [
            {'concept': query, 'en_synonyms': query, 'boolean': '本次实际检索式见 search_log.md', 'use': '本次实际检索'}
            for query in (overview.get('queries') or [])
        ]
    if not keyword_rows:
        keyword_rows = [{'concept': '未记录', 'boolean': '未记录', 'use': '未记录'}]
    for row in keyword_rows:
        lines.append(
            f"| {row.get('concept', '')} | {row.get('cn', '')} | {row.get('en_synonyms', '')} | "
            f"{row.get('boolean', '')} | {row.get('use', '')} |"
        )
    databases = strategy.get('databases') or '、'.join(overview.get('databases') or []) or '未记录'
    queries = strategy.get('queries') or overview.get('queries') or []
    lines.extend([
        '', f"- 实际接入并执行的数据库：{databases}",
        f"- 实际检索式：{'；'.join(str(query) for query in queries) or '未记录'}",
        f"- 追溯与追踪：{strategy.get('tracing') or '仅记录本次实际执行的策略'}",
        f"- 系统综述声明：{'已执行（须与 search_log.md 记录一致）' if strategy.get('systematic_review') else '未声明系统综述，未执行 PRISMA'}；"
        f"PRISMA：{'已执行' if strategy.get('prisma') else '未执行'}",
    ])

    lines.extend(['', '## 文献分类框架', ''])
    lines.extend(f"- {item}" for item in (data.get('classification') or ['未记录分类']))
    lines.extend(['', '## 不同研究方向的综合分析', ''])
    synthesis = data.get('synthesis') or []
    if not synthesis:
        synthesis = [
            {
                'direction': row.get('research_question') or row.get('method') or '研究方向',
                'progress': row.get('findings', ''),
                'representative_methods': row.get('method', ''),
                'scenarios': '适用场景由文献比较表归纳，未取得全文的细节标未确认',
                'limit': row.get('limitation', ''),
            }
            for row in comparison[:4]
        ]
    if not synthesis:
        synthesis = [{'direction': '未记录研究方向', 'progress': '未记录', 'representative_methods': '未记录', 'scenarios': '未记录', 'limit': '未记录'}]
    for item in synthesis:
        lines.extend([
            f"### {item.get('direction', '未记录研究方向')}", '',
            f"- 发展过程与已有进展：{item.get('progress', '')}",
            f"- 代表性方法：{item.get('representative_methods', '')}",
            f"- 适用场景：{item.get('scenarios', '')}",
            f"- 局限：{item.get('limit', '')}", '',
        ])

    lines.extend(['## 主要技术路线比较', '', '| 技术路线 | 解决的问题 | 性能/适用条件 | 局限 | 互补或融合可能 |', '|---|---|---|---|---|'])
    route_rows = data.get('route_comparison') or []
    if not route_rows:
        route_rows = [
            {
                'route': row.get('method', '未记录路线'),
                'problem': row.get('research_question', ''),
                'performance': '摘要未报告可核对的性能指标，标未确认',
                'conditions': '适用条件由文献比较表归纳',
                'limitation': row.get('limitation', ''),
                'complementarity': '与其他路线的互补性见综合分析',
            }
            for row in comparison[:4]
        ]
    for row in route_rows:
        lines.append(
            f"| {row.get('route', '')} | {row.get('problem', '')} | {row.get('performance', '')} | "
            f"{row.get('limitation', '')} | {row.get('complementarity', '')} |"
        )

    lines.extend(['', '## 文献比较表', '', '| 文献 | 研究问题 | 数据 | 核心方法 | 主要发现 | 局限性 |', '|---|---|---|---|---|---|'])
    for row in comparison:
        lines.append(f"| {row['literature']} | {row['research_question']} | {row['data']} | {row['method']} | {row['findings']} | {row['limitation']} |")
    lines.extend(['', '## 研究空白分析表', '', '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 可深入研究的问题 |', '|---|---|---|---|---|'])
    for row in gaps:
        lines.append(f"| {row['direction']} | {row['progress']} | {row['limitation']} | {row['evidence_text']} | {row['future_question']} |")
    lines.extend(['', '## 未来研究方向', '', '| 方向 | 已有进展与不足依据 | 待研究问题 |', '|---|---|---|'])
    future_rows = data.get('future_directions') or []
    if not future_rows:
        future_rows = [
            {'direction': row.get('direction', ''), 'basis': f"{row.get('progress', '')}；{row.get('limitation', '')}", 'question': row.get('future_question', '')}
            for row in gaps
        ]
    for row in future_rows:
        lines.append(f"| {row.get('direction', '')} | {row.get('basis', '')} | {row.get('question', '')} |")
    lines.extend(['', '各方向均基于已有进展与不足归纳，不作脱离文献的主观预测。'])
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
    elif mode == 'C2':
        if not data.get('comparison') or not data.get('gaps'):
            raise WritingInputError('mode C2 requires comparison and gap rows')
        for key in ('keywords', 'synthesis', 'route_comparison', 'future_directions'):
            if key in data and not isinstance(data[key], list):
                raise WritingInputError(f'mode C2 {key} must be a list')
        for key in ('synthesis', 'route_comparison', 'future_directions'):
            if key in data and len(data[key]) < 2:
                raise WritingInputError(f'mode C2 requires at least two {key} rows')
    elif mode == 'D':
        if not 3 <= len(data.get('reading_cards', [])) <= 5:
            raise WritingInputError('mode D requires 3–5 reading cards')
    elif mode == 'E':
        if not str(data.get('markdown') or '').strip():
            raise WritingInputError('mode E requires a markdown component')


def _citation_refs(text):
    return {int(ref) for ref in re.findall(r'\[(\d+)\]', text)}


def _validate_citation_coverage(text, evidence):
    available = {item['ref'] for item in evidence}
    missing = sorted(_citation_refs(text) - available)
    if missing:
        raise WritingInputError(f'citation {missing[0]} has no evidence ledger entry')


def _strip_unsupported_citations(value, available):
    """Remove citation markers that have no audited evidence entry.

    The model occasionally cites a pool number in prose without emitting an
    evidence object for it. Retrying strict JSON is preferred; this repair is a
    last resort that preserves the prose but never invents a ledger entry.
    """
    available = {int(ref) for ref in available}
    removed = 0

    def clean(node):
        nonlocal removed
        if isinstance(node, dict):
            result = {}
            for key, child in node.items():
                if key == 'evidence':
                    result[key] = child
                elif key in {'refs', 'paper_refs'} and isinstance(child, list):
                    kept = []
                    for ref in child:
                        try:
                            normalized = int(ref)
                        except (TypeError, ValueError):
                            normalized = None
                        if normalized in available:
                            kept.append(normalized)
                        else:
                            removed += 1
                    result[key] = kept
                else:
                    result[key] = clean(child)
            return result
        if isinstance(node, list):
            return [clean(item) for item in node]
        if isinstance(node, str):
            def replace(match):
                nonlocal removed
                if int(match.group(1)) in available:
                    return match.group(0)
                removed += 1
                return ''
            return re.sub(r'\[(\d+)\]', replace, node)
        return node

    return clean(value), removed


def _validate_material_citations(text, materials):
    """[M] is a separate channel: validate only the explicit material marker."""
    if not materials:
        if _MATERIAL_CITATION_RE.search(text):
            raise WritingInputError('未提供非论文材料，不得写（据材料 M…）')
        return
    allowed = set()
    for item in materials:
        match = re.search(r'M(\d+)', str(item.get('citation', '')))
        if match:
            allowed.add(int(match.group(1)))
    used = {int(value) for value in _MATERIAL_CITATION_RE.findall(text)}
    if not used:
        raise WritingInputError('B 正文必须至少引用一条（据材料 M…）')
    missing = sorted(used - allowed)
    if missing:
        raise WritingInputError('material citation M{} has no accepted material'.format(missing[0]))


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


_MATERIAL_ALIASES = {
    '题目': '题目', '研究问题': '研究问题', '问题': '研究问题',
    '摘要': '摘要', '方法': '方法', '研究方法': '方法',
    '结果': '结果', '创新': '创新', '创新点': '创新', '预期创新': '创新',
}


def extract_user_material(text):
    """Parse a pasted draft or oral notes into the fields C1/C2 prompts need."""
    result = {name: '' for name in ('题目', '研究问题', '摘要', '方法', '结果', '创新')}
    current = None
    for raw_line in str(text or '').splitlines():
        line = raw_line.strip().lstrip('#*- ').strip()
        if not line:
            continue
        match = re.match(r'^(题目|研究问题|问题|摘要|方法|研究方法|结果|创新|创新点|预期创新)\s*[:：]\s*(.*)$', line)
        if match:
            current = _MATERIAL_ALIASES[match.group(1)]
            result[current] = match.group(2).strip()
        elif current:
            result[current] = (result[current] + '\n' + line).strip()
    if not any(result.values()):
        # An unlabelled oral note or pasted abstract still counts as supplied material.
        result['摘要'] = ' '.join(str(text or '').split())[:2_000]
    abstract = result['摘要']
    first_sentence = re.split(r'(?<=[。.!?])', abstract, maxsplit=1)[0].strip() if abstract else ''
    result['研究问题'] = result['题目'] or result['研究问题'] or first_sentence[:160]
    result['本文方法'] = result['方法']
    result['预期创新'] = result['创新'] or result['结果']
    return result


def c_info_route(task):
    route = str(getattr(task, 'c_info_route', '') or '').strip().lower()
    if route in {'skip', 'upload', 'oral'}:
        return route
    # Legacy answers carried free text without a route; treat them as supplied material.
    return 'upload' if str(task.user_results or '').strip() else 'skip'


def c_writing_rule(task):
    mode = task.mode.upper()
    route = c_info_route(task)
    if mode == 'C1':
        return C1_SKIP_RULE if route == 'skip' else C1_MATERIAL_RULE
    if mode == 'C2':
        return C2_SKIP_RULE if route == 'skip' else C2_MATERIAL_RULE
    return ''


def style_reference_card(task):
    """Build the target-journal reference card, or state explicitly why it is degraded."""
    journal = str(task.target_journal or '').strip()
    if not journal:
        return '', False, '未提供目标期刊'
    folded = journal.casefold()
    matches = [
        paper for paper in task.papers
        if folded in str(paper.get('venue') or paper.get('journal') or '').casefold()
    ]
    lines = ['# 目标期刊写法参考卡', '', f'目标期刊：{journal}', '']
    if len(matches) < 2:
        reason = (
            f'检索池内属于《{journal}》的范文仅 {len(matches)} 篇（少于 2 篇），'
            '不能形成可靠的写法参考；本次按通用引言口径写，不抄写任何单篇范文措辞。'
        )
        lines.extend(['## 降级原因', '', reason])
        return '\n'.join(lines).strip(), True, reason
    lines.extend(['## 可参考范文（仅看结构与书目信息）', ''])
    for paper in matches[:3]:
        lines.append(f"- [{paper.get('ref_no')}] {paper.get('title', '未命名')}（{paper.get('venue', '')}）")
    lines.extend([
        '', '## 字段降级说明', '',
        '检索池只含摘要与书目信息，未取得开放全文；段数与职能、顺序过渡、引用密度位置无法可靠判定，'
        '三项均按降级处理。只借结构与学科口径，不复制范文原句。',
    ])
    return '\n'.join(lines).strip(), False, ''


def _style_reference_note(task):
    if task.mode.upper() != 'C1' or not str(task.target_journal or '').strip():
        return ''
    _, degraded, reason = style_reference_card(task)
    return reason if degraded else '已生成写法参考卡，只借结构不抄文字。'


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

    def _generate_components(self, task, strict=False):
        if self.model is None:
            raise WritingInputError('component data or a component model is required')
        payload = {
            'stage': 'components',
            'mode': task.mode,
            'mode_template': self._mode_template(task.mode.upper()),
            'components_schema': COMPONENT_SCHEMAS.get(task.mode.upper(), ''),
            'direction': task.direction,
            'papers': task.papers,
            'analysis': task.analysis,
            'search_overview': task.search_overview,
            'project': task.project,
            'user_results': task.user_results,
            'c_info_route': c_info_route(task),
            'user_material': extract_user_material(task.user_results) if c_info_route(task) != 'skip' else {},
            'c_writing_rules': c_writing_rule(task),
            'target_journal': task.target_journal,
            'style_reference_note': _style_reference_note(task),
            'team_context': task.team_context,
            'custom_purpose': task.custom_purpose,
        }
        if task.mode.upper() == 'B':
            payload['project_generation_rules'] = B_PROJECT_GENERATION_RULE
            if task.project_draft:
                payload['project_draft'] = task.project_draft
                payload['project_input_path'] = task.project_input_path
                payload['project_draft_rules'] = B_DRAFT_RULE
            payload['materials'] = list(task.materials or [])
            payload['material_index'] = _render_material_index(task.materials) if task.materials else ''
            payload['material_rules'] = B_MATERIAL_RULE
        if task.mode.upper() == 'E':
            payload['custom_purpose_rules'] = E_CUSTOM_PURPOSE_RULE
        if strict:
            payload['schema_reminder'] = (
                '上一次返回缺少必需键、数量不符、引用了没有 evidence 条目的编号，或 quote 不是摘要逐字原句；'
                '这次必须严格按 components_schema 返回，每个 [n] 都要有 evidence 条目，'
                'quote 从对应摘要中逐字复制一个连续片段（含原标点），拿不准就省略该论断。'
            )
        response = self.model.complete_json(
            '你是科研写作构件生成器。只使用输入摘要，所有文献事实必须附 refs 和逐字摘要 quotes；'
            'quote 必须是该篇摘要中逐字复制的一个连续片段（含原标点与空格），不得改写、翻译、拼接或概括，'
            '摘要中没有可直接复制的原句时不要输出该条证据或该论断；'
            '不得虚构研究空白、项目基础或用户结果。严格按 components_schema 的键名、字段与数量范围返回 JSON 对象 {"components": ...}。'
            + c_writing_rule(task)
            + (C1_STYLE_RULE if task.mode.upper() == 'C1' and str(task.target_journal or '').strip() else '')
            + (B_PROJECT_GENERATION_RULE if task.mode.upper() == 'B' else '')
            + (B_DRAFT_RULE if task.mode.upper() == 'B' and task.project_draft else '')
            + (B_MATERIAL_RULE if task.mode.upper() == 'B' and task.materials else '')
            + (E_CUSTOM_PURPOSE_RULE if task.mode.upper() == 'E' else ''),
            payload,
        )
        if not isinstance(response, dict) or not isinstance(response.get('components'), dict):
            raise WritingInputError('component model must return a components object')
        return response['components']

    def _build_components(self, task, mode):
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
            markdown = _render_c2(task.component_data, task)
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

    def produce_components(self, task):
        report_stage_phase('generate', 'components')
        mode = task.mode.upper()
        if mode not in OUTLINE_HEADINGS:
            raise WritingInputError(f'unsupported writing mode: {task.mode}')
        if task.component_data is not None:
            return self._build_components(task, mode)
        last_error = None
        last_candidate = None
        for attempt in range(2):
            try:
                task.component_data = self._generate_components(task, strict=attempt > 0)
                return self._build_components(task, mode)
            except (WritingInputError, ValueError) as error:
                last_error = error
                last_candidate = task.component_data
                task.component_data = None
        if (
            last_candidate is not None
            and last_error is not None
            and 'no evidence ledger entry' in str(last_error)
        ):
            try:
                evidence = EvidenceAuditor(task.papers).audit_data(last_candidate)
                repaired, removed = _strip_unsupported_citations(
                    last_candidate, {item['ref'] for item in evidence}
                )
                if removed:
                    task.component_data = repaired
                    components = self._build_components(task, mode)
                    task.events.append(WritingEvent(
                        kind='citation_repair',
                        payload={'removed': removed, 'stage': 'components'},
                    ))
                    components.markdown = (
                        f'> 引用修复：已移除 {removed} 处无证据编号，相关表述请人工复核。\n\n'
                        + components.markdown
                    )
                    return components
            except WritingInputError:
                pass
        raise last_error

    def produce_outline_and_sample(self, task, components):
        report_stage_phase('generate', 'outline_sample')
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
        report_stage_phase('generate', 'body')
        model_backed = body_writer is None and self.model is not None
        if model_backed:
            def body_writer(context):
                response = self.model.complete_json(
                    '你是科研正文写作器。先读已完成的构件、提纲和样章，再写连贯正文。每个文献事实必须在 evidence 中给出 refs 与逐字摘要 quotes；'
                    'quote 必须是该篇摘要中逐字复制的一个连续片段（含原标点），不得改写、翻译或拼接；'
                    '分析判断标明“分析”，不得虚构用户结果、全文细节或参考文献；'
                    '正文 CJK 字数必须落在 length_target 区间，并严格遵守 format_rules。'
                    + c_writing_rule(task)
                    + (C1_STYLE_RULE if task.mode.upper() == 'C1' and str(task.target_journal or '').strip() else '')
                    + (B_PROJECT_GENERATION_RULE if task.mode.upper() == 'B' else '')
                    + (B_DRAFT_RULE if task.mode.upper() == 'B' and task.project_draft else '')
                    + (B_MATERIAL_RULE if task.mode.upper() == 'B' and task.materials else '')
                    + (E_CUSTOM_PURPOSE_RULE if task.mode.upper() == 'E' else ''),
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
                        'project_generation_rules': (
                            B_PROJECT_GENERATION_RULE if task.mode.upper() == 'B' else ''
                        ),
                        'project_draft': task.project_draft if task.mode.upper() == 'B' else '',
                        'project_input_path': task.project_input_path if task.mode.upper() == 'B' else 'direction',
                        'project_draft_rules': (
                            B_DRAFT_RULE if task.mode.upper() == 'B' and task.project_draft else ''
                        ),
                        'materials': list(task.materials or []) if task.mode.upper() == 'B' else [],
                        'material_index': (
                            _render_material_index(task.materials) if task.mode.upper() == 'B' and task.materials else ''
                        ),
                        'material_rules': B_MATERIAL_RULE if task.mode.upper() == 'B' else '',
                        'custom_purpose': task.custom_purpose,
                        'custom_purpose_rules': (
                            E_CUSTOM_PURPOSE_RULE if task.mode.upper() == 'E' else ''
                        ),
                        'user_results': task.user_results,
                        'c_info_route': c_info_route(task),
                        'user_material': extract_user_material(task.user_results) if c_info_route(task) != 'skip' else {},
                        'c_writing_rules': c_writing_rule(task),
                        'target_journal': task.target_journal,
                        'style_reference_note': _style_reference_note(task),
                        'team_context': task.team_context,
                        'length_target': LENGTH_TARGETS.get(task.mode.upper(), ''),
                        'format_rules': FORMAT_RULES.get(task.mode.upper(), ''),
                        'response_schema': (
                            '严格返回 {"body":"完整正文 Markdown（含全部章节）",'
                            '"evidence":[{"claim":"论断","refs":[论文 ref_no],"quotes":{"<ref_no>":"摘要逐字原句"}}]}。'
                        ),
                    },
                )
                if isinstance(response, dict):
                    for key in ('body', 'text', 'markdown', 'document'):
                        if isinstance(response.get(key), str):
                            return {'text': response[key], 'evidence': response.get('evidence') or []}
                return response
        if body_writer is None:
            raise WritingInputError('a body composer is required; no prose was fabricated')
        context = {
            'task': task,
            'components': components,
            'outline': outline_sample.outline,
            'sample': outline_sample.sample,
        }
        last_error = None
        last_result = None
        for _ in range(2 if model_backed else 1):
            try:
                result = body_writer(context)
                last_result = result
            except ValueError as error:
                last_error = WritingInputError(str(error))
                continue
            try:
                if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                    raise WritingInputError('body composer must return text and evidence')
                auditor = EvidenceAuditor(task.papers)
                evidence = auditor.audit_items(result.get('evidence') or [])
                text = result['text']
                _validate_citation_coverage(text, evidence)
                _validate_material_citations(text, task.materials)
                text = _label_abstract_citations(text, evidence)
                return BodyOutput(text=text, evidence=evidence)
            except WritingInputError as error:
                last_error = error
        if (
            model_backed
            and isinstance(last_result, dict)
            and isinstance(last_result.get('text'), str)
            and last_error is not None
            and 'no evidence ledger entry' in str(last_error)
        ):
            try:
                evidence = EvidenceAuditor(task.papers).audit_items(
                    last_result.get('evidence') or []
                )
                repaired_text, removed = _strip_unsupported_citations(
                    last_result['text'], {item['ref'] for item in evidence}
                )
                if removed:
                    _validate_citation_coverage(repaired_text, evidence)
                    _validate_material_citations(repaired_text, task.materials)
                    repaired_text = _label_abstract_citations(repaired_text, evidence)
                    task.events.append(WritingEvent(
                        kind='citation_repair',
                        payload={'removed': removed, 'stage': 'body'},
                    ))
                    repaired_text = (
                        f'> 引用修复：已移除 {removed} 处无证据编号，相关表述请人工复核。\n\n'
                        + repaired_text
                    )
                    return BodyOutput(text=repaired_text, evidence=evidence)
            except WritingInputError:
                pass
        raise last_error

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

        if task.mode.upper() == 'C1' and str(task.target_journal or '').strip():
            card, degraded, reason = style_reference_card(task)
            (task_dir / STYLE_REFERENCE_FILE).write_text(card, encoding='utf-8')
            task.events.append(WritingEvent(kind='style_reference_ready', payload={'degraded': degraded, 'reason': reason}))

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
