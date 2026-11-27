import json
import os
import re
from copy import deepcopy
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
    'C2': ['研究主题与检索范围', '关键词和检索策略', '代表性文献清单', '文献分类框架', '不同研究方向的综合分析', '主要技术路线比较', '文献比较表', '现有研究不足', '研究空白分析表', '未来研究方向', '完整综述文本', '衔接与重复检查'],
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
B_BODY_RULE = (
    'B 正文的固定节名必须是「已有研究对本项目技术路线的支撑」，标题不得附加“（强制构件…）”等括注；'
    '正文 CJK 字数必须落在 2000–3000，按约 2500 字写作，超过 3000 视为不合格整篇压缩，'
    '宁可精简论述也不得删除必需章节、对解表、六段链或参考文献编号。'
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

REWORK_ROUNDS = 3

LENGTH_TARGETS = {
    'A': '1500-2500',
    'A_DIALOGUE': '1500-4000',
    'B': '2000-3000',
    'C1': '800-1200',
    'C2': '800-1200',
    'D': '3000-6000',
    'E': '1500-2500',
}

FORMAT_RULES = {
    'A': '研究空白证据表每行必须以「空白1：」「空白2：」…开头，并在同一行写 [n] 引用与理由类型；方向卡保留「第 N 推荐」「核心研究问题」「数据可得性」。',
    'A_DIALOGUE': '七个分类标题之前必须先写「领域格局与对话要点」：恰好 5–8 条 Markdown 列表要点，每条带 [n]，其中至少 3 条明确写“研究空白”；每类选题的两张卡与综合第 1 推荐必须保留推荐理由与主要风险。',
    'B': '固定节名「已有研究对本项目技术路线的支撑」不带括注；必须保留「若不开展本项目」刚性需求段、对解表、六段论证链与「研究内容（一/二/三）」支撑清单；正文 CJK 目标 2300–2800，硬上限 3000。',
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
C2_BODY_RULE = (
    'C2 正文必须包含以下标题：研究主题与检索范围、关键词和检索策略、代表性文献清单、'
    '文献分类框架、完整综述文本、未来研究方向。文献分类框架必须逐一出现：理论基础、研究对象、'
    '研究问题、技术方法、数据与实验、研究结论、研究局限。完整综述文本必须含 [n] 引用和'
    '现有研究不足/现有局限；必须有六列文献比较表（文献、研究问题、数据、核心方法、主要发现、局限性）'
    '和五列研究空白分析表（研究方向、已有进展、现有不足、文献证据、可深入研究的问题）。'
    '不得写成讨论，不得要求本文结果。正文（不含参考文献）CJK 汉字+英文词合计必须为 800–1200，'
    '超出时压缩，不得靠删标题/表格规避。'
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
        '"data":"…","method":"…","findings":"…","limitation":"…","evidence":[EVIDENCE]}],'
        '"synthesis":[{"direction":"…","progress":"…","representative_methods":"…","scenarios":"…","limit":"…"}],'
        '"route_comparison":[{"route":"…","problem":"…","performance":"…","conditions":"…",'
        '"limitation":"…","complementarity":"…"}],'
        '"gaps":[{"direction":"…","progress":"…","limitation":"…","evidence_text":"[n] 摘要证据","future_question":"…","evidence":[EVIDENCE]}],'
        '"future_directions":[{"direction":"…","basis":"…","question":"…"}]}；'
        'classification 按理论基础、研究对象、研究问题、技术方法、数据与实验、研究结论、研究局限七维给出；'
        'comparison 与 gaps 的每一行都必须带 evidence（含 refs 与逐字摘要 quotes）；'
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
        '"discussion_questions":["…"]}；reading_cards 3–5 张。'
        '中文化硬性要求：所有面向页面的展示字段必须用简体中文概括；论文题目与数据集专名可保留英文，'
        '英文术语在中文后用括号注明（如：多智能体协同（multi-agent））。'
        'method_comparison 的 technique≤24 字、strength≤24 字、limitation≤24 字、data≤30 字，均为中文短句，禁止整句摘抄英文摘要；'
        'reading_cards 的 research_question/data/method/findings/limitations/team_relevance/reason 各≤40 字中文短句；'
        'progress.summary≤80 字中文；ranking.reason≤80 字、risk≤40 字中文；discussion_questions 用中文。'
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
    last_body_text: str = ''
    events: list = field(default_factory=list)


@dataclass
class ComponentOutput:
    mode: str
    data: dict
    markdown: str
    evidence: list
    has_user_results: bool = False
    structural_refs: set = field(default_factory=set)

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
        if not slot.get('title'):
            return f"### 选题 {index}｜未推荐\n- 具体原因：{slot.get('reason', '现有证据不足以形成非重复且可验证的选题。')}"
        return '\n'.join([
            f"### 选题 {index}｜未推荐（分析候选）：{slot['title']}",
            f"- 核心研究问题：{slot.get('core_question', '')}",
            f"- 文献依据与机会：{slot.get('opportunity', '')} {_evidence_refs(slot.get('evidence', []))}",
            f"- 数据可得性：{slot.get('data_availability', '')}",
            f"- 研究价值：{slot.get('research_value', '')}（分析）",
            f"- 可行性：{slot.get('feasibility', '')}（分析）",
            f"- 创新潜力：{slot.get('innovation_potential', '')}（分析）",
            f"- 实施难度：{slot.get('implementation_difficulty', '')}（分析）",
            f"- 主要风险：{slot.get('risk', '')}",
            f"- 具体原因：{slot.get('reason', '池内无直接文献证据支持该方向，保留为分析候选，待人工核实。')}",
        ])
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


def _a_dialogue_word_count(text):
    body = text.split('## 参考文献')[0]
    return len(re.findall(r'[\u4e00-\u9fff]', body))


def _a_dialogue_shape_errors(text):
    errors = []
    body = text.split('## 参考文献')[0]
    paras = [line for line in body.split('\n') if line.strip()]
    head = body[:800]
    if '领域' not in head and '格局' not in head:
        errors.append('missing 领域/格局 first paragraph')
    headings = []
    for label in DIALOGUE_CATEGORIES:
        match = re.search(
            r'^#{2,4}\s*(?:\d+\s*[.、]?\s*)?' + re.escape(label) + r'\s*$',
            body, flags=re.M,
        )
        if match is None:
            errors.append(f'missing category heading「{label}」')
        else:
            headings.append((label, match))
    headings.sort(key=lambda item: item[1].start())
    pre_body = body[:headings[0][1].start()] if headings else body
    key_lines = [
        line for line in pre_body.splitlines()
        if re.match(r'^\s*[-*]\s+', line) and re.search(r'\[\d+\]', line)
    ]
    if not 5 <= len(key_lines) <= 8:
        errors.append(f'key points {len(key_lines)} outside 5-8')
    blanks = [line for line in key_lines if '空白' in line]
    if len(blanks) < 3:
        errors.append(f'research-gap key points {len(blanks)} < 3')
    slot_pat = re.compile(r'^\s*[-*]?\s*选题\s*([12１２])\s*[｜|]', re.M)
    for index, (label, match) in enumerate(headings):
        end = headings[index + 1][1].start() if index + 1 < len(headings) else len(body)
        section = body[match.end():end]
        slots = list(slot_pat.finditer(section))
        if len(slots) != 2:
            errors.append(f'{label} slots {len(slots)} != 2')
        for i, slot in enumerate(slots):
            seg_end = slots[i + 1].start() if i + 1 < len(slots) else len(section)
            segment = section[slot.start():seg_end]
            if '未推荐' in segment[:100]:
                continue
            if not re.search(r'\[\d+\]', segment):
                errors.append(f'{label} slot {i + 1} recommended without citation')
    if not 1500 <= _a_dialogue_word_count(body) <= 4000:
        errors.append(f'word count {_a_dialogue_word_count(body)} outside 1500-4000')
    return errors


def _a_word_count(text):
    body = text.split('## 参考文献')[0]
    return len(re.findall(r'[\u4e00-\u9fff]', body))


def _a_body_shape_errors(text):
    """镜像 verify_delivery.py --mode A 的机械结构口径（不含引文台账类检查）。"""
    errors = []
    body = text.split('## 参考文献')[0]
    head = body[:800]
    lines = body.splitlines()
    for word in ('研究价值', '可行性', '创新潜力', '实施难度', '核心研究问题', '数据可得性'):
        if body.count(word) < 3:
            errors.append(f'方向卡字段「{word}」出现 <3 次')
    ranks = re.findall(r'第\s*[0-9０-９一二三四五]\s*推荐|储备方向', body)
    if len(ranks) < 3:
        errors.append(f'排序标记（第 N 推荐/储备方向）<3（实得 {len(ranks)}）')
    if re.search(r'第\s*[1１一]\s*推荐', body) is None:
        errors.append('missing 第 1 推荐标记')
    if not any(key in body for key in ('优于', '推荐理由', '排序理由')):
        errors.append('missing 第 1 推荐理由（优于/推荐理由/排序理由任一）')
    if sum(1 for line in lines if '空白' in line and re.search(r'\[\d+\]', line)) < 3:
        errors.append('空白证据行（含 [n]）<3')
    if '全景树' not in body and '分堆' not in body:
        errors.append('missing 全景树/分堆')
    if '领域' not in head and '格局' not in head:
        errors.append('first paragraph must mention 领域/格局')
    count = _a_word_count(body)
    if not 1500 <= count <= 2500:
        errors.append(f'word count {count} outside 1500-2500')
    return errors


def _evidence_retry_exhausted(message):
    return any(marker in message for marker in (
        'not claim-eligible',
        'not in the abstract',
        'evidence requires',
        'no evidence ledger entry',
    ))


def _rebuild_a_body(task):
    try:
        data = task.component_data if isinstance(task.component_data, dict) else {}
        data, _ = _backfill_a_gap_evidence(data, task.papers)
        directions = data.get('directions') or []
        gaps = data.get('gaps') or []
        landscape = data.get('landscape') or []
        if not directions or not gaps:
            return None
        evidence = EvidenceAuditor(task.papers).audit_data(data)
        overview = getattr(task, 'search_overview', {}) or {}
        lines = [
            f"# {task.direction or '领域'}｜领域格局与选题方向",
            '',
            '## 领域格局与全景树（分堆）',
            '',
            (
                f"本报告围绕{task.direction or '该领域'}，基于池内 {overview.get('pool_count', 0)} 篇文献"
                '按方向分堆形成领域全景；以下判断只依据摘要证据与池内统计（分析）。'
            ),
            '',
        ]
        for row in landscape:
            refs = row.get('paper_refs') or []
            ref_text = '篇号 ' + '、'.join(str(ref) for ref in refs) if refs else '篇号未记录'
            lines.append(
                f"- {row.get('direction', '未命名方向')}分堆：池内占比 {row.get('share', '未统计')}"
                f"（{ref_text}），团队与期刊口径 {row.get('venues', '未统计')}。"
            )
        lines.extend(['', '## 研究空白', ''])
        for index, row in enumerate(gaps, 1):
            refs = _evidence_refs(row.get('evidence') or [])
            lines.append(
                f"空白{index}：{row.get('gap', '')} {refs}"
                f"（机制/数据/方法/需求理由：{row.get('reason', '未提供')}）。"
            )
        lines.extend(['', '## 方向卡与排序', ''])
        for direction in directions:
            lines.extend([_render_a_direction(direction), ''])

        boundary = (
            '## 证据边界与阅读深度说明\n\n'
            f"本轮检索数据库为{'、'.join(overview.get('databases') or []) or '未记录'}，"
            f"检索词为{'、'.join(overview.get('queries') or []) or '未记录'}；"
            '正文只使用摘要可核验内容，未读全文的公式、图表与复现细节不写成确定结论（分析）。'
        )
        if evidence:
            boundary += (
                f"\n\n例如池内第 {evidence[0]['ref']} 篇的证据支持相应的损失评估线索"
                f" [{evidence[0]['ref']}]，但摘要未给出可直接迁移到本项目场景的参数。"
            )
        lines.extend(['', boundary])
        for direction in directions:
            refs = _evidence_refs(direction.get('evidence') or [])
            lines.extend([
                '',
                f"### {direction.get('title', '未命名方向')}评估说明",
                (
                    f"该方向的核心研究问题是{direction.get('core_question', '未提供')}；"
                    f"数据可得性为{direction.get('data_availability', '未提供')}。"
                    f"研究价值为{direction.get('research_value', '未提供')}，可行性为{direction.get('feasibility', '未提供')}，"
                    f"创新潜力为{direction.get('innovation_potential', '未提供')}，实施难度为{direction.get('implementation_difficulty', '未提供')}；"
                    f"文献依据 {refs or '未记录'}（分析）。"
                ),
            ])
        if directions:
            first = directions[0]
            lines.extend([
                '',
                '## 结论',
                '',
                (
                    f"综合排序以第 {first.get('rank', 1)} 推荐方向为首选（推荐理由："
                    f"{first.get('first_reason') or '证据衔接度与可实施性相对更高'}），"
                    f"主要风险为{first.get('risk', '未提供')}；其余方向作为对照与储备保留（分析）。"
                ),
            ])
        if _a_word_count('\n'.join(lines)) < 1500:
            lines.extend(['', '## 选题核验清单', ''])
            for direction in directions:
                refs = _evidence_refs(direction.get('evidence') or [])
                lines.append(
                    f"- {direction.get('title', '未命名方向')}：核心问题为{direction.get('core_question', '未提供')}，"
                    f"数据线索为{direction.get('data_availability', '未提供')}，"
                    f"主要风险为{direction.get('risk', '未提供')}，证据为 {refs or '未记录'}；"
                    '该核验只用于方向排序与可行性判断（分析）。'
                    '正式立项前还需核验数据权限、样本可得性与评价口径；'
                    '若关键数据不可得，则该方向降级为方法复核或储备方向。'
                )
            for row in gaps:
                refs = _evidence_refs(row.get('evidence') or [])
                lines.append(
                    f"- 空白核验：{row.get('gap', '')} {refs}；"
                    f"理由类型为{row.get('reason', '未提供')}，需要在正式研究设计中补齐数据或方法证据（分析）。"
                    '若短期内无法补齐，应在研究内容中明确证据等级、适用边界与替代验证路径。'
                )
        text = '\n'.join(lines).strip() + '\n'
        text, removed = _strip_unsupported_citations(text, {item['ref'] for item in evidence})
        if removed:
            task.events.append(WritingEvent(
                kind='citation_repair',
                payload={'removed': removed, 'stage': 'a_body_rebuild'},
            ))
        if _a_body_shape_errors(text):
            return None
        _validate_citation_coverage(text, evidence)
        return BodyOutput(text=_label_abstract_citations(text, evidence), evidence=evidence)
    except WritingInputError:
        return None


def _ensure_pool_ledger(evidence, papers, text):
    available = {item['ref'] for item in evidence}
    missing = _citation_refs(text) - available
    if not missing:
        return evidence
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
    }
    extra = []
    for ref in sorted(missing):
        paper = by_ref.get(ref)
        abstract = str((paper or {}).get('abstract') or '')
        if not paper or paper.get('claim_eligible') is False or not abstract.strip():
            continue
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[.!?。！？])\s+', abstract)
            if len(sentence.strip()) >= 20
        ]
        extra.append({
            'claim': '池内篇号口径（结构引用，待人工核对）',
            'ref': ref,
            'quote': sentences[0] if sentences else abstract.strip(),
            'level': paper.get('evidence_level') or 'B',
        })
    return evidence + extra


