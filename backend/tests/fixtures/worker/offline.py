"""Deterministic offline providers for the real RQ worker acceptance tests.

Only network/paid boundaries live here. Analysis, graph, writing, delivery and
verification remain the project's real implementations.
"""

import json
from copy import deepcopy
from pathlib import Path


FIXTURE_ROOT = Path(__file__).resolve().parent
PAPERS = json.loads((FIXTURE_ROOT / 'papers.json').read_text(encoding='utf-8'))['papers']

EVIDENCE_ONE = {
    'claim': '校准模型降低了城市内涝损失估计误差。',
    'refs': [1],
    'quotes': {'1': 'The calibrated model reduced urban flood loss estimation error.'},
}
EVIDENCE_TWO = {
    'claim': '车库调查描述了暴露与恢复。',
    'refs': [2],
    'quotes': {'2': 'The survey describes garage exposure and recovery across three districts.'},
}
DIALOGUE_CATEGORIES = [
    '理论创新型选题',
    '方法创新型选题',
    '研究对象拓展型选题',
    '数据与实证创新型选题',
    '机制解释型选题',
    '前沿交叉型选题',
    '应用需求驱动型选题',
]


def _json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _pool(records, request, scope):
    papers = deepcopy(records)
    for ref_no, paper in enumerate(papers, 1):
        paper['ref_no'] = ref_no
    return {
        'mode': request.mode,
        'scope': scope,
        'from_year': request.from_year if scope == 'limited' else None,
        'terms': list(request.terms),
        'extensions': list(request.extensions),
        'count': len(papers),
        'total_hits': len(papers),
        'papers': papers,
    }


class OfflineOpenAlex:
    """File-backed retrieval with independent limited/unlimited numbering."""

    def __init__(self, output_dir, requests=None):
        self.output_dir = Path(output_dir)
        self.requests = requests if requests is not None else []

    def run(self, request):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.requests.append({
            'terms': list(request.terms),
            'from_year': request.from_year,
            'mode': request.mode,
        })
        limited_records = [
            paper for paper in PAPERS
            if request.from_year is None or paper['year'] >= request.from_year
        ]
        pools = {
            'limited': _pool(limited_records, request, 'limited'),
            'unlimited': _pool(PAPERS, request, 'unlimited'),
        }
        for scope, pool in pools.items():
            raw_name = f'openalex_{scope}_selected.json'
            _json(self.output_dir / raw_name, {
                'source': 'offline-openalex-fixture',
                'total_hits': pool['total_hits'],
                'papers': pool['papers'],
            })
        _json(self.output_dir / 'papers.json', pools['limited'])
        _json(self.output_dir / 'papers_all.json', pools['unlimited'])
        (self.output_dir / 'search_log.md').write_text(
            '# Search log\n\n'
            '- Provider: offline OpenAlex fixture; no network request performed.\n'
            f"- Terms: {', '.join(request.terms)}\n"
            f'- Limited from year: {request.from_year}\n'
            f"- Limited count: {pools['limited']['count']}\n"
            f"- Unlimited count: {pools['unlimited']['count']}\n"
            '- prisma: false\n'
            '- systematic_review: false\n',
            encoding='utf-8',
        )
        pools['search_log'] = str(self.output_dir / 'search_log.md')
        return pools


def offline_stats(task_dir, terms, from_year):
    task_dir = Path(task_dir)
    year = {
        'total_hits': 3,
        'groups': [
            {'name': '2018', 'count': 1},
            {'name': '2024', 'count': 1},
            {'name': '2025', 'count': 1},
        ],
    }
    topics_all = {
        'total_hits': 3,
        'groups': [
            {'key': 'T-OFFLINE-LOSS', 'name': 'Loss calibration', 'name_zh': '损失校准', 'count': 2},
            {'key': 'T-OFFLINE-GARAGE', 'name': 'Garage resilience', 'name_zh': '车库韧性', 'count': 1},
        ],
    }
    topics_limited = {
        'total_hits': 2,
        'from_year': from_year,
        'groups': deepcopy(topics_all['groups']),
    }
    series = [
        {
            'total_hits': 2,
            'groups': [
                {'name': '2024', 'count': 1},
                {'name': '2025', 'count': 1},
            ],
        },
        {
            'total_hits': 1,
            'groups': [{'name': '2025', 'count': 1}],
        },
    ]
    _json(task_dir / 'stats_year.json', year)
    _json(task_dir / 'stats_topics_all.json', topics_all)
    _json(task_dir / 'stats_topics_limited.json', topics_limited)
    for index, item in enumerate(series, 1):
        _json(task_dir / f'stats_series_{index}.json', item)
    return {
        'year': year,
        'topics': {'all': topics_all, 'limited': topics_limited},
        'series': series,
        'terms': list(terms),
        'from_year': from_year,
        'provider': 'offline-statistics-fixture',
    }


def offline_reference_checker(papers_path, output_path):
    papers = json.loads(Path(papers_path).read_text(encoding='utf-8'))['papers']
    Path(output_path).write_text(
        '# 著录核验\n\n'
        f'离线边界：仅核对本地 JSON 可解析及 {len(papers)} 条记录具有题录字段；'
        '未访问 Crossref、DataCite 或其他在线注册库。\n',
        encoding='utf-8',
    )
    return {'clean': True, 'issues': []}


