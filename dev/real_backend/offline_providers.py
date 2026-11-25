"""Offline third-party boundaries for real HTTP/RQ acceptance only.

Application APIs, SQLite, Redis/RQ, graph generation, writing templates, delivery,
and Office generation remain the real implementations. No network or paid model
call is made by these providers.
"""
from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODE_ROOT = ROOT / 'backend' / 'tests' / 'fixtures' / 'modes'
SOURCE = json.loads((MODE_ROOT / 'B' / 'papers.json').read_text(encoding='utf-8'))
PAPERS = SOURCE['papers']


def load_fixture(mode):
    root = MODE_ROOT / mode
    return {
        'components': json.loads((root / 'components.json').read_text(encoding='utf-8')),
        'evidence': json.loads((root / 'evidence.json').read_text(encoding='utf-8')),
        'body_evidence': json.loads((root / 'body_evidence.json').read_text(encoding='utf-8')),
        'body': (root / 'body.md').read_text(encoding='utf-8'),
    }


FIXTURES = {mode: load_fixture(mode) for mode in ('B', 'C1', 'C2', 'D')}


def materialize(value, evidence):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'evidence':
                result[key] = [deepcopy(evidence[evidence_id]) for evidence_id in item]
            else:
                result[key] = materialize(item, evidence)
        return result
    if isinstance(value, list):
        return [materialize(item, evidence) for item in value]
    return value


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class OfflineHCCSearch:
    """Replace only OpenAlex retrieval; retain real merge and snapshot citations."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)

    def run(self, request):
        from app.search import merge_records

        self.output_dir.mkdir(parents=True, exist_ok=True)
        pools = {}
        for scope in ('limited', 'unlimited'):
            from_year = request.from_year if scope == 'limited' else None
            records = deepcopy(PAPERS)
            for record in records:
                record['_retrieval_rank'] = record['ref_no']
            pool = merge_records(records, from_year=from_year, mode=request.mode)
            # Real B/C/D merging may reorder records. Restore this snapshot's DOI
            # order so graph refs, generated evidence, and fixture citations agree.
            citation_order = {paper['doi']: index for index, paper in enumerate(PAPERS)}
            pool['papers'].sort(key=lambda paper: citation_order.get(paper.get('doi'), len(citation_order)))
            for ref_no, paper in enumerate(pool['papers'], 1):
                paper['ref_no'] = ref_no
            pool['count'] = len(pool['papers'])
            pool.update({
                'scope': scope,
                'terms': list(request.terms),
                'extensions': list(request.extensions),
                'total_hits': pool['count'],
            })
            write_json(self.output_dir / f'openalex_{scope}_selected.json', {
                'source': 'offline-hcc-openalex-snapshot',
                'online_retrieval': False,
                'papers': pool['papers'],
            })
            filename = 'papers.json' if scope == 'limited' else 'papers_all.json'
            write_json(self.output_dir / filename, pool)
            pools[scope] = pool
        (self.output_dir / 'search_log.md').write_text(
            '# Search log\n\n'
            '- Provider: project-owned HCC OpenAlex offline snapshot.\n'
            '- Online retrieval: false; no external request performed.\n'
            f'- Terms: {", ".join(request.terms)}\n'
            f'- Limited from year: {request.from_year}\n'
            f'- Limited count: {pools["limited"]["count"]}\n'
            f'- Unlimited count: {pools["unlimited"]["count"]}\n',
            encoding='utf-8',
        )
        pools['search_log'] = str(self.output_dir / 'search_log.md')
        # Keep a real observable searching interval for the polling assertion.
        time.sleep(1.2)
        return pools


TOPICS = ['髓系代谢与 S1P', 'IL-8/CXCR2 动态分层', '乳酸化与 PD-L1', '免疫微环境综述']
METHODS = ['NEK2/S1P 代谢干预', '动态单细胞 RNA 测序', '乳酸化与蛋白稳定性实验', '叙述性领域综合']
FACTORS = ['NEK2/S1P', 'IL-8/CXCR2', '乳酸化/MVP', '免疫微环境']
OUTCOMES = ['免疫治疗耐药', '髓系细胞迁移与应答', 'PD-L1 稳定性', '免疫逃逸与耐药框架']


class OfflineModel:
    def complete_json(self, system_prompt, payload):
        if system_prompt.startswith('你是科研检索术语助手'):
            return {'candidates': [{
                'zh': '肝细胞癌免疫治疗耐药',
                'en': 'hepatocellular carcinoma immunotherapy resistance',
                'description': 'HCC 离线快照的固定检索词',
                'best_for': '本轮真实后端离线联调',
            }]}
        if system_prompt.startswith('Classify'):
            clusters, methods = [], []
            for paper in payload['papers']:
                index = paper['ref'] - 1
                clusters.append({'ref': paper['ref'], 'name': TOPICS[index], 'quote': paper['abstract'], 'confidence': 'high'})
                methods.append({
                    'ref': paper['ref'], 'key': f'hcc_method_{paper["ref"]}',
                    'family': '实验与干预' if paper['ref'] < 4 else '文献与二手数据',
                    'technique': METHODS[index], 'quote': paper['abstract'], 'confidence': 'high',
                })
            return {'clusters': clusters, 'methods': methods}
        if system_prompt.startswith('Extract factor'):
            return {'votes': [{
                'factor': FACTORS[paper['ref'] - 1],
                'outcome': OUTCOMES[paper['ref'] - 1],
                'polarity': 'pos', 'ref': paper['ref'],
                'quote': paper['abstract'], 'confidence': 'high',
            } for paper in payload['papers']]}
        if system_prompt.startswith('Compare only'):
            papers = payload['papers']
            if len(papers) < 2:
                return {'relations': []}
            left, right = papers[0], papers[1]
            return {'relations': [{
                's': left['ref'], 't': right['ref'], 'type': 'difference',
                'reason': '两篇摘要使用不同方法与机制层级；这是离线证据约束下的差异判断。',
                'evidence_ref': left['ref'], 'quote': left['abstract'],
                'basis_ref': right['ref'], 'basis_quote': right['abstract'],
                'confidence': 'high',
            }]}
        stage = payload.get('stage')
        if stage == 'components':
            mode = payload['mode']
            if mode == 'A_DIALOGUE':
                return {'components': self.dialogue_components(payload)}
            fixture = FIXTURES[mode]
            return {'components': materialize(fixture['components'], fixture['evidence'])}
        if stage == 'body':
            mode = payload['mode']
            if mode == 'A_DIALOGUE':
                return {
                    'body': self.dialogue_body(payload['components']),
                    'evidence': [deepcopy(FIXTURES['B']['evidence'][key]) for key in FIXTURES['B']['body_evidence']],
                }
            fixture = FIXTURES[mode]
            return {
                'body': fixture['body'],
                'evidence': [deepcopy(fixture['evidence'][key]) for key in fixture['body_evidence']],
            }
        raise AssertionError(f'Unexpected offline model request: {system_prompt[:80]} / {stage}')

    def dialogue_components(self, payload):
        evidence = FIXTURES['B']['evidence']
        categories = ['理论创新型选题', '方法创新型选题', '研究对象拓展型选题', '数据与实证创新型选题', '机制解释型选题', '前沿交叉型选题', '应用需求驱动型选题']
        groups = []
        for index, category in enumerate(categories):
            slots = []
            for slot in (1, 2):
                slots.append({
                    'title': f'{category}：HCC 机制对解方向 {slot}',
                    'core_question': f'如何在同一证据边界内比较髓系代谢、IL-8/CXCR2 与乳酸化机制（方案 {slot}）？',
                    'data_availability': '仅有四篇公开摘要；原始数据与全文参数未提供。',
                    'research_value': '区分文献事实、跨研究分析与待验证假设。',
                    'feasibility': '可先核对方法、样本与指标，实验条件待团队确认。',
                    'innovation_potential': '候选创新来自机制对解，不宣称文献之外的疗效。',
                    'implementation_difficulty': '跨体系终点不同，需全文和数据字典。',
                    'rank': slot,
                    'opportunity': '池内摘要支持三条机制链，但未支持直接联合疗效。',
                    'risk': '跨研究外推和全文缺失是主要边界。',
                    'evidence': [deepcopy(evidence['s1p_resistance']), deepcopy(evidence['il8_mdsc'])],
                })
            groups.append({'category': category, 'slots': slots})
        return {
            'landscape': [
                {
                    'direction': TOPICS[index], 'paper_refs': [index + 1],
                    'share': '四篇离线池内文献', 'venues': PAPERS[index]['venue'],
                    'evidence': [deepcopy(evidence[key])],
                }
                for index, key in enumerate(('s1p_resistance', 'il8_mdsc', 'lactylation_targeting', 'microenvironment'))
            ],
            'gaps': [
                {'gap': '三条机制链未在同一实验体系内联合验证', 'reason': '研究对象、方法和终点不同', 'evidence': [deepcopy(evidence['s1p_resistance']), deepcopy(evidence['il8_mdsc'])]},
                {'gap': '循环指标与组织机制的外推边界未解决', 'reason': '关联与因果证据层级不同', 'evidence': [deepcopy(evidence['il8_association'])]},
                {'gap': '联合干预效果没有池内摘要支持', 'reason': '不能把互补机制等同于协同疗效', 'evidence': [deepcopy(evidence['lactylation_targeting'])]},
            ],
            'topic_groups': groups,
            'overall_first': {
                'topic': '方法创新型选题：HCC 机制对解方向 1',
                'reason': '先统一问题、样本和终点，再进行机制比较，保留否定结果。',
                'risk': '需要全文、原始数据与实验资源，当前均未确认。',
                'evidence': [deepcopy(evidence['s1p_resistance']), deepcopy(evidence['il8_mdsc'])],
            },
        }

    def dialogue_body(self, components):
        lines = [
            '# 领域格局与七类双槽选题', '',
            '本对话仅使用四篇 HCC 离线摘要，把髓系代谢、IL-8/CXCR2、乳酸化和免疫微环境综述分别呈现，不将跨研究线索写成联合疗效。',
            '- S1P 机制与耐药有摘要证据 [1]。', '- IL-8/CXCR2 与髓系状态有摘要证据 [2]。', '- 乳酸化/MVP 与 PD-L1 稳定性有摘要证据 [3]。',
            '- 研究空白：三条机制链未在同一体系内联合验证 [1][2][3]。', '- 研究空白：循环指标与组织机制的外推边界仍需复核 [2]。', '- 研究空白：联合干预效果未由池内摘要建立 [1][3]。',
            '', '## 研究空白与要点', '', '| 研究空白 | 机制/数据/方法/需求理由 | 文献证据 |', '|---|---|---|',
        ]
        for gap in components['gaps']:
            lines.append(f'| {gap["gap"]} | {gap["reason"]} | [1][2][3] |')
        for group_index, group in enumerate(components['topic_groups'], 1):
            lines.extend(['', f'## {group_index}. {group["category"]}', ''])
            for slot_index, slot in enumerate(group['slots'], 1):
                lines.extend([
                    f'选题 {slot_index}｜类内第 {slot_index} 推荐：{slot["title"]}',
                    f'- 核心研究问题：{slot["core_question"]}',
                    f'- 文献依据与机会：{slot["opportunity"]} [1][2]',
                    f'- 数据可得性：{slot["data_availability"]}', f'- 研究价值：{slot["research_value"]}',
                    f'- 可行性：{slot["feasibility"]}', f'- 创新潜力：{slot["innovation_potential"]}',
                    f'- 实施难度：{slot["implementation_difficulty"]}', f'- 主要风险：{slot["risk"]}', '',
                ])
        first = components['overall_first']
        lines.extend(['## 综合第 1 推荐', '', f'推荐选题：{first["topic"]} [1][2]', f'推荐理由：{first["reason"]}', f'主要风险：{first["risk"]}', '', '所有候选均为摘要约束下的分析方案，不宣称已有实验验证。'])
        return '\n'.join(lines)


def offline_stats(task_dir, terms, from_year):
    task_dir = Path(task_dir)
    year_groups = [{'name': str(year), 'count': sum(paper['year'] == year for paper in PAPERS)} for year in sorted({paper['year'] for paper in PAPERS})]
    year = {'total_hits': len(PAPERS), 'groups': year_groups}
    topics_all = {'total_hits': len(PAPERS), 'groups': [{'key': f'T-HCC-{index}', 'name': topic, 'name_zh': topic, 'count': 1} for index, topic in enumerate(TOPICS, 1)]}
    topics_limited = {'total_hits': len(PAPERS), 'from_year': from_year, 'groups': deepcopy(topics_all['groups'])}
    series = [{'total_hits': 1, 'groups': [{'name': str(PAPERS[index]['year']), 'count': 1}]} for index in range(4)]
    for name, payload in [('stats_year.json', year), ('stats_topics_all.json', topics_all), ('stats_topics_limited.json', topics_limited)]:
        write_json(task_dir / name, payload)
    for index, item in enumerate(series, 1):
        write_json(task_dir / f'stats_series_{index}.json', item)
    return {'year': year, 'topics': {'all': topics_all, 'limited': topics_limited}, 'series': series, 'terms': list(terms), 'from_year': from_year, 'provider': 'offline-hcc-statistics'}


def offline_reference_checker(papers_path, output_path):
    papers = json.loads(Path(papers_path).read_text(encoding='utf-8'))['papers']
    issues = []
    for paper in papers:
        for field in ('title', 'authors', 'year', 'venue', 'doi', 'abstract'):
            if not paper.get(field):
                issues.append(f'ref {paper["ref_no"]} missing {field}')
        if not re.fullmatch(r'https://doi\.org/10\.\d{4,9}/\S+', str(paper.get('doi') or '')):
            issues.append(f'ref {paper["ref_no"]} invalid DOI')
        if paper.get('is_retracted'):
            issues.append(f'ref {paper["ref_no"]} retracted')
    Path(output_path).write_text('# 著录核验\n\n离线边界：仅核对 HCC 快照题录；未访问 Crossref 或出版社。\n' + '\n'.join(f'- [{"PASS" if not issues else "FAIL"}] ref {paper["ref_no"]}' for paper in papers) + '\n' + '\n'.join(issues), encoding='utf-8')
    return {'clean': not issues, 'issues': issues}


def install():
    import ipaddress
    import socket
    from app import orchestration
    from app.delivery import DeliveryService

    # Fail closed if any unpatched provider tries to leave this machine.
    original_connect = socket.socket.connect
    def local_only(self, address):
        if isinstance(address, tuple) and address:
            host = str(address[0])
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host == 'localhost'
            if not local:
                raise RuntimeError(f'External network is disabled in real-backend offline acceptance: {host}')
        return original_connect(self, address)
    socket.socket.connect = local_only

    original_init = orchestration.Orchestrator.__init__
    def offline_init(self, *args, **kwargs):
        kwargs.setdefault('search_factory', OfflineHCCSearch)
        kwargs.setdefault('stats_runner', offline_stats)
        kwargs.setdefault('model', OfflineModel())
        kwargs.setdefault('delivery_factory', lambda workspace_root: DeliveryService(
            workspace_root=workspace_root,
            reference_checker=offline_reference_checker,
        ))
        original_init(self, *args, **kwargs)

    orchestration.SearchService = OfflineHCCSearch
    orchestration.ChatModel = OfflineModel
    orchestration.Orchestrator.__init__ = offline_init