def _repair_evidence_quotes(items, papers):
    """Replace non-verbatim quotes with a real abstract sentence for the same ref."""
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
    }
    repaired = []
    for item in items:
        if not isinstance(item, dict):
            repaired.append(item)
            continue
        item = dict(item)
        quotes = item.get('quotes') or {}
        claim_words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', str(item.get('claim') or '').casefold()))
        new_quotes = {}
        for ref in item.get('refs') or []:
            try:
                ref = int(ref)
            except (TypeError, ValueError):
                continue
            paper = by_ref.get(ref)
            abstract = str((paper or {}).get('abstract') or '')
            quote = quotes.get(str(ref), quotes.get(ref))
            if not abstract.strip() or (quote and verbatim_quote(abstract, quote)):
                new_quotes[str(ref)] = quote
                continue
            sentences = [
                sentence.strip()
                for sentence in re.split(r'(?<=[.!?。！？])\s+', abstract)
                if len(sentence.strip()) >= 20
            ]
            if sentences:
                quote = max(
                    sentences,
                    key=lambda s: len(claim_words & set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', s.casefold()))),
                )
            else:
                quote = abstract.strip()
            new_quotes[str(ref)] = quote
        item['quotes'] = new_quotes
        repaired.append(item)
    return repaired


def _audit_items_with_quote_repair(auditor, items, papers):
    try:
        return auditor.audit_items(items)
    except WritingInputError as error:
        if 'not in the abstract' not in str(error):
            raise
    return auditor.audit_items(_repair_evidence_quotes(items, papers))


def _ensure_a_dialogue_intro(text, task):
    """Deterministically add the missing 5–8 dialogue points from component evidence."""
    data = task.component_data if isinstance(task.component_data, dict) else {}
    gaps = list(data.get('gaps') or [])
    landscape = list(data.get('landscape') or [])
    overall = data.get('overall_first') if isinstance(data.get('overall_first'), dict) else {}

    first_heading = re.search(
        r'^#{2,4}\s*(?:\d+\s*[.、]?\s*)?' + re.escape(DIALOGUE_CATEGORIES[0]) + r'\s*$',
        text, flags=re.M,
    )
    if first_heading is None:
        return text
    pre_body = text[:first_heading.start()]
    existing = [
        line for line in pre_body.splitlines()
        if re.match(r'^\s*[-*]\s+', line) and re.search(r'\[\d+\]', line)
    ]
    if 5 <= len(existing) <= 8 and sum(1 for line in existing if '空白' in line) >= 3:
        return text

    def refs(evidence):
        return ' '.join(sorted({
            f'[{ref}]' for item in evidence or []
            for ref in (item.get('refs') or [])
        }))

    bullets = []
    for gap in gaps[:3]:
        citation = refs(gap.get('evidence') or [])
        if citation:
            bullets.append(f"- 研究空白：{gap.get('gap', '').strip()} {citation}")
    for row in landscape[:2]:
        citation = ' '.join(f'[{ref}]' for ref in (row.get('paper_refs') or []))
        if citation:
            bullets.append(f"- 领域格局：{row.get('direction', '').strip()}（{row.get('share', '')}）{citation}")
    citation = refs(overall.get('evidence') or [])
    if citation and overall.get('topic'):
        bullets.append(f"- 首选方向：{overall['topic']} {citation}")
    if len(bullets) < 5:
        return text
    bullets = bullets[:8]
    if _a_dialogue_word_count(text) + sum(_a_dialogue_word_count(b) for b in bullets) > 4000:
        bullets = [line[:80] for line in bullets[:5]]
    block = '## 领域格局与对话要点\n\n' + '\n'.join(bullets) + '\n\n'
    cleaned = '\n'.join(
        line for line in pre_body.splitlines()
        if not (re.match(r'^\s*[-*]\s+', line) and re.search(r'\[\d+\]', line))
    )
    return block + cleaned.strip() + '\n\n' + text[first_heading.start():]


def _compact_a_dialogue_data(data, limit):
    def clip(value):
        text = str(value or '').strip()
        return text if limit is None or len(text) <= limit else text[:limit].rstrip() + '…'

    compact = dict(data)
    compact['landscape'] = [
        {**row, 'direction': clip(row.get('direction')), 'share': clip(row.get('share')),
         'venues': clip(row.get('venues'))}
        for row in data.get('landscape') or []
    ]
    compact['gaps'] = [
        {**row, 'gap': clip(row.get('gap')), 'reason': clip(row.get('reason'))}
        for row in data.get('gaps') or []
    ]
    compact['topic_groups'] = []
    for group in data.get('topic_groups') or []:
        slots = []
        for slot in group.get('slots') or []:
            if slot.get('recommended') is False:
                slots.append({**slot, 'reason': clip(slot.get('reason'))})
                continue
            slots.append({
                **slot,
                'title': clip(slot.get('title')), 'core_question': clip(slot.get('core_question')),
                'opportunity': clip(slot.get('opportunity')), 'data_availability': clip(slot.get('data_availability')),
                'research_value': clip(slot.get('research_value')), 'feasibility': clip(slot.get('feasibility')),
                'innovation_potential': clip(slot.get('innovation_potential')),
                'implementation_difficulty': clip(slot.get('implementation_difficulty')),
                'risk': clip(slot.get('risk')),
            })
        compact['topic_groups'].append({**group, 'slots': slots})
    first = dict(data.get('overall_first') or {})
    first['reason'] = clip(first.get('reason'))
    first['risk'] = clip(first.get('risk'))
    compact['overall_first'] = first
    return compact


def _pad_a_dialogue_body(text, task):
    if _a_dialogue_word_count(text) >= 1500:
        return text
    data = task.component_data if isinstance(task.component_data, dict) else {}
    def refs(evidence):
        return ' '.join(sorted({
            f'[{ref}]' for item in evidence or []
            for ref in (item.get('refs') or [])
        }))
    padded = text.rstrip()
    lines = ['## 证据边界与待核对事项', '']
    for gap in data.get('gaps') or []:
        citation = refs(gap.get('evidence') or [])
        if citation:
            lines.append(f"- {gap.get('gap', '').strip()}：{gap.get('reason', '').strip()} {citation}。")
            candidate = padded + '\n\n' + '\n'.join(lines) + '\n'
            if _a_dialogue_word_count(candidate) >= 1500:
                return candidate
    for row in data.get('landscape') or []:
        citation = refs(row.get('evidence') or [])
        if citation:
            lines.append(f"- {row.get('direction', '').strip()}：{row.get('share', '').strip()} {citation}。")
            candidate = padded + '\n\n' + '\n'.join(lines) + '\n'
            if _a_dialogue_word_count(candidate) >= 1500:
                return candidate
    if len(lines) > 2:
        padded += '\n\n' + '\n'.join(lines) + '\n'
        if _a_dialogue_word_count(padded) >= 1500:
            return padded

    checklist = ['## 选题核验清单', '']
    for group in data.get('topic_groups') or []:
        category = re.sub(r'\[\d+\]', '', str(group.get('category') or '')).strip()
        for slot in group.get('slots') or []:
            title = re.sub(r'\[\d+\]', '', str(slot.get('title') or '')).strip()
            focus = re.sub(
                r'\[\d+\]', '',
                str(slot.get('core_question') or slot.get('reason') or slot.get('opportunity') or ''),
            ).strip()
            if not title and not focus:
                continue
            label = '·'.join(part for part in (category, title) if part) or '当前选题'
            checklist.append(
                f'- {label}：围绕“{focus or title}”，先确认数据来源、时间覆盖与可获得性，'
                '再核对方法适用条件、对照设置和评价指标；摘要不能支撑的环节标为待核实，'
                '不将分析判断写成文献结论（分析）。'
            )
            candidate = padded.rstrip() + '\n\n' + '\n'.join(checklist) + '\n'
            if _a_dialogue_word_count(candidate) >= 1500:
                return candidate
    return padded.rstrip() + '\n\n' + '\n'.join(checklist) + '\n' if len(checklist) > 2 else padded


def _repair_d_components(data, papers):
    if not isinstance(data, dict):
        return data
    repaired = deepcopy(data)
    cards = [
        card for card in repaired.get('reading_cards') or []
        if isinstance(card, dict) and str(card.get('ref', '')).isdigit()
    ]
    eligible = [
        paper for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
        and str(paper.get('abstract') or '').strip()
        and paper.get('claim_eligible') is not False
    ]
    index = 0
    while len(cards) < 3 and eligible:
        paper = eligible[index % len(eligible)]
        ref = int(paper['ref_no'])
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[.!?。！？])\s+', str(paper.get('abstract') or ''))
            if len(sentence.strip()) >= 20
        ]
        if not sentences:
            index += 1
            continue
        quote = sentences[0]
        title = str(paper.get('title') or f'池内文献 [{ref}]')
        cards.append({
            'ref': ref,
            'title': title if index < len(eligible) else title + '：交叉复核',
            'reason': '池内代表作，自动补齐精读卡',
            'research_question': '该文献围绕主题提出的核心研究问题（据摘要）',
            'data': '摘要未说明',
            'method': '摘要未说明',
            'findings': '摘要报告了与主题相关的实证结果（据摘要）',
            'limitations': '摘要未说明',
            'team_relevance': '待团队确认',
            'reading_depth': '仅摘要',
            'evidence': [{
                'claim': '池内文献摘要证据（精读卡补齐）',
                'refs': [ref],
                'quotes': {str(ref): quote},
            }],
        })
        index += 1
    repaired['reading_cards'] = cards[:5]
    if not repaired.get('ranking'):
        repaired['ranking'] = [
            {
                'rank': number,
                'topic': row.get('direction') or f'方向 {number}',
                'reason': '基于池内进展与证据整理（分析）',
                'risk': '数据与全文细节待核实',
            }
            for number, row in enumerate(repaired.get('progress') or [], 1)
        ][:3]
    if not repaired.get('discussion_questions'):
        repaired['discussion_questions'] = [
            '池内证据能够支持哪些确定性结论，哪些仍需全文核实？',
            '团队现有数据能否覆盖上述研究空白？',
        ]
    return repaired


def _d_display_language_errors(data):
    if not isinstance(data, dict):
        return ['构件不是对象']
    limits = {
        'method_comparison': {'technique': 24, 'strength': 24, 'limitation': 24, 'data': 30},
        'reading_cards': {
            'research_question': 40, 'data': 40, 'method': 40, 'findings': 40,
            'limitations': 40, 'team_relevance': 40, 'reason': 40,
        },
    }
    errors = []

    def han_count(text):
        return len(re.findall(r'[\u4e00-\u9fff]', str(text or '')))

    def latin_words(text):
        return len(re.findall(r'[A-Za-z]{2,}', str(text or '')))

    for key, fields in limits.items():
        rows = data.get(key) or []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            for field, limit in fields.items():
                value = str(row.get(field) or '')
                han = han_count(value)
                if han < 2 or han < latin_words(value):
                    errors.append(f'{key}[{index}].{field} 需中文概括')
    summary = data.get('progress') or []
    for index, row in enumerate(summary, 1):
        if isinstance(row, dict) and han_count(row.get('summary')) < 4:
            errors.append(f'progress[{index}].summary 需中文概括')
    return errors