def _dialogue_components():
    groups = []
    for category_index, category in enumerate(DIALOGUE_CATEGORIES, 1):
        slots = []
        for slot_index in (1, 2):
            slots.append({
                'title': f'{category}方向 {slot_index}',
                'core_question': f'围绕{category}，如何核对暴露恢复信息与损失校准口径并形成可检验问题？',
                'data_availability': '池内模型与调查摘要提供线索，原始数据公开性未确认。',
                'research_value': '有助于区分文献事实、候选机制与待验证方案。',
                'feasibility': '可先开展数据字典和口径核对，后续实验条件未确认。',
                'innovation_potential': '候选创新来自跨证据链衔接，而非预设模型优势。',
                'implementation_difficulty': '变量映射和独立验证存在不确定性。',
                'rank': slot_index,
                'opportunity': f'{category}可连接模型误差和地下空间过程，属于分析判断。',
                'risk': '摘要之外的方法细节和数据可得性尚未确认。',
                'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
            })
        groups.append({'category': category, 'slots': slots})
    return {
        'landscape': [
            {'direction': '损失校准', 'paper_refs': [1], 'share': '池内限定范围文献', 'venues': 'Offline Urban Water Studies'},
            {'direction': '车库暴露与恢复', 'paper_refs': [2], 'share': '池内限定范围文献', 'venues': 'Offline Cities and Resilience'},
        ],
        'gaps': [
            {'gap': '暴露恢复信息尚未在摘要中进入损失校准', 'reason': '变量映射与模型输入未确认', 'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)]},
            {'gap': '调查指标与损失记录缺少公开数据字典', 'reason': '数据口径可能影响联合分析', 'evidence': [deepcopy(EVIDENCE_TWO)]},
            {'gap': '联合校准是否改善表现尚无本文验证', 'reason': '不能把文献互补等同于实际效果', 'evidence': [deepcopy(EVIDENCE_ONE)]},
        ],
        'topic_groups': groups,
        'overall_first': {
            'topic': '方法创新型选题方向 1',
            'reason': '优先核对变量映射，再验证联合校准，能够直接回应池内空白并保留否定结果。',
            'risk': '原始数据和全文方法未确认，联合分析可能不可行。',
            'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
        },
    }


def _c1_components():
    functions = ['背景重要性', '研究进展', '现有研究不足', '研究思路与方法', '研究贡献']
    return {
        'paragraph_cards': [
            {
                'function': function,
                'claim': f'{function}围绕损失校准与车库暴露恢复的证据衔接展开。',
                'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
            }
            for function in functions
        ],
        'gaps': [
            {
                'gap': '两类摘要未说明联合校准。',
                'response': '本文拟先核对变量映射再检验模型回应。',
                'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
            },
        ],
    }


def _c2_components():
    return {
        'classification': ['损失校准', '车库暴露与恢复调查'],
        'comparison': [
            {
                'literature': '[1]',
                'research_question': '损失估计误差',
                'data': '摘要未说明',
                'method': '模型校准',
                'findings': '误差降低 [1]',
                'limitation': '暴露恢复输入未确认',
                'evidence': [deepcopy(EVIDENCE_ONE)],
            },
            {
                'literature': '[2]',
                'research_question': '车库暴露与恢复',
                'data': '摘要提及调查',
                'method': '调查研究',
                'findings': '描述暴露恢复 [2]',
                'limitation': '损失模型联动未确认',
                'evidence': [deepcopy(EVIDENCE_TWO)],
            },
        ],
        'gaps': [
            {
                'direction': '联合损失评估',
                'progress': '模型与调查分别提供证据',
                'limitation': '缺少联合校准说明',
                'evidence_text': '[1][2]',
                'future_question': '如何形成可追溯的变量映射和校准约束？',
                'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
            },
        ],
    }


def _a_dialogue_body(components):
    lines = [
        '# 领域格局与七类双槽选题',
        '',
        '本对话以限定范围的两篇摘要为事实边界，把模型校准和车库调查分开呈现，再将二者的未衔接处转化为候选研究方向。',
        '',
        '- 校准模型研究报告了城市内涝损失估计误差降低 [1]。',
        '- 车库调查研究报告了地下空间暴露与恢复现象 [2]。',
        '- 研究空白：损失校准摘要没有说明如何接收车库暴露恢复信息 [1]。',
        '- 研究空白：车库调查摘要没有说明调查结果如何映射到损失模型 [2]。',
        '- 研究空白：两类摘要未共同证明联合校准的实际效果 [1][2]。',
        '- 综合判断：优先核对数据口径，再决定是否开展联合模型验证，属于分析而非文献结论。',
        '',
        '## 研究空白与要点',
        '',
        '| 研究空白 | 机制/数据/方法/需求理由 | 文献证据 |',
        '|---|---|---|',
    ]
    for gap in components['gaps']:
        lines.append(f"| {gap['gap']} | {gap['reason']} | [1][2] |")
    for category_index, group in enumerate(components['topic_groups'], 1):
        lines.extend(['', f"## {category_index}. {group['category']}", ''])
        for slot_index, slot in enumerate(group['slots'], 1):
            lines.extend([
                f"选题 {slot_index}｜类内第 {slot_index} 推荐：{slot['title']}",
                f"- 核心研究问题：{slot['core_question']}",
                f"- 文献依据与机会：{slot['opportunity']} [1][2]",
                f"- 数据可得性：{slot['data_availability']}",
                f"- 研究价值：{slot['research_value']}（分析）",
                f"- 可行性：{slot['feasibility']}（分析）",
                f"- 创新潜力：{slot['innovation_potential']}（分析）",
                f"- 实施难度：{slot['implementation_difficulty']}（分析）",
                f"- 主要风险：{slot['risk']}",
                '',
            ])
    first = components['overall_first']
    lines.extend([
        '## 综合第 1 推荐',
        '',
        f"推荐选题：{first['topic']} [1][2]",
        f"推荐理由：{first['reason']}",
        f"主要风险：{first['risk']}",
        '',
        '以上选题均为基于池内摘要的分析候选；在获得全文、原始数据和本文实验前，不宣称任何候选方向已经有效。',
    ])
    return '\n'.join(lines)


class OfflineQwen:
    """Prompt-compatible deterministic replacement; never performs API calls."""

    def __init__(self):
        self.calls = []

    def complete_json(self, system_prompt, payload):
        stage = payload.get('stage')
        if stage is None and system_prompt.startswith('Classify'):
            stage = 'classify'
        elif stage is None and system_prompt.startswith('Extract factor'):
            stage = 'factor_votes'
        elif stage is None and system_prompt.startswith('Compare only'):
            stage = 'relations'
        self.calls.append({
            'stage': stage,
            'mode': payload.get('mode'),
            'paper_refs': [paper.get('ref') for paper in payload.get('papers', [])],
        })

        if stage == 'classify':
            clusters = []
            methods = []
            for paper in payload['papers']:
                abstract = paper['abstract']
                if 'calibrated model' in abstract:
                    cluster = '损失校准'
                    family = '计算建模与仿真'
                    technique = '损失模型校准'
                    key = 'loss_calibration'
                elif 'survey' in abstract:
                    cluster = '车库暴露与恢复'
                    family = '问卷调查与观察性数据'
                    technique = '车库暴露恢复调查'
                    key = 'garage_survey'
                else:
                    cluster = '排水规划'
                    family = '文献与二手数据'
                    technique = '规划证据归纳'
                    key = 'drainage_planning'
                clusters.append({
                    'ref': paper['ref'], 'name': cluster,
                    'quote': abstract, 'confidence': 'high',
                })
                methods.append({
                    'ref': paper['ref'], 'key': key, 'family': family,
                    'technique': technique, 'quote': abstract, 'confidence': 'high',
                })
            return {'clusters': clusters, 'methods': methods}

        if stage == 'factor_votes':
            votes = []
            for paper in payload['papers']:
                abstract = paper['abstract']
                if 'calibrated model' in abstract:
                    factor, outcome, polarity = '校准模型', '损失估计误差', 'neg'
                elif 'survey' in abstract:
                    factor, outcome, polarity = '车库调查', '暴露与恢复记录', 'pos'
                else:
                    factor, outcome, polarity = '排水规划', '内涝防备与恢复协调', 'pos'
                votes.append({
                    'factor': factor, 'outcome': outcome, 'polarity': polarity,
                    'ref': paper['ref'], 'quote': abstract, 'confidence': 'high',
                })
            return {'votes': votes}

        if stage == 'relations':
            papers = payload['papers']
            if len(papers) < 2:
                return {'relations': []}
            source, target = papers[0], papers[1]
            return {'relations': [{
                's': source['ref'], 't': target['ref'], 'type': 'difference',
                'reason': '两篇摘要的研究对象和输出不同，可构成经证据约束的差异关系。',
                'evidence_ref': source['ref'], 'quote': source['abstract'],
                'basis_ref': target['ref'], 'basis_quote': target['abstract'],
                'confidence': 'high',
            }]}

        if stage == 'components':
            mode = payload['mode']
            if mode == 'A_DIALOGUE':
                components = _dialogue_components()
            elif mode == 'C1':
                components = _c1_components()
            elif mode == 'C2':
                components = _c2_components()
            else:
                raise AssertionError(f'Unexpected offline component mode: {mode}')
            return {'components': components}

        if stage == 'body':
            mode = payload['mode']
            if mode == 'A_DIALOGUE':
                body = _a_dialogue_body(payload['components'])
            elif mode in {'C1', 'C2'}:
                body = (FIXTURE_ROOT / f'{mode.lower()}_body.md').read_text(encoding='utf-8')
            else:
                raise AssertionError(f'Unexpected offline body mode: {mode}')
            return {
                'body': body,
                'evidence': [deepcopy(EVIDENCE_ONE), deepcopy(EVIDENCE_TWO)],
            }

        raise AssertionError(f'Unexpected offline model stage: {stage}')