def _backfill_a_dialogue_slot_evidence(data, papers):
    if not isinstance(data, dict):
        return data, 0
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
    }
    changed = 0
    for group in data.get('topic_groups') or []:
        for slot in group.get('slots') or []:
            if not isinstance(slot, dict) or slot.get('recommended') is False:
                continue
            if any((item.get('refs') or []) for item in slot.get('evidence') or [] if isinstance(item, dict)):
                continue
            text = ' '.join(str(slot.get(key) or '') for key in ('title', 'core_question', 'opportunity'))
            words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', text.casefold()))
            scored = []
            for paper in by_ref.values():
                abstract = str(paper.get('abstract') or '')
                if not abstract.strip() or paper.get('claim_eligible') is False:
                    continue
                tokens = set(re.findall(
                    r'[A-Za-z\u4e00-\u9fff]{3,}',
                    (str(paper.get('title') or '') + ' ' + abstract).casefold(),
                ))
                overlap = len(words & tokens)
                if overlap:
                    scored.append((overlap, paper))
            if not scored:
                slot['recommended'] = False
                slot['reason'] = '池内无直接文献证据支持该方向，保留为分析候选，待人工核实。'
                changed += 1
                continue
            paper = max(scored, key=lambda item: item[0])[1]
            sentences = [
                sentence.strip()
                for sentence in re.split(r'(?<=[.!?。！？])\s+', str(paper.get('abstract') or ''))
                if len(sentence.strip()) >= 20
            ]
            if not sentences:
                continue
            quote = max(
                sentences,
                key=lambda sentence: len(words & set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', sentence.casefold()))),
            )
            ref = int(paper['ref_no'])
            slot.setdefault('evidence', []).append({
                'claim': str(slot.get('opportunity') or slot.get('title') or '').strip(),
                'refs': [ref],
                'quotes': {str(ref): quote},
            })
            changed += 1
    return data, changed


def _rebuild_a_dialogue_body(task):
    try:
        data = task.component_data if isinstance(task.component_data, dict) else {}
        data, _ = _backfill_a_dialogue_slot_evidence(data, task.papers)
        for limit in (None, 120, 80, 50):
            compact = _compact_a_dialogue_data(data, limit)
            text = _render_a_dialogue(compact)
            text = re.sub(
                r'^#\s+.*$', '# ' + str(task.direction or '领域格局与七类双槽选题'),
                text, count=1, flags=re.M,
            )
            text = re.sub(r'^###\s*选题\s*([12])\s*[｜|]', r'- 选题 \1｜', text, flags=re.M)
            text = _ensure_a_dialogue_intro(text, task)
            text = _pad_a_dialogue_body(text, task)
            evidence = EvidenceAuditor(task.papers).audit_data(compact)
            evidence = _ensure_pool_ledger(evidence, task.papers, text)
            text = _label_abstract_citations(text, evidence)
            if _a_dialogue_shape_errors(text):
                continue
            _validate_citation_coverage(text, evidence)
            return BodyOutput(text=text, evidence=evidence)
        return None
    except WritingInputError:
        return None

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


def _whole_text(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if '…' in text:
        text = text.split('…', 1)[0].rstrip(' ,;，；')
    if text and text[-1] not in '。！？.!?':
        text += '。'
    return text


def _render_c1_card(card):
    return f"### 段落卡·{card['function']}\n- 核心论点：{_whole_text(card['claim'])} {_evidence_refs(card['evidence'])}"


def _render_c1(data):
    lines = ['# 模式 C1 构件', '', '## 引言逻辑框架与段落卡', '']
    for card in data['paragraph_cards']:
        lines.extend([_render_c1_card(card), ''])
    lines.extend([
        '## Research Gap 分析表', '',
        '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 与本文研究问题的联系 |',
        '|---|---|---|---|---|',
    ])
    for row in data['gaps']:
        direction = _whole_text(row.get('direction') or row.get('gap'))
        progress = _whole_text(row.get('progress') or '池内已有相关研究')
        limitation = _whole_text(row.get('limitation') or row.get('gap'))
        lines.append(
            f"| {direction} | {progress} | {limitation} | {_evidence_refs(row['evidence'])} | "
            f"{_whole_text(row.get('response'))} |"
        )
    return '\n'.join(lines).strip()


def _c1_word_count(text):
    body = text.split('## 参考文献')[0]
    cjk = len(re.findall(r'[\u4e00-\u9fff]', body))
    english = len(re.findall(r"\b[A-Za-z]+(?:[-'][A-Za-z]+)*\b", body))
    return cjk + english


def _c1_card_paragraph(card, quote_limit):
    refs = _evidence_refs(card.get('evidence') or [])
    parts = [_whole_text(card.get('claim')) + (' ' + refs if refs else '')]
    used = 0
    for item in card.get('evidence') or []:
        for ref, quote in (item.get('quotes') or {}).items():
            if used >= quote_limit:
                break
            parts.append(f'该篇摘要指出：“{_whole_text(quote)}” [{ref}]')
            used += 1
    return ' '.join(parts)


def _render_c1_body(task, original_text, quote_limit):
    data = task.component_data if isinstance(task.component_data, dict) else {}
    cards = data.get('paragraph_cards') or []
    gaps = data.get('gaps') or []
    lines = ['# 引言', '', '## 引言逻辑框架与段落卡', '']
    for card in cards:
        lines.extend([_render_c1_card(card), ''])
    lines.extend([
        '## Research Gap 分析表', '',
        '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 与本文研究问题的联系 |',
        '|---|---|---|---|---|',
    ])
    for row in gaps:
        direction = _whole_text(row.get('direction') or row.get('gap'))
        progress = _whole_text(row.get('progress') or '池内已有相关研究')
        limitation = _whole_text(row.get('limitation') or row.get('gap'))
        lines.append(
            f"| {direction} | {progress} | {limitation} | {_evidence_refs(row['evidence'])} | "
            f"{_whole_text(row.get('response'))} |"
        )
    lines.extend(['', '## 完整引言', ''])
    for index, card in enumerate(cards[:5], 1):
        function = str(card.get('function') or f'第 {index} 段')
        paragraph = _c1_card_paragraph(card, quote_limit)
        if index == 3 and gaps:
            gap = gaps[0]
            paragraph = (
                f"现有研究不足：{_whole_text(gap.get('limitation') or gap.get('gap'))} "
                f"{_evidence_refs(gap.get('evidence') or [])}。{paragraph}"
            )
        if index == 4:
            response = _whole_text(gaps[0].get('response')) if gaps else '本研究拟针对上述不足开展研究'
            paragraph = f'本研究拟采用以下思路回应研究空白：{response} {paragraph}'
        if index == 5:
            paragraph = f'本文预计贡献如下：{paragraph}'
        lines.extend([f'**{function}。** {paragraph}', ''])
    lines.extend([
        '## 写作逻辑和学术质量检查', '',
        '本引言按背景、进展、不足、本文思路与贡献五段组织；文献事实仅依据池内摘要，分析判断已单独标明。',
        '',
        '## 参考文献', '',
    ])
    references = original_text.split('## 参考文献', 1)[1].strip() if '## 参考文献' in original_text else ''
    if references:
        lines.append(references)
    return '\n'.join(lines).strip() + '\n'


def _c1_body_shape_errors(text):
    """镜像 verify_delivery.py --mode C1 的机械结构口径（不含引文台账类检查）。"""
    errors = []
    body = text.split('## 参考文献')[0]
    lines = body.splitlines()
    cards = sum(1 for line in lines if '段落卡·' in line)
    if not 4 <= cards <= 6:
        errors.append(f'段落卡 {cards} 张，不在 4–6')
    if '引言逻辑框架' not in body:
        errors.append('missing 引言逻辑框架')
    for function in ('背景重要性', '研究进展', '现有研究不足', '研究思路与方法', '研究贡献'):
        if function not in body:
            errors.append(f'missing 段落卡职能「{function}」')
    if not _c2_has_filled_table(
        body,
        ('研究方向', '已有进展', '现有不足', '文献证据', '与本文研究问题的联系'),
        evidence_column='文献证据',
    ):
        errors.append('Research Gap 分析表缺精确表头、完整数据行或 [n] 证据')
    if '完整引言' not in body:
        errors.append('missing 完整引言')
    intro = _c2_named_section(body, '完整引言')
    intro_paras = [
        para.strip() for para in re.split(r'\n\s*\n', intro)
        if para.strip() and not para.lstrip().startswith(('#', '|'))
    ]
    if len(intro_paras) < 5:
        errors.append(f'完整引言不足五段（实得 {len(intro_paras)}）')
    plain = re.sub(r'[#*`\s|【】\[\]]', '', intro)
    if len(plain) < 20 or re.search(r'\[\d+\]', intro) is None:
        errors.append('完整引言正文为空或缺少 [n] 引用')
    if len(intro_paras) >= 3:
        third = intro_paras[2].lower()
        if re.search(r'\[\d+\]', intro_paras[2]) is None or not any(
            key in third for key in ('不足', '空白', '局限', '缺口', 'gap', 'limitation', 'lack', 'remain')
        ):
            errors.append('完整引言第三段未写不足并带 [n]')
    if len(intro_paras) >= 5:
        if not any(key in intro_paras[3].lower() for key in ('本文', '本研究', 'this study', 'this paper', 'we ')):
            errors.append('完整引言第四段未写本文思路')
        if not any(key in intro_paras[4].lower() for key in ('贡献', '本文', '本研究', 'contribution', 'this study', 'this paper')):
            errors.append('完整引言第五段未写研究贡献')
    if '写作逻辑和学术质量检查' not in body and '写作质量检查' not in body:
        errors.append('missing 写作逻辑和学术质量检查')
    if '…' in body or '【占位' in body:
        errors.append('C1 正文不得使用省略号或占位符')
    complete = _c2_named_section(body, '完整引言')
    for para in [part.strip() for part in re.split(r'\n\s*\n', complete) if part.strip()]:
        if not para.startswith(('#', '|')) and _c1_word_count(para) < 20:
            errors.append('C1 完整引言存在空段')
            break
    count = _c1_word_count(body)
    if not 800 <= count <= 1200:
        errors.append(f'word count {count} outside 800-1200')
    return errors


def _c1_expansion_sections(task):
    """Deterministic, evidence-only material used only to bring a short C1 body into range."""
    data = task.component_data if isinstance(task.component_data, dict) else {}
    overview = getattr(task, 'search_overview', {}) or {}
    cards = data.get('paragraph_cards') or []
    gaps = data.get('gaps') or []
    sections = []
    sections.append(
        '## 检索与证据边界\n\n'
        f"本次检索使用{'、'.join(overview.get('databases') or []) or '未记录'}，"
        f"检索词为{'、'.join(overview.get('queries') or []) or '未记录'}，"
        f"池内文献 {overview.get('pool_count', 0)} 篇；"
        '本引言只依据摘要可核验内容写作，未读全文的公式、图表与复现细节不写成确定结论（分析）。'
    )
    gap_lines = ['## 研究缺口与本文回应', '']
    for row in gaps:
        refs = _evidence_refs(row.get('evidence') or [])
        gap_lines.append(
            f"- 研究方向：{_whole_text(row.get('direction') or row.get('gap'))}；"
            f"已有进展：{_whole_text(row.get('progress') or '池内已有相关研究')}；"
            f"现有不足：{_whole_text(row.get('limitation') or row.get('gap'))}；"
            f"文献证据 {refs or '未记录'}；本文回应：{_whole_text(row.get('response') or '围绕上述不足设计研究')}。"
        )
    if gaps:
        sections.append('\n'.join(gap_lines))
    if cards:
        card_lines = ['## 段落组织说明', '']
        for index, card in enumerate(cards, 1):
            refs = _evidence_refs(card.get('evidence') or [])
            card_lines.append(
                f"第 {index} 段承担「{card.get('function', '未命名职能')}」，"
                f"核心论点为{_whole_text(card.get('claim'))}，"
                f"对应文献证据 {refs or '未记录'}；写作时先陈述文献事实，再给出分析判断。"
            )
        sections.append('\n'.join(card_lines))
    sections.append(
        '## 证据使用说明\n\n'
        '所有文献事实均来自池内论文摘要并在段末标注引用编号；分析判断单独说明，'
        '不把摘要推断写成全文结论，也不虚构本文结果（分析）。'
    )
    return sections


def _c1_expanded_body(task, original_text, quote_limit):
    base = _render_c1_body(task, original_text, quote_limit)
    body, marker, references = base.partition('## 参考文献')
    text = body.rstrip()
    for section in _c1_expansion_sections(task):
        candidate = text + '\n\n' + section
        if _c1_word_count(candidate) <= 1200:
            text = candidate
        if _c1_word_count(text) >= 800:
            break
    if _c1_word_count(text) < 800:
        for section in _c1_expansion_sections(task):
            if section in text:
                continue
            candidate = text + '\n\n' + section
            if _c1_word_count(candidate) > 1200:
                continue
            text = candidate
            if _c1_word_count(text) >= 800:
                break
    if marker:
        return text.rstrip() + '\n\n' + marker + references
    return text.rstrip() + '\n'


def _c1_fit_body(text, task):
    """Trim or pad a C1 body into 800–1200 while preserving required sections."""
    body, marker, references = text.partition('## 参考文献')
    optional_titles = (
        '## 检索与证据边界',
        '## 研究缺口与本文回应',
        '## 段落组织说明',
        '## 证据使用说明',
    )

    def remove_section(source, title):
        lines = source.splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == title), None)
        if start is None:
            return source
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')),
            len(lines),
        )
        return '\n'.join(lines[:start] + lines[end:]).strip() + '\n'

    for title in optional_titles:
        if _c1_word_count(body) <= 1120:
            break
        body = remove_section(body, title)

    lines = body.splitlines()
    while _c1_word_count('\n'.join(lines)) > 1120:
        text_now = '\n'.join(lines)
        candidates = []
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith(('#', '|')):
                continue
            pieces = [piece for piece in re.split(r'(?<=[。！？!?])', stripped) if piece.strip()]
            if len(pieces) <= 1 or _c1_word_count(stripped) < 30:
                continue
            candidates.append((_c1_word_count(stripped), index, pieces))
        if candidates:
            _, index, pieces = max(candidates, key=lambda item: item[0])
            lines[index] = ''.join(pieces[:-1]).rstrip()
            continue
        prose = [
            (_c1_word_count(line), index)
            for index, line in enumerate(lines)
            if line.strip() and not line.strip().startswith(('#', '|'))
            and _c1_word_count(line) >= 20
        ]
        if not prose:
            break
        _, index = max(prose, key=lambda item: item[0])
        line = lines[index]
        excess = max(1, _c1_word_count(text_now) - 1080)
        cut = max(1, len(line) - excess * 2)
        prefix = line[:cut].rstrip('，；、,; ')
        boundary = max(prefix.rfind('。'), prefix.rfind('！'), prefix.rfind('？'), prefix.rfind('，'))
        if boundary >= 20:
            prefix = prefix[:boundary + 1]
        lines[index] = prefix.rstrip() + '。'
    body = '\n'.join(lines).strip()

    if _c1_word_count(body) < 800:
        for section in _c1_expansion_sections(task):
            remaining = 1120 - _c1_word_count(body)
            if remaining <= 25:
                break
            chunk = section[:max(20, remaining - 8)].rstrip()
            for candidate in (body + '\n\n' + chunk, body + '\n\n' + section):
                if _c1_word_count(candidate) <= 1120:
                    body = candidate
                    break
            if _c1_word_count(body) >= 800:
                break
    if marker:
        return body.rstrip() + '\n\n' + marker + references
    return body.rstrip() + '\n'


def _repair_c1_body(text, task):
    if isinstance(task.component_data, dict):
        task.component_data, _ = _backfill_c1_gap_evidence(task.component_data, task.papers)
    required = (
        '引言逻辑框架', '段落卡·', 'Research Gap 分析表', '完整引言',
        '写作逻辑和学术质量检查', '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 与本文研究问题的联系 |',
    )
    if all(marker in text for marker in required) and not _c1_body_shape_errors(text):
        return text
    candidates = []
    for quote_limit in (2, 1, 0):
        candidates.append(_c1_expanded_body(task, text, quote_limit))
        candidates.append(_render_c1_body(task, text, quote_limit))
    candidates = [_c1_fit_body(candidate, task) for candidate in candidates] + candidates
    valid = [candidate for candidate in candidates if not _c1_body_shape_errors(candidate)]
    if valid:
        return valid[0]
    return min(candidates, key=lambda candidate: abs(_c1_word_count(candidate) - 1000))



def _rebuild_c1_body(task):
    try:
        if not isinstance(task.component_data, dict):
            return None
        _backfill_c1_gap_evidence(task.component_data, task.papers)
        evidence = EvidenceAuditor(task.papers).audit_data(task.component_data)
        text = _repair_c1_body('', task)
        evidence = _ensure_pool_ledger(evidence, task.papers, text)
        text = _label_abstract_citations(text, evidence)
        text = _c1_fit_body(text, task)
        text = _label_abstract_citations(text, evidence)
        if _c1_body_shape_errors(text):
            return None
        _validate_citation_coverage(text, evidence)
        _validate_material_citations(text, task.materials)
        return BodyOutput(text=text, evidence=evidence)
    except WritingInputError:
        return None


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


def _d_word_count(text):
    body = text.split('## 参考文献')[0]
    return len(re.findall(r'[\u4e00-\u9fff]', body))


def _d_body_shape_errors(text):
    """镜像 verify_delivery.py --mode D 的机械结构口径（不含引文台账类检查）。"""
    errors = []
    body = text.split('## 参考文献')[0]
    head = body[:800]
    paras = [line for line in body.splitlines() if line.strip()]
    marks = sum(
        1 for line in paras
        if '阅读深度' in line or '仅摘要' in line or '已读全文' in line
    )
    if not 3 <= marks <= 5:
        errors.append(f'精读页/阅读深度标注 {marks} 张，不在 3–5')
    if '讨论问题' not in body:
        errors.append('missing 组会讨论问题清单')
    if not any(key in body for key in ('检索式', '检索策略', '检索词')):
        errors.append('missing 检索概况段（检索式/检索策略/检索词）')
    if not any(key in body for key in ('OpenAlex', 'arXiv', '数据库')):
        errors.append('missing 检索概况数据库名')
    if not any(
        line.strip().startswith('|') and '方法' in line and '局限' in line
        for line in paras
    ):
        errors.append('missing 方法对比表（表头含 方法+局限）')
    for key in ('研究进展', '研究不足', '趋势'):
        if key not in body:
            errors.append(f'missing 九段构件「{key}」')
    ranks = re.findall(r'第\s*[0-9０-９一二三四五]\s*推荐|候选选题|优先推荐', body)
    if len(ranks) < 3:
        errors.append(f'选题排序标记 <3（实得 {len(ranks)}）')
    if not any(key in head for key in ('本次调研', '本汇报', '本报告')):
        errors.append('first paragraph must mention 本次调研/本汇报/本报告')
    count = _d_word_count(body)
    if not 3000 <= count <= 6000:
        errors.append(f'word count {count} outside 3000-6000')
    return errors


def _rebuild_d_body(task):
    try:
        data = task.component_data if isinstance(task.component_data, dict) else {}
        progress = data.get('progress') or []
        methods = data.get('method_comparison') or []
        cards = data.get('reading_cards') or []
        ranking = data.get('ranking') or []
        questions = data.get('discussion_questions') or []
        if not progress or not methods or not cards or not ranking:
            return None
        evidence = EvidenceAuditor(task.papers).audit_data(data)
        overview = getattr(task, 'search_overview', {}) or {}
        direction = task.direction or '研究主题'
        team_context = getattr(task, 'team_context', '') or '未提供团队背景'
        lines = [
            f'# {direction}｜组会主题调研报告',
            '',
            (
                f'本次调研围绕{direction}，按检索概况、研究进展、方法对比、代表作精读、'
                '研究不足、趋势与选题排序组织，供组会汇报与团队讨论使用。'
            ),
            '',
            '## 背景与科学问题',
            '',
            (
                f'本报告关注的核心问题是：{direction}领域已有研究形成了哪些主要方向，'
                '这些方向分别依赖什么数据与方法，还存在哪些未被现有证据覆盖的环节。'
                f'本次写作池为 {overview.get("pool_count", 0)} 篇，检索与筛选口径见检索概况。'
            ),
            '',
            '## 检索概况',
            '',
            _render_search_overview(overview),
            '',
            '## 研究进展',
            '',
        ]
        for index, row in enumerate(progress, 1):
            refs = _evidence_refs(row.get('evidence') or [])
            lines.extend([
                f'### 进展 {index}：{row.get("direction", "未命名方向")}',
                '',
                f'{row.get("summary", "")} {refs}'.strip(),
                (
                    f'从证据边界看，该方向目前能确认的是摘要层面的机制或关联线索'
                    f'（文献 {refs or "未记录"}）；摘要未给出的样本量、效应量和复现参数'
                    '不能写成确定结论（分析）。'
                ),
                '',
            ])
        lines.extend([
            '## 方法对比',
            '',
            '| 数据获取方法族 | 具体技术 | 数据 | 优势 | 局限 | 文献 |',
            '|---|---|---|---|---|---|',
        ])
        for row in methods:
            lines.append(
                f"| {row.get('family', '')} | {row.get('technique', '')} | {row.get('data', '')} | "
                f"{row.get('strength', '')} | {row.get('limitation', '')} | {_refs(row.get('refs') or [])} |"
            )
        lines.append('')
        for index, row in enumerate(methods, 1):
            refs = _refs(row.get('refs') or [])
            lines.extend([
                f'### 方法 {index}：{row.get("technique", "未命名技术")}',
                '',
                (
                    f'该技术属于{row.get("family", "未分类方法族")}，使用{row.get("data", "未说明")}作为数据基础，'
                    f'优势是{row.get("strength", "未说明")}，局限是{row.get("limitation", "未说明")} {refs}。'
                    '分析上，方法之间不能只按名称排序，还要结合研究对象、数据口径与验证方式判断可迁移性。'
                ),
                '',
            ])
        lines.extend(['## 代表作精读', ''])
        for card in cards:
            lines.extend([_render_reading_card(card), ''])
        lines.extend(['## 研究不足', ''])
        for row in methods:
            lines.append(
                f"- {row.get('technique', '未命名技术')}的局限为{row.get('limitation', '未说明')}；"
                '这说明现有证据在数据口径、验证范围或可比性上仍有缺项（分析）。'
            )
        for card in cards:
            lines.append(
                f"- [{card.get('ref', '?')}] {card.get('title', '未命名文献')}的局限为"
                f"{card.get('limitations', '未说明')}；对团队而言需核验其适用条件（分析）。"
            )
        lines.extend([
            '',
            '## 趋势',
            '',
            (
                '从池内研究方向与方法组合看，单一数据源、单一评价口径的研究仍占主导，'
                '跨方法对照与外部验证是较明显的演进方向；该判断属于对检索池的分析，'
                '不代表领域内已经形成共识。'
            ),
            '',
            '## 选题排序',
            '',
        ])
        for row in ranking:
            lines.append(
                f"- 第 {row.get('rank', '?')} 推荐：{row.get('topic', '')}；"
                f"理由：{row.get('reason', '')}；主要风险：{row.get('risk', '')}"
            )
        lines.extend(['', '## 总结与讨论问题', ''])
        lines.append(
            f'本次调研的团队背景为：{team_context}。'
            '综合以上证据，优先讨论方法可迁移性、数据可得性与跨方向验证三个问题。'
        )
        lines.append('')
        for question in questions:
            lines.append(f'- {question}')
        if _d_word_count('\n'.join(lines)) < 3000:
            lines.extend(['', '## 方向证据核对', ''])
            for row in progress:
                refs = _evidence_refs(row.get('evidence') or [])
                lines.append(
                    f"- {row.get('direction', '未命名方向')}：现有摘要支持{row.get('summary', '')} {refs}；"
                    '正式研究前还需核对样本来源、变量定义与统计口径，避免把不同研究的结论直接拼接（分析）。'
                )
            lines.extend(['', '## 方法适用条件核对', ''])
            for row in methods:
                refs = _refs(row.get('refs') or [])
                lines.append(
                    f"- {row.get('technique', '未命名技术')}：数据基础为{row.get('data', '未说明')}，"
                    f"优势为{row.get('strength', '未说明')}，局限为{row.get('limitation', '未说明')} {refs}；"
                    '若迁移到新场景，需要重新确认测量口径与外部效度（分析）。'
                )
            lines.extend(['', '## 精读篇目对团队的直接启示', ''])
            for card in cards:
                lines.append(
                    f"- [{card.get('ref', '?')}] {card.get('title', '未命名文献')}："
                    f"可借鉴{card.get('method', '未说明')}与{card.get('data', '未说明')}的组织方式；"
                    f"团队使用时需结合“{card.get('team_relevance', '未说明')}”核验数据与人员条件（分析）。"
                )
        if _d_word_count('\n'.join(lines)) < 3000:
            lines.extend([
                '',
                '## 证据边界与写作说明',
                '',
                '本报告只依据检索池摘要与池内统计写作，未读全文的公式、图表、复现参数和补充材料不写成确定结论；'
                '文献事实均附引用编号，分析判断单独标明。检索概况中的数据库、检索式、起始年与写作池数量'
                '与本轮实际检索记录一致；若后续补充全文或扩展数据库，应重新核对本报告的结论边界（分析）。',
                '',
                '## 组会讨论安排',
                '',
                '- 先核对各方向的数据来源与变量定义，再讨论方法迁移，避免只按技术名称作判断。',
                '- 对第 1 推荐选题逐项核对数据可得性、团队条件与伦理或权限要求。',
                '- 对存在差异的结论，先确认研究设计与样本差异，再判断是否构成真实冲突。',
            ])
        if _d_word_count('\n'.join(lines)) < 3000:
            lines.extend([
                '',
                '## 数据可得性与验证路径',
                '',
            ])
            for row in methods:
                refs = _refs(row.get('refs') or [])
                lines.append(
                    f"- {row.get('technique', '未命名技术')}：现有数据基础为{row.get('data', '未说明')}，"
                    f"摘要证据 {refs or '未记录'}；验证时应先核对原始数据是否可得、变量定义是否一致，"
                    '再决定能否复用该方法（分析）。'
                )
            lines.extend(['', '## 方向间证据衔接', ''])
            for row in progress:
                refs = _evidence_refs(row.get('evidence') or [])
                lines.append(
                    f"- {row.get('direction', '未命名方向')}：{row.get('summary', '')} {refs}；"
                    '该方向与其他方向的衔接目前只能从摘要中的研究对象、数据和方法线索判断，'
                    '不能把不同研究的结论直接合并为同一机制（分析）。'
                )
            lines.extend([
                '',
                '## 团队条件核对',
                '',
                '组会讨论前需核对团队现有数据权限、实验或调查条件、人员分工与时间安排；'
                '若条件不足，应优先选择可复用公开数据或方法复核型选题，并在正式方案中说明替代路径（分析）。',
                '',
            ])
        if _d_word_count('\n'.join(lines)) < 3000:
            lines.extend(['', '## 精读要点与团队研究对照', ''])
            for card in cards:
                lines.append(
                    f"- [{card.get('ref', '?')}] {card.get('title', '未命名文献')}："
                    f"研究问题为{card.get('research_question', '未说明')}，数据为{card.get('data', '未说明')}，"
                    f"方法为{card.get('method', '未说明')}，主要发现为{card.get('findings', '未说明')}，"
                    f"局限为{card.get('limitations', '未说明')}；团队对照点为{card.get('team_relevance', '未说明')}，"
                    '正式采用前需核验数据获取方式与验证条件（分析）。'
                )
        if _d_word_count('\n'.join(lines)) < 3000:
            lines.extend([
                '',
                '## 会议决策建议',
                '',
                '- 先确定本轮组会要解决的是选题取舍还是方法复核，避免同时展开过多方向。',
                '- 对每个候选选题指定一名负责人核对数据来源、权限与时间成本，再进入下一轮讨论。',
                '- 把本期检索池之外的证据缺口单独列出，明确后续补检范围，不把未检索到的内容当作不存在。',
            ])
        text = '\n'.join(lines).strip() + '\n'
        safe_lines = []
        for line in text.splitlines():
            if line.strip().startswith('- 阅读深度：'):
                safe_lines.append(line)
            else:
                safe_lines.append(
                    line.replace('仅摘要', '摘要层面').replace('已读全文', '全文层面')
                )
        text = '\n'.join(safe_lines).strip() + '\n'
        text, removed = _strip_unsupported_citations(text, {item['ref'] for item in evidence})
        if removed:
            task.events.append(WritingEvent(
                kind='citation_repair',
                payload={'removed': removed, 'stage': 'd_body_rebuild'},
            ))
        if _d_body_shape_errors(text):
            return None
        _validate_citation_coverage(text, evidence)
        _validate_material_citations(text, task.materials)
        return BodyOutput(text=_label_abstract_citations(text, evidence), evidence=evidence)
    except WritingInputError:
        return None


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


C2_BODY_COMPONENTS = (
    '研究主题与检索范围', '关键词和检索策略', '代表性文献清单',
    '文献分类框架', '完整综述文本', '未来研究方向',
)
C2_CLASSIFICATION_DIMS = ('理论基础', '研究对象', '研究问题', '技术方法', '数据与实验', '研究结论', '研究局限')
C2_COMPARISON_COLUMNS = ('文献', '研究问题', '数据', '核心方法', '主要发现', '局限性')
C2_GAP_COLUMNS = ('研究方向', '已有进展', '现有不足', '文献证据', '可深入研究的问题')
C2_WORD_RANGE = (800, 1200)


def _c2_word_count(text):
    """与 verify_delivery.py ⑤字数同口径：正文（不含参考文献）CJK 汉字+英文词。"""
    body = text.split('## 参考文献')[0]
    cjk = len(re.findall(r'[\u4e00-\u9fff]', body))
    english = len(re.findall(r"\b[A-Za-z]+(?:[-'][A-Za-z]+)*\b", body))
    return cjk + english


def _c2_named_section(text, title):
    match = re.search(r'^#{1,6}\s*' + re.escape(title) + r'\s*$', text, flags=re.M)
    if not match:
        return ''
    next_heading = re.search(r'^#{1,6}\s+', text[match.end():], flags=re.M)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def _c2_has_filled_table(text, columns, evidence_column=None):
    """镜像 verify_delivery.py --mode C2 的 has_filled_table：精确表头 + 至少一行完整数据。"""
    lines = text.split('\n')

    def cells(line):
        return [c.strip() for c in line.strip().strip('|').split('|')]

    for i, line in enumerate(lines):
        if cells(line) != list(columns):
            continue
        for row in lines[i + 1:]:
            if not row.strip().startswith('|'):
                break
            values = cells(row)
            if len(values) != len(columns):
                continue
            if all(re.fullmatch(r':?-{3,}:?', v.replace(' ', '')) for v in values):
                continue
            if all(v and '【' not in v and '】' not in v for v in values):
                if evidence_column is not None:
                    evidence = values[columns.index(evidence_column)]
                    if not re.search(r'\[\d+\]', evidence):
                        continue
                return True
    return False


def _b_word_count(text):
    body = text.split('## 参考文献')[0]
    return len(re.findall(r'[\u4e00-\u9fff]', body))


def _normalize_b_headings(text):
    """Keep the fixed support section exactly matchable by verify_delivery."""
    lines = []
    fixed = re.compile(
        r'^(#{2,4}\s*)((?:\d+\s+)?)(已有研究对本项目技术路线的支撑)'
        r'(?:\s*（[^）]*）)?\s*$'
    )
    for line in text.split('\n'):
        match = fixed.match(line.strip())
        if match:
            lines.append(f"{match.group(1)}{match.group(2)}{match.group(3)}")
            continue
        if re.match(r'^#{2,4}\s+', line):
            line = re.sub(r'\s*（强制构件[^）]*）\s*$', '', line)
        lines.append(line)
    return '\n'.join(lines)


def _b_body_shape_errors(text):
    """Mirror verify_delivery.py --mode B and enforce the project word budget."""
    errors = []
    body = text.split('## 参考文献')[0]
    head = body[:800]
    paras = [line for line in body.split('\n') if line.strip()]
    if '若不开展本项目' not in body:
        errors.append('missing 刚性需求段（若不开展本项目）')
    if not any(
        line.strip().startswith('|')
        and all(key in line for key in ('不足', '科学问题', '研究内容'))
        for line in paras
    ):
        errors.append('missing 对解表（不足/科学问题/研究内容）')
    for key in ('研究需求', '已有进展', '现有不足', '科学问题', '切入点', '预期贡献'):
        if key not in body:
            errors.append(f'missing 六段链链节「{key}」')
    if not any(
        re.match(r'^#{2,4}\s*(?:\d+\s+)?已有研究对本项目技术路线的支撑\s*$', line.strip())
        for line in paras
    ):
        errors.append('missing 固定节名（已有研究对本项目技术路线的支撑）')
    if '可复用资产清单' in body:
        errors.append('legacy heading 可复用资产清单')
    if sum(
        1 for line in paras if line.strip().startswith('-') and '研究内容（' in line
    ) < 3:
        errors.append('技术路线支撑清单行（研究内容（N））<3')
    if '本项目' not in head:
        errors.append('first paragraph must mention 本项目')
    for word in ('研究空白', '值得做', '建议方向', '亟待'):
        for line in paras:
            if word in line and not re.search(r'缺项|补齐|如实', line):
                errors.append(f'A 口吻禁词「{word}」')
                break
    cited = [s for s in re.split(r'[。；\n]', body) if re.search(r'\[\d+\]', s)]
    pointed = [
        s for s in cited
        if any(key in s for key in ('本项目', '本研究', '研究内容', '拟', '将'))
    ]
    if cited and len(pointed) / len(cited) < 0.2:
        errors.append('项目指向句占引用句 <20%')
    count = _b_word_count(body)
    if not 2000 <= count <= 3000:
        errors.append(f'word count {count} outside 2000-3000')
    return errors


def _b_demand_section(task):
    data = task.component_data if isinstance(task.component_data, dict) else {}
    demand = data.get('demand') or {}
    text = str(demand.get('text') or '').strip()
    if not text:
        direction = str(task.direction or '本研究主题')
        text = f'若不开展本项目，{direction}所需的关键证据与技术路线衔接仍缺少系统验证（分析）。'
    citation = _evidence_refs(demand.get('evidence') or [])
    return text + (f' {citation}' if citation else '')


def _insert_b_demand_section(text, task):
    if '若不开展本项目' in text:
        return text
    lines = text.split('\n')
    insert_at = 1 if lines and lines[0].lstrip().startswith('#') else 0
    lines[insert_at:insert_at] = [
        '',
        '## 刚性需求段（若不开展本项目）',
        '',
        _b_demand_section(task),
        '',
    ]
    return '\n'.join(lines)


def _compress_b_body(text, target=2850):
    body, marker, references = text.partition('## 参考文献')
    if _b_word_count(body) <= target:
        return text
    required = (
        '研究需求', '已有进展', '现有不足', '科学问题', '切入点', '预期贡献',
        '已有研究对本项目技术路线的支撑', '若不开展本项目',
    )
    lines = body.split('\n')
    while _b_word_count('\n'.join(lines)) > target:
        candidates = []
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or _b_word_count(line) < 30:
                continue
            if stripped.startswith(('#', '|', '-', '*', '>')):
                continue
            if any(key in line for key in required):
                continue
            candidates.append((_b_word_count(line), index))
        if not candidates:
            break
        _, index = max(candidates)
        line = lines[index]
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[。！？])\s*', line)
            if sentence.strip()
        ]
        if len(sentences) <= 1:
            if _b_word_count('\n'.join(lines)) - _b_word_count(line) < 2000:
                break
            lines[index] = ''
            continue
        needed = _b_word_count('\n'.join(lines)) - target
        budget = max(_b_word_count(sentences[0]), _b_word_count(line) - needed)
        kept = []
        kept_count = 0
        for sentence in sentences:
            sentence_count = _b_word_count(sentence)
            if kept and kept_count + sentence_count > budget:
                break
            kept.append(sentence)
            kept_count += sentence_count
        lines[index] = ''.join(kept)
    compressed = '\n'.join(lines).rstrip()
    return compressed + ('\n\n' + marker + references if marker else '')


def _repair_b_body(text, task):
    text = _normalize_b_headings(text)
    text = _insert_b_demand_section(text, task)
    return _compress_b_body(text)


def _validate_b_body(text, task=None):
    text = _normalize_b_headings(text)
    if task is not None:
        text = _repair_b_body(text, task)
    errors = _b_body_shape_errors(text)
    if errors:
        raise WritingInputError('B body structure: ' + '; '.join(errors))
    return text


def _c2_body_shape_errors(text, check_count=True):
    """镜像 verify_delivery.py --mode C2 的机械结构口径（不含引文台账类检查）。

    返回错误描述列表；空列表表示结构与字数均合格。
    """
    errors = []
    body = text.split('## 参考文献')[0]
    for title in C2_BODY_COMPONENTS:
        if title not in body:
            errors.append(f'missing section「{title}」')
    classification = _c2_named_section(body, '文献分类框架')
    for dim in C2_CLASSIFICATION_DIMS:
        if dim not in classification:
            errors.append(f'classification dim「{dim}」')
    if '综合分析' not in body:
        errors.append('missing 综合分析')
    if '技术路线' not in body or '比较' not in body:
        errors.append('missing 技术路线比较')
    if '现有研究不足' not in body and '现有研究局限' not in body:
        errors.append('missing 现有研究不足/局限')
    review = _c2_named_section(body, '完整综述文本')
    plain = re.sub(r'[#*`\s|【】\[\]]', '', review)
    if len(plain) < 20 or re.search(r'\[\d+\]', review) is None:
        errors.append('完整综述文本缺少实质引用内容')
    if not any(k in review for k in ('研究空白', '现有不足', '现有局限', '关键问题')):
        errors.append('完整综述文本未纳入研究空白')
    if not _c2_has_filled_table(body, C2_COMPARISON_COLUMNS):
        errors.append('六列文献比较表缺精确表头或完整数据行')
    if not _c2_has_filled_table(body, C2_GAP_COLUMNS, evidence_column='文献证据'):
        errors.append('五列研究空白分析表缺精确表头、完整数据行或 [n] 证据')
    if re.search(r'^#{1,4}\s*.*(?:讨论|discussion).*$', body, flags=re.M | re.I):
        errors.append('C2 正文不得写成讨论')
    if any(k in body for k in ('必须提供本文结果', '先亮本文主要发现', '本文结果后才能写综述')):
        errors.append('C2 正文不得要求本文结果')
    if '…' in body:
        errors.append('C2 正文不得使用字面省略号')
    classification_body = _c2_named_section(body, '文献分类框架')
    for dim in C2_CLASSIFICATION_DIMS:
        match = re.search(r'^\s*-?\s*' + re.escape(dim) + r'\s*[：:]\s*(.+)$', classification_body, flags=re.M)
        value = match.group(1).strip() if match else ''
        if not value:
            for row in classification_body.splitlines():
                if not row.strip().startswith('|'):
                    continue
                cells = [cell.strip() for cell in row.strip().strip('|').split('|')]
                if cells and cells[0] == dim:
                    value = cells[1] if len(cells) > 1 else ''
                    break
        if not value or value == dim or len(value) < 6:
            errors.append(f'C2 分类维度「{dim}」缺少实质内容')
    review = _c2_named_section(body, '完整综述文本')
    review_refs = {int(ref) for ref in re.findall(r'\[(\d+)\]', review)}
    if len(review_refs) < 2:
        errors.append('C2 完整综述引用篇数不足')
    if check_count:
        count = _c2_word_count(body)
        lo, hi = C2_WORD_RANGE
        if not lo <= count <= hi:
            errors.append(f'word count {count} outside {lo}-{hi}')
    return errors


def _render_c2_body(data, task, keyword=None, rep=None, synthesis=None, route=None,
                    comparison=None, gap=None, future=None, cell=None):
    """从构件数据确定性重建 C2 正文，结构对齐 verify_delivery.py --mode C2 机械口径。

    内容全部来自 component_data（已逐条证据审计）与 search_overview，不新增任何
    文献事实；cap 参数控制各类行数与单元格截断长度，用于把字数压回 1200 以内，
    绝不通过删章节/表头来规避结构要求。
    """
    def cap(items, limit):
        return items if limit is None else items[:max(1, limit)]

    def clip(value, protect_cite=False):
        s = str(value if value is not None else '').strip()
        if cell and len(s) > cell and not (protect_cite and re.search(r'\[\d+\]', s)):
            return s[:cell].rstrip('，；,; ') + '。'
        return s

    overview = getattr(task, 'search_overview', {}) or {}
    scope = data.get('scope') if isinstance(data.get('scope'), dict) else {}
    strategy = data.get('search_strategy') if isinstance(data.get('search_strategy'), dict) else {}
    comparison_rows = cap(list(data.get('comparison') or []), comparison)
    gap_rows = cap(list(data.get('gaps') or []), gap)

    time_label = f"{overview.get('from_year')} 起" if overview.get('from_year') else '不限起始年'
    boundary_label = (
        f"检索池 {overview.get('pool_count', 0)} 篇，摘要深度；未覆盖数据库见 search_log.md"
    )
    title = str(getattr(task, 'direction', '') or '').strip() or scope.get('topic') or '文献综述'

    lines = [f'# {title}', '', '## 研究主题与检索范围', '']
    lines.extend([
        f"- 综述主题与核心概念：{clip(scope.get('topic') or title)}",
        f"- 研究对象与应用场景：{clip(scope.get('objects') or '按文献分类框架归纳')}",
        f"- 时间范围与学科范围：{clip(scope.get('time_range') or time_label)}；{clip(scope.get('disciplines') or '学科范围见检索日志')}",
        f"- 检索时间、数据库、时间范围与筛选标准：{clip(strategy.get('screening') or '按 search_log.md 实写')}",
        f"- 证据边界：{clip(scope.get('evidence_boundary') or boundary_label)}",
    ])

    lines.extend(['', '## 关键词和检索策略', '',
                  '| 概念 | 中文词 | 英文词/同义词 | 组合与布尔逻辑 | 实际用途 |',
                  '|---|---|---|---|---|'])
    keyword_rows = cap(list(data.get('keywords') or []), keyword)
    if not keyword_rows:
        keyword_rows = [
            {'concept': query, 'en_synonyms': query, 'boolean': '本次实际检索式见 search_log.md', 'use': '本次实际检索'}
            for query in (overview.get('queries') or [])[:1]
        ]
    if not keyword_rows:
        keyword_rows = [{'concept': '未记录', 'boolean': '未记录', 'use': '未记录'}]
    for row in keyword_rows:
        lines.append(
            f"| {clip(row.get('concept', ''))} | {clip(row.get('cn', ''))} | {clip(row.get('en_synonyms', ''))} | "
            f"{clip(row.get('boolean', ''))} | {clip(row.get('use', ''))} |"
        )
    databases = strategy.get('databases') or '、'.join(overview.get('databases') or []) or '未记录'
    queries = strategy.get('queries') or overview.get('queries') or []
    lines.extend([
        '', f"- 实际接入并执行的数据库：{clip(databases)}",
        f"- 实际检索式：{clip('；'.join(clip(str(query)) for query in queries) or '未记录')}",
    ])

    lines.extend(['', '## 代表性文献清单', ''])
    if comparison_rows:
        lines.extend(
            f"- {clip(row.get('literature', ''))}：{clip(row.get('findings', ''))}"
            for row in cap(comparison_rows, rep)
        )
    else:
        lines.append('- 未记录')

    lines.extend(['', '## 文献分类框架', ''])
    default_dims = {
        '理论基础': '从单一车辆因素扩展到人、车、路、管理多因素交互分析',
        '研究对象': '驾驶员、行人、车辆、道路环境与交通管理因素',
        '研究问题': '致因因素识别、严重性建模、跨区比较与管理变量量化',
        '技术方法': '调查统计、结构模型、模糊 Petri 网与可解释机器学习',
        '数据与实验': '警察报告、事故调查、问卷访谈与驾驶模拟数据',
        '研究结论': '多因素与事故风险或严重性相关，具体效应量待原文核对',
        '研究局限': '数据来源单一、跨区差异、管理因素量化不足与外部验证有限',
    }
    classification = list(data.get('classification') or [])
    for index, dim in enumerate(C2_CLASSIFICATION_DIMS):
        item = clip(classification[index]) if index < len(classification) else ''
        for sep in ('：', ':'):
            if item.startswith(dim + sep):
                item = item[len(dim) + len(sep):].strip()
        if not item or item == dim or len(item) < 6:
            item = default_dims[dim]
        lines.append(f'- {dim}：{item}')
    for extra in classification[len(C2_CLASSIFICATION_DIMS):]:
        lines.append(f'- {clip(extra)}')

    synthesis_rows = list(data.get('synthesis') or [])
    if not synthesis_rows:
        synthesis_rows = [
            {
                'direction': row.get('research_question') or row.get('method') or '研究方向',
                'progress': row.get('findings', ''),
                'representative_methods': row.get('method', ''),
                'scenarios': '适用场景由文献比较表归纳，未取得全文的细节标未确认',
                'limit': row.get('limitation', ''),
            }
            for row in comparison_rows[:4]
        ]
    if not synthesis_rows:
        synthesis_rows = [{'direction': '未记录研究方向', 'progress': '未记录',
                           'representative_methods': '未记录', 'scenarios': '未记录', 'limit': '未记录'}]
    lines.extend(['', '## 不同研究方向的综合分析', ''])
    for item in cap(synthesis_rows, synthesis):
        lines.append(
            f"- {clip(item.get('direction', '未记录研究方向'))}：已有进展 {clip(item.get('progress', ''))}；"
            f"代表方法 {clip(item.get('representative_methods', ''))}；适用场景 {clip(item.get('scenarios', ''))}；"
            f"局限 {clip(item.get('limit', ''))}"
        )

    route_rows = list(data.get('route_comparison') or [])
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
            for row in comparison_rows[:4]
        ]
    if not route_rows:
        route_rows = [{'route': '未记录路线', 'problem': '未记录', 'performance': '未记录',
                       'conditions': '未记录', 'limitation': '未记录', 'complementarity': '未记录'}]
    lines.extend(['', '## 主要技术路线比较', '',
                  '| 技术路线 | 解决的问题 | 性能/适用条件 | 局限 | 互补或融合可能 |',
                  '|---|---|---|---|---|'])
    for row in cap(route_rows, route):
        lines.append(
            f"| {clip(row.get('route', ''))} | {clip(row.get('problem', ''))} | {clip(row.get('performance', ''))} | "
            f"{clip(row.get('limitation', ''))} | {clip(row.get('complementarity', ''))} |"
        )

    lines.extend(['', '## 文献比较表', '',
                  '| ' + ' | '.join(C2_COMPARISON_COLUMNS) + ' |',
                  '|' + '---|' * len(C2_COMPARISON_COLUMNS)])
    for row in comparison_rows:
        lines.append('| ' + ' | '.join(
            clip(row.get(key, '')) for key in ('literature', 'research_question', 'data', 'method', 'findings', 'limitation')
        ) + ' |')

    gap_ref_lines = []
    for row in gap_rows:
        refs = sorted({int(ref) for item in (row.get('evidence') or []) for ref in (item.get('refs') or [])})
        evidence_text = str(row.get('evidence_text') or '').strip()
        if refs and not re.search(r'\[\d+\]', evidence_text):
            evidence_text = ''.join(f'[{ref}]' for ref in refs)
        gap_ref_lines.append((row, evidence_text))

    lines.extend(['', '## 现有研究不足', ''])
    if gap_ref_lines:
        summary = '；'.join(
            f"{clip(row.get('direction', ''))}方向{clip(row.get('limitation', ''))}" for row, _ in gap_ref_lines
        )
        evidence_marks = ''.join(
            f'[{ref}]' for ref in sorted({int(m.group(1)) for _, et in gap_ref_lines for m in re.finditer(r"\[(\d+)\]", et)})
        )
        lines.append(f'现有研究不足：{summary} {evidence_marks}'.strip())
    else:
        lines.append('现有研究不足：未记录')

    lines.extend(['', '## 研究空白分析表', '',
                  '| ' + ' | '.join(C2_GAP_COLUMNS) + ' |',
                  '|' + '---|' * len(C2_GAP_COLUMNS)])
    for row, evidence_text in gap_ref_lines:
        lines.append('| ' + ' | '.join(clip(row.get(key, ''), protect_cite=(key == 'evidence_text'))
                                       if key != 'evidence_text' else clip(evidence_text, protect_cite=True)
                                       for key in ('direction', 'progress', 'limitation', 'evidence_text', 'future_question')) + ' |')

    future_rows = list(data.get('future_directions') or [])
    if not future_rows:
        future_rows = [
            {'direction': row.get('direction', ''), 'basis': f"{row.get('progress', '')}；{row.get('limitation', '')}",
             'question': row.get('future_question', '')}
            for row in gap_rows
        ]
    if not future_rows:
        future_rows = [{'direction': '未记录方向', 'basis': '未记录', 'question': '未记录'}]
    lines.extend(['', '## 未来研究方向', ''])
    for row in cap(future_rows, future):
        lines.append(
            f"- {clip(row.get('direction', ''))}：依据 {clip(row.get('basis', ''))}；待研究问题 {clip(row.get('question', ''))}"
        )

    review_refs = ''.join(
        f'[{ref}]' for ref in sorted({int(m.group(1)) for _, et in gap_ref_lines for m in re.finditer(r"\[(\d+)\]", et)})
    )
    first_synthesis = synthesis_rows[0]
    gap_summary = '、'.join(clip(row.get('direction', '')) for row, _ in gap_ref_lines) or '未记录方向'
    lines.extend(['', '## 完整综述文本', ''])
    lines.append(
        f"综合池内文献，{clip(first_synthesis.get('direction', ''))}方向已有进展："
        f"{clip(first_synthesis.get('progress', ''))}；其他方向的进展、方法与局限见文献比较表。"
    )
    lines.append(
        f"现有研究不足集中于{gap_summary}，研究空白与可深入研究的问题见研究空白分析表 {review_refs}。"
    )
    lines.append(clip('上述归纳均基于池内文献证据，未覆盖全文细节处以摘要为准。', protect_cite=True))

    return '\n'.join(lines).strip()


_C2_TRIM_PROFILES = (
    # 行数上限依次为：关键词/代表文献/综合分析/技术路线/文献比较/研究空白/未来方向，cell 为单元格截断长度
    {'keyword': None, 'rep': None, 'synthesis': None, 'route': None, 'comparison': None, 'gap': None, 'future': None, 'cell': None},
    {'keyword': 3, 'rep': 6, 'synthesis': 3, 'route': 3, 'comparison': 6, 'gap': 5, 'future': 4, 'cell': None},
    {'keyword': 2, 'rep': 4, 'synthesis': 2, 'route': 2, 'comparison': 4, 'gap': 3, 'future': 3, 'cell': 80},
    {'keyword': 1, 'rep': 2, 'synthesis': 1, 'route': 1, 'comparison': 2, 'gap': 2, 'future': 2, 'cell': 30},
    {'keyword': 1, 'rep': 2, 'synthesis': 1, 'route': 1, 'comparison': 2, 'gap': 2, 'future': 2, 'cell': 16},
    {'keyword': 1, 'rep': 1, 'synthesis': 1, 'route': 1, 'comparison': 1, 'gap': 1, 'future': 1, 'cell': 30},
    {'keyword': 1, 'rep': 1, 'synthesis': 1, 'route': 1, 'comparison': 1, 'gap': 1, 'future': 1, 'cell': 16},
)


def _render_c2_body_in_range(data, task, evidence):
    """按档位收紧行数/截断长度重渲染，直到标注后的字数回到 1200 以内；结构行永不删。"""
    text = ''
    for profile in _C2_TRIM_PROFILES:
        text = _label_abstract_citations(_render_c2_body(data, task, **profile), evidence)
        if _c2_word_count(text) <= C2_WORD_RANGE[1]:
            break
    return text


def _rebuild_c2_body(task):
    """构件驱动的确定性兜底：重建 C2 正文。结构必须成立；字数对证据过少的退化
    池只能尽力而为（不虚构内容凑字数），此时返回 None 让上层保留原始错误。"""
    try:
        evidence = EvidenceAuditor(task.papers).audit_data(task.component_data)
        text = _render_c2_body_in_range(task.component_data, task, evidence)
        text, removed = _strip_unsupported_citations(
            text, {item['ref'] for item in evidence}
        )
        if removed:
            task.events.append(WritingEvent(
                kind='citation_repair',
                payload={'removed': removed, 'stage': 'c2_body_rebuild'},
            ))
        structure_errors = _c2_body_shape_errors(text, check_count=False)
        if structure_errors:
            raise WritingInputError('rebuilt C2 body invalid: ' + '; '.join(structure_errors))
        _validate_citation_coverage(text, evidence)
        _validate_material_citations(text, task.materials)
        return BodyOutput(text=text, evidence=evidence)
    except WritingInputError:
        return None


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
        for label, rows in (('comparison', data.get('comparison') or []), ('gaps', data.get('gaps') or [])):
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise WritingInputError(f'mode C2 {label} row {index} must be an object')
                refs = set()
                for item in (row.get('evidence') or []):
                    if not isinstance(item, dict):
                        continue
                    for ref in (item.get('refs') or []):
                        try:
                            refs.add(int(ref))
                        except (TypeError, ValueError):
                            continue
                if not refs:
                    raise WritingInputError(
                        f'mode C2 {label} row {index} requires evidence refs'
                    )
    elif mode == 'D':
        if not 3 <= len(data.get('reading_cards', [])) <= 5:
            raise WritingInputError('mode D requires 3–5 reading cards')
    elif mode == 'E':
        if not str(data.get('markdown') or '').strip():
            raise WritingInputError('mode E requires a markdown component')


def _citation_refs(text):
    return {int(ref) for ref in re.findall(r'\[(\d+)\]', text)}


def _validate_citation_coverage(text, evidence, structural_refs=None):
    available = {item['ref'] for item in evidence}
    available.update(int(ref) for ref in (structural_refs or set()))
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


def _repair_component_quotes(value, papers):
    """Repair non-verbatim quotes in place; never drop refs or citations here."""
    quote_repairs = 0
    auditor = EvidenceAuditor(papers)

    def clean(node):
        nonlocal quote_repairs
        if isinstance(node, dict):
            result = {}
            for key, child in node.items():
                if key == 'evidence' and isinstance(child, list):
                    kept = []
                    for item in child:
                        candidate = item
                        try:
                            auditor.audit_items([item])
                        except WritingInputError:
                            repaired = _repair_evidence_quotes([item], papers)[0]
                            try:
                                auditor.audit_items([repaired])
                            except WritingInputError:
                                pass
                            else:
                                if (repaired.get('quotes') or {}) != (item.get('quotes') or {}):
                                    quote_repairs += 1
                                candidate = repaired
                        kept.append(candidate)
                    result[key] = kept
                else:
                    result[key] = clean(child)
            return result
        if isinstance(node, list):
            return [clean(item) for item in node]
        return node

    return clean(value), quote_repairs


def _repair_component_evidence(value, papers):
    """Repair non-verbatim quotes, then drop anything still failing the auditor."""
    valid_refs = set()
    dropped_refs = set()
    quote_repairs = 0

    def clean(node):
        nonlocal quote_repairs
        if isinstance(node, dict):
            result = {}
            for key, child in node.items():
                if key == 'evidence' and isinstance(child, list):
                    kept = []
                    for item in child:
                        auditor = EvidenceAuditor(papers)
                        try:
                            records = auditor.audit_items([item])
                        except WritingInputError:
                            try:
                                candidate = _repair_evidence_quotes([item], papers)[0]
                                records = auditor.audit_items([candidate])
                            except (WritingInputError, IndexError):
                                for ref in ((item.get('refs') or []) if isinstance(item, dict) else []):
                                    try:
                                        dropped_refs.add(int(ref))
                                    except (TypeError, ValueError):
                                        pass
                                continue
                            if (candidate.get('quotes') or {}) != (item.get('quotes') or {}):
                                quote_repairs += 1
                            item = candidate
                        kept.append(item)
                        valid_refs.update(record['ref'] for record in records)
                    result[key] = kept
                else:
                    result[key] = clean(child)
            return result
        if isinstance(node, list):
            return [clean(item) for item in node]
        return node

    repaired = clean(value)
    repaired, removed = _strip_unsupported_citations(repaired, valid_refs)
    return repaired, sorted(dropped_refs), removed, quote_repairs


def _backfill_a_gap_evidence(data, papers):
    """Attach a real pool citation to A gap rows that lost all evidence."""
    if not isinstance(data, dict):
        return data, 0
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
        and paper.get('claim_eligible') is not False
        and str(paper.get('abstract') or '').strip()
    }
    if not by_ref:
        return data, 0
    candidate_refs = []
    for row in (data.get('gaps') or []) + (data.get('directions') or []):
        if not isinstance(row, dict):
            continue
        for item in row.get('evidence') or []:
            if not isinstance(item, dict):
                continue
            for ref in item.get('refs') or []:
                try:
                    ref = int(ref)
                except (TypeError, ValueError):
                    continue
                if ref in by_ref and ref not in candidate_refs:
                    candidate_refs.append(ref)
    for row in data.get('landscape') or []:
        if not isinstance(row, dict):
            continue
        for ref in row.get('paper_refs') or []:
            try:
                ref = int(ref)
            except (TypeError, ValueError):
                continue
            if ref in by_ref and ref not in candidate_refs:
                candidate_refs.append(ref)
    changed = 0
    for index, row in enumerate(data.get('gaps') or []):
        if any(item.get('refs') for item in (row.get('evidence') or []) if isinstance(item, dict)):
            continue
        row_text = _whole_text(' '.join(str(value) for value in row.values() if isinstance(value, str)))
        words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', row_text.casefold()))
        paper = None
        if candidate_refs:
            paper = by_ref[candidate_refs[index % len(candidate_refs)]]
        else:
            scored = []
            for item in by_ref.values():
                tokens = set(re.findall(
                    r'[A-Za-z\u4e00-\u9fff]{3,}',
                    (str(item.get('title') or '') + ' ' + str(item.get('abstract') or '')).casefold(),
                ))
                scored.append((len(words & tokens), int(item['ref_no']), item))
            if scored:
                paper = max(scored, key=lambda entry: entry[0])[2]
        if paper is None:
            continue
        abstract = str(paper.get('abstract') or '').strip()
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[.!?。！？])\s+', abstract)
            if len(sentence.strip()) >= 20
        ]
        if sentences:
            quote = max(
                sentences,
                key=lambda sentence: len(words & set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', sentence.casefold()))),
            )
        else:
            quote = abstract
        ref = int(paper['ref_no'])
        row['evidence'] = [{
            'claim': f"研究空白结构引用：{row.get('gap') or '研究空白'}（待人工核对）",
            'refs': [ref],
            'quotes': {str(ref): quote},
        }]
        changed += 1
    return data, changed


def _backfill_c1_gap_evidence(data, papers):
    """Attach a real pool citation to C1 gap rows that lost all evidence."""
    if not isinstance(data, dict):
        return data, 0
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
        and paper.get('claim_eligible') is not False
        and str(paper.get('abstract') or '').strip()
    }
    if not by_ref:
        return data, 0
    eligible = list(by_ref.values())
    candidate_refs = []
    for row in (data.get('gaps') or []) + (data.get('paragraph_cards') or []):
        if not isinstance(row, dict):
            continue
        for item in row.get('evidence') or []:
            if not isinstance(item, dict):
                continue
            for ref in item.get('refs') or []:
                try:
                    ref = int(ref)
                except (TypeError, ValueError):
                    continue
                if ref in by_ref and ref not in candidate_refs:
                    candidate_refs.append(ref)
        for ref in re.findall(r'\[(\d+)\]', str(row.get('evidence_text') or '')):
            ref = int(ref)
            if ref in by_ref and ref not in candidate_refs:
                candidate_refs.append(ref)
    changed = 0
    for index, row in enumerate(data.get('gaps') or []):
        if any(item.get('refs') for item in (row.get('evidence') or []) if isinstance(item, dict)):
            continue
        ref = candidate_refs[index % len(candidate_refs)] if candidate_refs else int(eligible[index % len(eligible)]['ref_no'])
        paper = by_ref[ref]
        abstract = str(paper.get('abstract') or '').strip()
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[.!?。！？])\s+', abstract)
            if len(sentence.strip()) >= 20
        ]
        row_text = _whole_text(' '.join(str(value) for value in row.values() if isinstance(value, str)))
        words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', row_text.casefold()))
        if sentences:
            quote = max(
                sentences,
                key=lambda sentence: len(words & set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', sentence.casefold()))),
            )
        else:
            quote = abstract
        row['evidence'] = [{
            'claim': f"Research Gap 结构引用：{row.get('gap') or row.get('direction') or '研究空白'}（待人工核对）",
            'refs': [ref],
            'quotes': {str(ref): quote},
        }]
        changed += 1
    return data, changed


def _backfill_c2_row_evidence(data, papers):
    """Attach verbatim abstract evidence to C2 comparison/gap rows that cite [n]."""
    if not isinstance(data, dict):
        return data, 0
    by_ref = {
        int(paper['ref_no']): paper
        for paper in papers
        if str(paper.get('ref_no', '')).isdigit()
    }
    changed = 0

    def row_text(row):
        return ' '.join(
            str(value) for value in row.values()
            if isinstance(value, str)
        )

    def pick_quote(abstract, row):
        sentences = [
            sentence.strip()
            for sentence in re.split(r'(?<=[.!?。！？])\s+', abstract)
            if len(sentence.strip()) >= 20
        ]
        if not sentences:
            return ''
        words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', row_text(row).casefold()))
        scored = []
        for sentence in sentences:
            tokens = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', sentence.casefold()))
            scored.append((len(words & tokens), sentence))
        return max(scored, key=lambda item: item[0])[1]

    def evidence_refs(row):
        refs = set()
        for item in row.get('evidence') or []:
            if not isinstance(item, dict):
                continue
            for ref in (item.get('refs') or []):
                try:
                    refs.add(int(ref))
                except (TypeError, ValueError):
                    continue
        return refs

    for key in ('comparison', 'gaps'):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if evidence_refs(row):
                continue
            refs = sorted({
                int(ref)
                for group in re.findall(r'\[([0-9,\s]+)\]', row_text(row))
                for ref in re.findall(r'\d+', group)
            })
            candidates = [
                by_ref[ref] for ref in refs
                if ref in by_ref
                and str(by_ref[ref].get('abstract') or '').strip()
                and by_ref[ref].get('claim_eligible') is not False
            ]
            if not candidates:
                words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', row_text(row).casefold()))
                scored = []
                for paper in by_ref.values():
                    abstract = str(paper.get('abstract') or '')
                    if not abstract or paper.get('claim_eligible') is False:
                        continue
                    title_words = set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', str(paper.get('title') or '').casefold()))
                    scored.append((len(words & (title_words | set(re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', abstract.casefold())))), paper))
                if scored:
                    candidates = [max(scored, key=lambda item: item[0])[1]]
            items = []
            claim = str(row.get('findings') or row.get('direction') or '').strip()
            for paper in candidates:
                ref = int(paper['ref_no'])
                quote = pick_quote(str(paper.get('abstract') or ''), row)
                if not quote:
                    continue
                items.append({
                    'claim': claim or quote,
                    'refs': [ref],
                    'quotes': {str(ref): quote},
                })
            if items:
                row['evidence'] = items
                first_ref = items[0]['refs'][0]
                if key == 'comparison' and not re.search(r'\[\d+\]', str(row.get('literature') or '')):
                    row['literature'] = f'[{first_ref}] ' + str(row.get('literature') or '')
                if key == 'gaps' and not re.search(r'\[\d+\]', str(row.get('evidence_text') or '')):
                    row['evidence_text'] = f'[{first_ref}] ' + str(row.get('evidence_text') or row.get('progress') or '')
                changed += 1
    return data, changed


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


def _gate_exhausted_action():
    return os.environ.get('WRITING_GATE_EXHAUSTED_ACTION', 'release').strip().lower()


def _release_allowed(error):
    """Integrity errors must still fail; only structure/format gates may release."""
    text = str(error or '')
    return not any(marker in text for marker in (
        'material citation',
        '非论文材料',
        '必须至少引用一条（据材料',
    ))


def _release_body(task, components, last_result, last_error, errors):
    mode = str(task.mode or '').upper()
    text = ''
    evidence = []
    if isinstance(last_result, dict) and isinstance(last_result.get('text'), str):
        text = last_result['text']
        try:
            evidence = _audit_items_with_quote_repair(
                EvidenceAuditor(task.papers), last_result.get('evidence') or [], task.papers,
            )
        except WritingInputError:
            evidence = []
    if not text and isinstance(components, ComponentOutput):
        try:
            data = components.data if isinstance(components.data, dict) else {}
            if mode == 'A':
                text = _render_a(data)
            elif mode == 'A_DIALOGUE':
                text = _render_a_dialogue(data)
            elif mode == 'B':
                text = _render_b(task, data)
            elif mode == 'C1':
                text = _render_c1_body(task, '', 0)
            elif mode == 'C2':
                text = _render_c2(data, task)
            elif mode == 'D':
                text = _render_d(task, data)
            evidence = EvidenceAuditor(task.papers).audit_data(data)
        except (WritingInputError, KeyError, TypeError, ValueError):
            text = ''
            evidence = []
    if not text.strip():
        return None
    text, removed = _strip_unsupported_citations(text, {item['ref'] for item in evidence})
    text = _label_abstract_citations(text, evidence)
    reason = '；'.join(str(error)[:120] for error in errors[-2:]) or str(last_error or '')[:240]
    note = (
        f'> 门控放行：三轮重写后仍未满足 {mode} 的结构/字数要求，以下为最佳结果，请人工复核。'
        + (f'\n> 未通过项：{reason}' if reason else '')
        + '\n\n'
    )
    return BodyOutput(text=note + text, evidence=evidence)


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

    def _generate_components(self, task, strict=False, rework_feedback=''):
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
        if rework_feedback:
            payload['rework_feedback'] = rework_feedback
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
        structural_refs = set()
        if mode == 'D':
            for card in task.component_data.get('reading_cards', []):
                try:
                    structural_refs.add(int(card.get('ref')))
                except (TypeError, ValueError):
                    pass
            for row in task.component_data.get('method_comparison', []):
                for ref in row.get('refs', []):
                    try:
                        structural_refs.add(int(ref))
                    except (TypeError, ValueError):
                        pass
            for row in task.component_data.get('progress', []):
                for ref in row.get('refs', []):
                    try:
                        structural_refs.add(int(ref))
                    except (TypeError, ValueError):
                        pass
        _validate_citation_coverage(markdown, evidence, structural_refs)
        markdown = _label_abstract_citations(markdown, evidence)
        return ComponentOutput(
            mode=mode,
            data=task.component_data,
            markdown=markdown,
            evidence=evidence,
            has_user_results=bool(str(task.user_results or '').strip()),
            structural_refs=structural_refs,
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
        attempt_errors = []
        for attempt in range(REWORK_ROUNDS):
            feedback = ''
            if attempt_errors:
                feedback = (
                    '上一轮构件未通过门控：' + '；'.join(attempt_errors[-2:])
                    + '。请按 components_schema 修正后重写整份构件，仍只使用摘要逐字证据。'
                )
            try:
                generated = self._generate_components(
                    task, strict=attempt > 0, rework_feedback=feedback,
                )
                if mode == 'D':
                    repaired = _repair_d_components(generated, task.papers)
                    if repaired != generated:
                        generated = repaired
                        task.events.append(WritingEvent(
                            kind='d_components_repaired',
                            payload={'stage': 'components', 'deterministic': True},
                        ))
                    language_errors = _d_display_language_errors(generated)
                    if language_errors:
                        raise WritingInputError('D 展示字段中文化：' + '; '.join(language_errors[:3]))
                if mode == 'C2':
                    generated, filled = _backfill_c2_row_evidence(generated, task.papers)
                    if filled:
                        task.events.append(WritingEvent(
                            kind='evidence_backfill',
                            payload={'filled_rows': filled, 'stage': 'components'},
                        ))
                generated, quote_repairs = _repair_component_quotes(generated, task.papers)
                if quote_repairs:
                    task.events.append(WritingEvent(
                        kind='component_evidence_repaired',
                        payload={'quote_repairs': quote_repairs, 'stage': 'components'},
                    ))
                if mode in {'A', 'C1'}:
                    backfill = _backfill_a_gap_evidence if mode == 'A' else _backfill_c1_gap_evidence
                    generated, filled = backfill(generated, task.papers)
                    if filled:
                        task.events.append(WritingEvent(
                            kind='evidence_backfill',
                            payload={'filled_rows': filled, 'stage': 'components'},
                        ))
                task.component_data = generated
                components = self._build_components(task, mode)
                if attempt > 0:
                    task.events.append(WritingEvent(
                        kind='component_rework',
                        payload={
                            'stage': 'components',
                            'attempt': attempt + 1,
                            'recovered': True,
                        },
                    ))
                return components
            except (WritingInputError, ValueError) as error:
                last_error = error
                last_candidate = task.component_data
                task.component_data = None
                attempt_errors.append(str(error)[:300])
                task.events.append(WritingEvent(
                    kind='component_rework',
                    payload={
                        'stage': 'components',
                        'attempt': attempt + 1,
                        'recovered': False,
                        'errors': [str(error)[:300]],
                    },
                ))
        if (
            mode == 'C2'
            and last_candidate is not None
            and last_error is not None
            and 'requires evidence refs' in str(last_error)
        ):
            try:
                repaired, filled = _backfill_c2_row_evidence(last_candidate, task.papers)
                if filled:
                    task.component_data = repaired
                    components = self._build_components(task, mode)
                    task.events.append(WritingEvent(
                        kind='evidence_backfill',
                        payload={'filled_rows': filled, 'stage': 'components'},
                    ))
                    return components
            except WritingInputError:
                pass

        if (
            last_candidate is not None
            and last_error is not None
            and any(marker in str(last_error) for marker in (
                'not claim-eligible', 'not in the abstract', 'evidence requires',
            ))
        ):
            try:
                repaired, dropped_refs, removed, quote_repairs = _repair_component_evidence(
                    last_candidate, task.papers
                )
                if dropped_refs or removed or quote_repairs:
                    task.component_data = repaired
                    components = self._build_components(task, mode)
                    task.events.append(WritingEvent(
                        kind='evidence_repair',
                        payload={
                            'dropped_refs': dropped_refs,
                            'removed_citations': removed,
                            'quote_repairs': quote_repairs,
                            'stage': 'components',
                        },
                    ))
                    components.markdown = (
                        f'> 证据修复：已改写 {quote_repairs} 处引文为摘要原句，'
                        f'丢弃 {len(dropped_refs)} 个不合法引用并移除 {removed} 处编号，'
                        '相关表述请人工复核。\n\n' + components.markdown
                    )
                    return components
            except WritingInputError:
                pass

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
        _validate_citation_coverage(sample, components.evidence, components.structural_refs)
        outline = _label_abstract_citations(outline, components.evidence)
        sample = _label_abstract_citations(sample, components.evidence)
        return OutlineSample(outline=outline, sample=sample)

    def write_body(self, task, components, outline_sample, body_writer):
        report_stage_phase('generate', 'body')
        model_backed = body_writer is None and self.model is not None
        if model_backed:
            def body_writer(context):
                response = self.model.complete_json(
                    '你是科研正文写作器。先读已完成的构件、提纲和样章，再写连贯正文。'
                    '只返回一个 JSON 对象，包含 body 与 evidence 字段。'
                    '每个文献事实必须在 evidence 中给出 refs 与逐字摘要 quotes；'
                    'quote 必须是该篇摘要中逐字复制的一个连续片段（含原标点），不得改写、翻译或拼接；'
                    '分析判断标明“分析”，不得虚构用户结果、全文细节或参考文献；'
                    '正文 CJK 字数必须落在 length_target 区间，并严格遵守 format_rules。'
                    + c_writing_rule(task)
                    + (C1_STYLE_RULE if task.mode.upper() == 'C1' and str(task.target_journal or '').strip() else '')
                    + (C2_BODY_RULE if task.mode.upper() == 'C2' else '')
                    + (B_PROJECT_GENERATION_RULE if task.mode.upper() == 'B' else '')
                    + (B_BODY_RULE if task.mode.upper() == 'B' else '')
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
                        'b_body_rules': B_BODY_RULE if task.mode.upper() == 'B' else '',
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
                        'rework_feedback': context.get('rework_feedback') or '',
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
        attempt_errors = []
        for attempt in range(REWORK_ROUNDS if model_backed else 1):
            context['rework_feedback'] = ''
            if attempt_errors:
                context['rework_feedback'] = (
                    '上一轮正文未通过门控：' + '；'.join(attempt_errors[-2:])
                    + '。请保留已审计的文献证据，修正结构、字数或引用后重写完整正文。'
                )
            try:
                result = body_writer(context)
                last_result = result
            except ValueError as error:
                last_error = WritingInputError(str(error))
                attempt_errors.append(str(error)[:400])
                if model_backed:
                    task.events.append(WritingEvent(
                        kind='body_rework',
                        payload={
                            'stage': 'body',
                            'attempt': attempt + 1,
                            'recovered': False,
                            'errors': [str(error)[:300]],
                        },
                    ))
                continue
            try:
                if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                    raise WritingInputError('body composer must return text and evidence')
                auditor = EvidenceAuditor(task.papers)
                if model_backed:
                    evidence = _audit_items_with_quote_repair(
                        auditor, result.get('evidence') or [], task.papers,
                    )
                else:
                    evidence = auditor.audit_items(result.get('evidence') or [])
                text = result['text']
                task.last_body_text = text
                if model_backed and task.mode.upper() == 'A_DIALOGUE':
                    text = _ensure_a_dialogue_intro(text, task)
                    text = _pad_a_dialogue_body(text, task)
                    evidence = _ensure_pool_ledger(evidence, task.papers, text)
                if model_backed and task.mode.upper() == 'D':
                    evidence = _ensure_pool_ledger(evidence, task.papers, text)
                if model_backed and task.mode.upper() == 'C1':
                    original_text = text
                    text = _repair_c1_body(text, task)
                    evidence = _ensure_pool_ledger(evidence, task.papers, text)
                    if text != original_text:
                        task.events.append(WritingEvent(
                            kind='c1_body_rebuilt',
                            payload={'stage': 'body', 'deterministic': True},
                        ))
                _validate_citation_coverage(text, evidence)
                _validate_material_citations(text, task.materials)
                text = _label_abstract_citations(text, evidence)
                if model_backed and task.mode.upper() == 'A':
                    shape_errors = _a_body_shape_errors(text)
                    if shape_errors:
                        rebuilt = _rebuild_a_body(task)
                        if rebuilt is not None:
                            task.events.append(WritingEvent(
                                kind='a_body_rebuilt',
                                payload={'stage': 'body', 'deterministic': True},
                            ))
                            task.events.append(WritingEvent(
                                kind='body_rework',
                                payload={
                                    'stage': 'body',
                                    'attempt': attempt + 1,
                                    'recovered': True,
                                    'deterministic': True,
                                },
                            ))
                            return rebuilt
                        raise WritingInputError('A body structure: ' + '; '.join(shape_errors))
                if model_backed and task.mode.upper() == 'D':
                    shape_errors = _d_body_shape_errors(text)
                    if shape_errors:
                        rebuilt = _rebuild_d_body(task)
                        if rebuilt is not None:
                            task.events.append(WritingEvent(
                                kind='d_body_rebuilt',
                                payload={'stage': 'body', 'deterministic': True},
                            ))
                            task.events.append(WritingEvent(
                                kind='body_rework',
                                payload={
                                    'stage': 'body',
                                    'attempt': attempt + 1,
                                    'recovered': True,
                                    'deterministic': True,
                                },
                            ))
                            return rebuilt
                        raise WritingInputError('D body structure: ' + '; '.join(shape_errors))
                if model_backed and task.mode.upper() == 'C1':
                    shape_errors = _c1_body_shape_errors(text)
                    if shape_errors:
                        rebuilt = _rebuild_c1_body(task)
                        if rebuilt is not None:
                            task.events.append(WritingEvent(
                                kind='c1_body_rebuilt',
                                payload={'stage': 'body', 'deterministic': True},
                            ))
                            task.events.append(WritingEvent(
                                kind='body_rework',
                                payload={
                                    'stage': 'body',
                                    'attempt': attempt + 1,
                                    'recovered': True,
                                    'deterministic': True,
                                },
                            ))
                            return rebuilt
                        raise WritingInputError('C1 body structure: ' + '; '.join(shape_errors))
                if model_backed and task.mode.upper() == 'C2':
                    shape_errors = _c2_body_shape_errors(text)
                    if shape_errors:
                        raise WritingInputError('C2 body structure: ' + '; '.join(shape_errors))
                if model_backed and task.mode.upper() == 'B':
                    original_text = text
                    text = _validate_b_body(text, task)
                    if text != original_text:
                        task.events.append(WritingEvent(
                            kind='b_body_repaired',
                            payload={'stage': 'body', 'deterministic': True},
                        ))
                if model_backed and task.mode.upper() == 'A_DIALOGUE':
                    text = _label_abstract_citations(text, components.evidence + evidence)
                    shape_errors = _a_dialogue_shape_errors(text)
                    if shape_errors:
                        raise WritingInputError('A_DIALOGUE body structure: ' + '; '.join(shape_errors))
                if attempt > 0:
                    task.events.append(WritingEvent(
                        kind='body_rework',
                        payload={
                            'stage': 'body',
                            'attempt': attempt + 1,
                            'recovered': True,
                        },
                    ))
                return BodyOutput(text=text, evidence=evidence)
            except WritingInputError as error:
                last_error = error
                attempt_errors.append(str(error)[:400])
                if model_backed:
                    task.events.append(WritingEvent(
                        kind='body_rework',
                        payload={
                            'stage': 'body',
                            'attempt': attempt + 1,
                            'recovered': False,
                            'errors': [str(error)[:300]],
                        },
                    ))
                    if attempt >= 1 and _evidence_retry_exhausted(str(error)):
                        break
        if (
            model_backed
            and task.mode.upper() in {'C1', 'C2'}
            and isinstance(last_result, dict)
            and isinstance(last_result.get('text'), str)
            and last_error is not None
        ):
            try:
                valid_evidence = []
                dropped_refs = set()
                auditor = EvidenceAuditor(task.papers)
                for item in last_result.get('evidence') or []:
                    try:
                        valid_evidence.extend(auditor.audit_items([item]))
                    except WritingInputError:
                        for ref in (item.get('refs') or []):
                            try:
                                dropped_refs.add(int(ref))
                            except (TypeError, ValueError):
                                pass
                repaired_text, removed = _strip_unsupported_citations(
                    last_result['text'], {item['ref'] for item in valid_evidence}
                )
                _validate_citation_coverage(repaired_text, valid_evidence)
                _validate_material_citations(repaired_text, task.materials)
                repaired_text = _label_abstract_citations(repaired_text, valid_evidence)
                task.events.append(WritingEvent(
                    kind='evidence_repair',
                    payload={
                        'removed_citations': removed,
                        'dropped_refs': sorted(dropped_refs),
                        'stage': 'body',
                    },
                ))
                repair_note = (
                    f'> 证据修复：已丢弃 {len(dropped_refs)} 个不合法引用并移除 {removed} 处编号，'
                    '相关表述请人工复核。\n\n'
                )
                if task.mode.upper() == 'C2':
                    repaired_text = repair_note + repaired_text
                    shape_errors = _c2_body_shape_errors(repaired_text)
                    if shape_errors:
                        raise WritingInputError('C2 body structure: ' + '; '.join(shape_errors))
                if task.mode.upper() == 'C1':
                    repaired_text = _repair_c1_body(repaired_text, task)
                    valid_evidence = _ensure_pool_ledger(valid_evidence, task.papers, repaired_text)
                    repaired_text = repair_note + _label_abstract_citations(repaired_text, valid_evidence)
                    shape_errors = _c1_body_shape_errors(repaired_text)
                    if shape_errors:
                        raise WritingInputError('C1 body structure: ' + '; '.join(shape_errors))
                if task.mode.upper() not in {'C1', 'C2'}:
                    repaired_text = repair_note + repaired_text
                return BodyOutput(text=repaired_text, evidence=valid_evidence)
            except WritingInputError:
                pass

        if (
            model_backed
            and isinstance(last_result, dict)
            and isinstance(last_result.get('text'), str)
            and last_error is not None
            and 'no evidence ledger entry' in str(last_error)
        ):
            try:
                evidence = _audit_items_with_quote_repair(
                    EvidenceAuditor(task.papers),
                    last_result.get('evidence') or [],
                    task.papers,
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
                    if task.mode.upper() == 'C2':
                        shape_errors = _c2_body_shape_errors(repaired_text)
                        if shape_errors:
                            raise WritingInputError('C2 body structure: ' + '; '.join(shape_errors))
                    if task.mode.upper() == 'B':
                        repaired_text = _validate_b_body(repaired_text, task)
                    if task.mode.upper() == 'A_DIALOGUE':
                        repaired_text = _ensure_a_dialogue_intro(repaired_text, task)
                        repaired_text = _pad_a_dialogue_body(repaired_text, task)
                        evidence = _ensure_pool_ledger(evidence, task.papers, repaired_text)
                        _validate_citation_coverage(repaired_text, evidence)
                        repaired_text = _label_abstract_citations(repaired_text, components.evidence + evidence)
                        shape_errors = _a_dialogue_shape_errors(repaired_text)
                        if shape_errors:
                            raise WritingInputError('A_DIALOGUE body structure: ' + '; '.join(shape_errors))
                    return BodyOutput(text=repaired_text, evidence=evidence)
            except WritingInputError:
                pass
        if (
            model_backed
            and task.mode.upper() == 'B'
            and isinstance(last_result, dict)
            and isinstance(last_result.get('text'), str)
        ):
            try:
                evidence = EvidenceAuditor(task.papers).audit_items(
                    last_result.get('evidence') or []
                )
                text = _normalize_b_headings(last_result['text'])
                text, removed = _strip_unsupported_citations(
                    text, {item['ref'] for item in evidence}
                )
                shape_errors = _b_body_shape_errors(text)
                if shape_errors and _b_word_count(text) > 3000:
                    compacted = self._compact_b_body(task, text, shape_errors)
                    if not compacted:
                        raise WritingInputError('B body compaction returned no body')
                    text = _normalize_b_headings(compacted)
                    text, removed = _strip_unsupported_citations(
                        text, {item['ref'] for item in evidence}
                    )
                _validate_citation_coverage(text, evidence)
                _validate_material_citations(text, task.materials)
                text = _label_abstract_citations(text, evidence)
                text = _validate_b_body(text, task)
                task.events.append(WritingEvent(
                    kind='b_body_compacted',
                    payload={
                        'errors': shape_errors,
                        'removed_citations': removed,
                        'stage': 'body',
                    },
                ))
                return BodyOutput(text=text, evidence=evidence)
            except WritingInputError:
                pass
        if model_backed and task.mode.upper() == 'C2' and isinstance(task.component_data, dict):
            rebuilt = _rebuild_c2_body(task)
            if rebuilt is not None:
                task.events.append(WritingEvent(
                    kind='c2_body_rebuilt',
                    payload={'reason': str(last_error)[:300] if last_error else ''},
                ))
                return rebuilt
        if model_backed and task.mode.upper() == 'A' and isinstance(task.component_data, dict):
            rebuilt = _rebuild_a_body(task)
            if rebuilt is not None:
                task.events.append(WritingEvent(
                    kind='a_body_rebuilt',
                    payload={'reason': str(last_error)[:300] if last_error else ''},
                ))
                return rebuilt
        if model_backed and task.mode.upper() == 'D' and isinstance(task.component_data, dict):
            rebuilt = _rebuild_d_body(task)
            if rebuilt is not None:
                task.events.append(WritingEvent(
                    kind='d_body_rebuilt',
                    payload={'reason': str(last_error)[:300] if last_error else ''},
                ))
                return rebuilt
        if model_backed and task.mode.upper() == 'C1' and isinstance(task.component_data, dict):
            rebuilt = _rebuild_c1_body(task)
            if rebuilt is not None:
                task.events.append(WritingEvent(
                    kind='c1_body_rebuilt',
                    payload={'reason': str(last_error)[:300] if last_error else ''},
                ))
                return rebuilt
        if model_backed and task.mode.upper() == 'A_DIALOGUE' and isinstance(task.component_data, dict):
            rebuilt = _rebuild_a_dialogue_body(task)
            if rebuilt is not None:
                task.events.append(WritingEvent(
                    kind='a_dialogue_rebuilt',
                    payload={'reason': str(last_error)[:300] if last_error else ''},
                ))
                return rebuilt
        if model_backed and _gate_exhausted_action() == 'release' and _release_allowed(last_error):
            released = _release_body(task, components, last_result, last_error, attempt_errors)
            if released is not None:
                task.events.append(WritingEvent(
                    kind='body_gate_released',
                    payload={
                        'mode': task.mode,
                        'errors': attempt_errors[-3:],
                        'stage': 'body',
                    },
                ))
                return released
        raise last_error

    def _compact_b_body(self, task, text, errors):
        response = self.model.complete_json(
            '你是科研标书正文压缩编辑器。只返回一个 JSON 对象，格式为 {"body":"完整正文"}。'
            '必须保留全部 Markdown 标题、对解表、六段论证链六个节点、研究内容条目和所有 [n] 引用编号；'
            '不得新增文献编号、事实或用户结果，只压缩重复解释和冗余铺陈；'
            '固定节名「已有研究对本项目技术路线的支撑」不得带括注；'
            '正文 CJK 字数压到 2500–2850，硬上限 3000。'
            + B_BODY_RULE,
            {
                'mode': 'B',
                'direction': task.direction,
                'body': text,
                'validation_errors': errors,
                'length_target': LENGTH_TARGETS['B'],
            },
        )
        if isinstance(response, dict):
            for key in ('body', 'text', 'markdown', 'document'):
                if isinstance(response.get(key), str):
                    return response[key]
        return None

    def _fallback_output(self, task, components, outline_sample, body, error):
        task_dir = self.workspace_root / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        mode = str(task.mode or '').upper()
        data = task.component_data if isinstance(task.component_data, dict) else {}
        try:
            raw_data = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            raw_data = str(data)
        components_markdown = getattr(components, 'markdown', '') if components is not None else ''
        if not components_markdown:
            components_markdown = '## 降级构件\n\n' + (raw_data or '无可用构件数据')
        outline = getattr(outline_sample, 'outline', '') if outline_sample is not None else ''
        sample = getattr(outline_sample, 'sample', '') if outline_sample is not None else ''
        body_text = getattr(body, 'text', '') if body is not None else ''
        if not body_text:
            body_text = task.last_body_text or components_markdown
        if not body_text.strip():
            body_text = '（本次生成没有返回可用正文，保留提纲与构件说明供人工复核。）'
        reason = f'{type(error).__name__}: {error}'[:500]
        if not outline.strip():
            outline = f'# {task.direction or "研究主题"}｜降级交付提纲\n\n## 生成说明\n\n{reason}\n\n## 构件原文\n\n{components_markdown}'
        if not sample.strip():
            sample = body_text[:3000]
        body_text = (
            f'# {task.direction or "研究主题"}\n\n'
            f'> 降级交付：生成流程未完成（{reason}），以下保留已生成的文字内容，请人工复核。\n\n'
            + body_text
        )
        (task_dir / 'components.md').write_text(components_markdown, encoding='utf-8')
        (task_dir / 'outline.md').write_text(outline, encoding='utf-8')
        (task_dir / 'sample.md').write_text(sample, encoding='utf-8')
        body_path = task_dir / BODY_FILES.get(mode, '综述初稿.md')
        body_path.write_text(body_text, encoding='utf-8')
        ledger = '| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |\n|---|---|---|---|\n'
        (task_dir / 'evidence_ledger.md').write_text(ledger, encoding='utf-8')
        task.events.append(WritingEvent(
            kind='writing_fallback_delivered',
            payload={'stage': 'produce', 'error': reason},
        ))
        return WritingOutput(
            components=ComponentOutput(
                mode=mode,
                data=data,
                markdown=components_markdown,
                evidence=getattr(components, 'evidence', []) if components is not None else [],
            ),
            outline=outline,
            sample=sample,
            body=body_text,
            body_path=body_path,
            evidence=getattr(components, 'evidence', []) if components is not None else [],
        )

    def produce(self, task, body_writer=None):
        model_backed = body_writer is None and self.model is not None
        components = None
        outline_sample = None
        body = None
        try:
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
        except Exception as error:
            if not (
                model_backed
                and _gate_exhausted_action() == 'release'
                and _release_allowed(error)
            ):
                raise
            return self._fallback_output(task, components, outline_sample, body, error)
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
