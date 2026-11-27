import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.delivery import DeliveryService, DeliveryTask
from app.models import Base, InviteSession, SkillVersion, Task
from app.orchestration import Orchestrator
from app.writing import WritingService, WritingTask


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures' / 'modes'
SOURCE_FIXTURE = PROJECT_ROOT / 'fixtures' / 'hcc-20261122' / 'papers.json'
MODE_SPECS = {
    'B': {'range': (2000, 3000), 'body': '综述初稿.md'},
    'C1': {'range': (800, 1200), 'body': 'C1_引言.md'},
    'C2': {'range': (800, 1200), 'body': 'C2_文献综述.md'},
    'D': {'range': (3000, 6000), 'body': '调研初稿.md'},
}
DIRECTION = '肝细胞癌免疫治疗耐药机制'
SEARCH_LOG = '''# 离线检索边界

本回归只复用项目已有 OpenAlex 真实快照 fixtures/hcc-20261122/papers.json 中的四篇论文。
本次未执行在线检索、付费模型调用或全文下载；题录、摘要与引文均来自 fixture。
'''
PROJECT = {
    'name': '肝细胞癌免疫治疗耐药的多机制对解与联合验证',
    'goal': '连接髓系代谢、IL-8/CXCR2 与乳酸化调控证据并形成分层验证方案',
    'funding': '离线回归未指定',
    'research_contents': [
        '研究内容（一）髓系代谢机制解析',
        '研究内容（二）IL-8/CXCR2 动态验证',
        '研究内容（三）乳酸化机制与联合干预评价',
    ],
    'technical_route': '证据对解→分层观察→机制验证→联合评价',
    'feasibility': '只确认文献方法线索；团队、预实验与数据权限未提供。',
    'expected_outcomes': '机制对解框架、分层验证流程与联合评价方案。',
}


@pytest.fixture(autouse=True)
def disable_external_delivery(monkeypatch):
    """Prevent the orchestrator from synchronizing artifacts to a remote site."""
    monkeypatch.delenv('QODER_SITES_ORIGIN', raising=False)
    monkeypatch.delenv('WORKER_SHARED_SECRET', raising=False)


def load_fixture(mode):
    root = FIXTURE_ROOT / mode
    return {
        'root': root,
        'papers_document': json.loads((root / 'papers.json').read_text(encoding='utf-8')),
        'components': json.loads((root / 'components.json').read_text(encoding='utf-8')),
        'evidence': json.loads((root / 'evidence.json').read_text(encoding='utf-8')),
        'body_evidence': json.loads((root / 'body_evidence.json').read_text(encoding='utf-8')),
        'body': (root / 'body.md').read_text(encoding='utf-8'),
    }


def materialize(value, evidence):
    if isinstance(value, dict):
        resolved = {}
        for key, item in value.items():
            if key == 'evidence':
                assert isinstance(item, list) and item
                resolved[key] = [deepcopy(evidence[evidence_id]) for evidence_id in item]
            else:
                resolved[key] = materialize(item, evidence)
        return resolved
    if isinstance(value, list):
        return [materialize(item, evidence) for item in value]
    return value


class OfflineModel:
    """Deterministic fixture model: no SDK, network, token, or paid-model path."""

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.calls = []

    def complete_json(self, system_prompt, payload):
        mode = payload['mode']
        fixture = self.fixtures[mode]
        assert payload['papers'] == fixture['papers_document']['papers']
        self.calls.append((mode, payload['stage']))
        if payload['stage'] == 'components':
            return {'components': materialize(fixture['components'], fixture['evidence'])}
        assert payload['stage'] == 'body'
        return {
            'body': fixture['body'],
            'evidence': [
                deepcopy(fixture['evidence'][evidence_id])
                for evidence_id in fixture['body_evidence']
            ],
        }


def writing_task(mode, fixture, task_id):
    papers = fixture['papers_document']['papers']
    return WritingTask(
        id=task_id,
        mode=mode,
        direction=DIRECTION,
        papers=papers,
        component_data=None,
        analysis={'clusters': ['髓系代谢', 'IL-8/CXCR2', '乳酸化调控']},
        search_overview={
            'databases': ['OpenAlex 离线快照'],
            'queries': ['hepatocellular carcinoma immunotherapy resistance'],
            'from_year': None,
            'pool_count': len(papers),
        },
        project=deepcopy(PROJECT),
        user_results='',
        target_journal='',
        team_context='未提供团队背景',
    )


def produce_mode(mode, workspace, task_id=None, fixtures=None):
    fixtures = fixtures or {name: load_fixture(name) for name in MODE_SPECS}
    fixture = fixtures[mode]
    model = OfflineModel(fixtures)
    task = writing_task(mode, fixture, task_id or f'{mode.lower()}-offline')
    output = WritingService(workspace_root=workspace, model=model).produce(task)
    assert model.calls == [(mode, 'components'), (mode, 'body')]
    return task, output


def offline_reference_checker(papers_path, output_path):
    """Check the frozen bibliography without any online bibliographic lookup."""
    document = json.loads(Path(papers_path).read_text(encoding='utf-8'))
    papers = document['papers']
    issues = []
    for paper in papers:
        for field in ('title', 'authors', 'year', 'venue', 'doi', 'abstract'):
            if not paper.get(field):
                issues.append(f"ref {paper['ref_no']} 缺少 {field}")
        doi = str(paper.get('doi') or '')
        if not re.fullmatch(r'https://doi\.org/10\.\d{4,9}/\S+', doi):
            issues.append(f"ref {paper['ref_no']} DOI 格式不完整")
        if paper.get('is_retracted'):
            issues.append(f"ref {paper['ref_no']} 已标记撤稿")
    lines = [
        '# 著录核验',
        '',
        '离线检查器：逐条核对 fixture 的题名、作者、年份、期刊、DOI、摘要和撤稿字段。',
        '未调用 Crossref、出版社网站或任何在线检索；外部著录变化不在本次覆盖范围。',
        '',
    ]
    lines.extend(f'- [PASS] ref {paper["ref_no"]}：{paper["doi"]}' for paper in papers)
    lines.extend(f'- [FAIL] {issue}' for issue in issues)
    Path(output_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'clean': not issues, 'issues': issues}


def offline_figure_loader(*args, **kwargs):
    """Test-only loader: fixture papers carry real OA URLs, but tests must stay offline."""
    from app.ppt_figures import FigureBundle

    return FigureBundle(assets=[], attempts=[])


def deliver_mode(mode, task, output, workspace, form='ALL', figure_loader=None):
    if figure_loader is None:
        figure_loader = offline_figure_loader
    task_dir = workspace / task.id
    delivery_task = DeliveryTask(
        id=task.id,
        mode=mode,
        direction=DIRECTION,
        papers=task.papers,
        body=output.body_path.read_text(encoding='utf-8'),
        evidence_ledger=(task_dir / 'evidence_ledger.md').read_text(encoding='utf-8'),
        components=output.components.data,
        outline=output.outline,
        sample=output.sample,
        delivery_form=form,
        search_log=SEARCH_LOG,
        requirements=[
            {'requirement': '真实 fixture 与逐字摘要证据', 'location': 'papers.json / evidence_ledger.md', 'passed': True},
            {'requirement': f'{mode} 独立预置复核', 'location': 'verify_report.txt', 'passed': True},
            {'requirement': '真实 Office 生成与重开', 'location': 'report.docx / slides.pptx', 'passed': True},
        ],
    )
    result = DeliveryService(
        workspace_root=workspace,
        reference_checker=offline_reference_checker,
        figure_loader=figure_loader,
    ).deliver(delivery_task)
    return result


def cjk_count(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text.split('## 参考文献')[0]))


def word_path(result):
    return next(path for path in result.artifacts.values() if path.suffix == '.docx')


def ppt_path(result):
    if 'slides.pptx' in result:
        return result['slides.pptx']
    return next(path for path in result.artifacts.values() if path.name.endswith('组会汇报.pptx'))


def assert_common_delivery(mode, output, result):
    spec = MODE_SPECS[mode]
    body = result[spec['body']].read_text(encoding='utf-8')
    low, high = spec['range']
    assert low <= cjk_count(body) <= high
    report = result['verify_report.txt'].read_text(encoding='utf-8')
    # 回归基线曾是“台账: 0条”；现在直接核验原始交付，不做任何格式转换或兼容复跑。
    assert '台账: 0条' not in report
    assert '台账: 15条' in report
    assert '15/15 条摘要原句逐字命中' in report
    if mode == 'D':
        assert result.clean, result.failures
        assert result.failures == []
        structure_report = result['verify_ppt_report.txt'].read_text(encoding='utf-8')
        assert '结果：PASS' in structure_report
        assert json.loads(result['layout_check.json'].read_text(encoding='utf-8'))['ok'] is True
    else:
        assert result.clean, result.failures
    failures = [line for line in report.splitlines() if line.startswith('[FAIL]')]
    assert not failures
    ledger = result['evidence_ledger.md'].read_text(encoding='utf-8')
    ledger_refs = [
        cells[1]
        for line in ledger.splitlines()
        if line.strip().startswith('|')
        for cells in [[cell.strip() for cell in line.strip().strip('|').split('|')]]
        if len(cells) >= 4 and cells[1].isdigit()
    ]
    assert len(ledger_refs) == 15
    assert '| [1] |' not in ledger
    assert f'⑧模式形态(--mode {mode})' in report
    assert '③摘要通道' in report and '[PASS] ③摘要通道' in report
    assert '离线检查器' in result['references_check.md'].read_text(encoding='utf-8')

    document = Document(word_path(result))
    assert len(document.paragraphs) > 10
    document_text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    assert DIRECTION in document_text
    assert '参考文献' in document_text

    presentation = Presentation(ppt_path(result))
    assert len(presentation.slides) > 0
    slide_text = '\n'.join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if getattr(shape, 'has_text_frame', False)
    )
    assert '参考文献' in slide_text
    assert word_path(result).read_bytes().startswith(b'PK')
    assert ppt_path(result).read_bytes().startswith(b'PK')

    papers = {
        paper['ref_no']: paper
        for paper in json.loads(result['papers.json'].read_text(encoding='utf-8'))['papers']
    }
    body_refs = {int(ref) for ref in re.findall(r'\[(\d+)\]', body.split('## 参考文献')[0])}
    assert body_refs <= {item['ref'] for item in output.evidence}
    for item in output.evidence:
        assert item['quote'] in papers[item['ref']]['abstract']


def assert_fixture_provenance_and_quotes(mode):
    fixture = load_fixture(mode)
    source = json.loads(SOURCE_FIXTURE.read_text(encoding='utf-8'))
    source_by_doi = {paper['doi']: paper for paper in source['papers']}
    papers = fixture['papers_document']['papers']
    assert len(papers) == 4
    assert fixture['papers_document']['provenance']['online_retrieval'] is False
    for paper in papers:
        original = source_by_doi[paper['doi']]
        for field in ('title', 'abstract', 'authors', 'year', 'venue', 'type', 'is_retracted'):
            assert paper[field] == original[field]
        assert paper['claim_eligible'] is True
    for item in fixture['evidence'].values():
        for ref, quote in item['quotes'].items():
            paper = next(paper for paper in papers if paper['ref_no'] == int(ref))
            assert quote in paper['abstract']
            assert quote in source_by_doi[paper['doi']]['abstract']
        assert item['claim'].strip()
        assert item['refs']


@pytest.mark.parametrize('mode', sorted(MODE_SPECS))
def test_real_fixture_provenance_and_verbatim_abstract_quotes(mode):
    assert_fixture_provenance_and_quotes(mode)


def test_b_real_offline_delivery_and_required_components(tmp_path):
    task, output = produce_mode('B', tmp_path)
    result = deliver_mode('B', task, output, tmp_path)
    assert_common_delivery('B', output, result)

    components = output.components.markdown
    for field in ('项目名称', '资助类别/学科属性', '一句话目标'):
        assert field in components
    assert '已有研究对本项目技术路线的支撑' in components
    assert '不足↔科学问题↔研究内容一一对解表' in components
    for name in ('研究需求', '已有进展', '现有不足', '关键科学问题', '项目切入点', '预期贡献'):
        assert f'### {name}' in components
    body = result['综述初稿.md'].read_text(encoding='utf-8')
    assert body.count('研究内容（') >= 3
    assert '若不开展本项目' in body


def test_c1_real_offline_delivery_is_independent_introduction(tmp_path):
    task, output = produce_mode('C1', tmp_path)
    result = deliver_mode('C1', task, output, tmp_path)
    assert_common_delivery('C1', output, result)

    body = result['C1_引言.md'].read_text(encoding='utf-8')
    assert body.count('段落卡·') == 5
    assert 'Research Gap 分析表' in body
    assert '## 完整引言' in body
    assert '## 完整综述文本' not in body
    introduction = body.split('## 完整引言', 1)[1].split('## 写作逻辑和学术质量检查', 1)[0]
    paragraphs = [paragraph.strip() for paragraph in re.split(r'\n\s*\n', introduction) if paragraph.strip()]
    assert len(paragraphs) == 5
    assert '不足' in paragraphs[2] and re.search(r'\[\d+\]', paragraphs[2])
    assert '本文' in paragraphs[3]
    assert '贡献' in paragraphs[4]


def test_c2_real_offline_delivery_is_not_discussion(tmp_path):
    task, output = produce_mode('C2', tmp_path)
    result = deliver_mode('C2', task, output, tmp_path)
    assert_common_delivery('C2', output, result)

    body = result['C2_文献综述.md'].read_text(encoding='utf-8')
    for section in (
        '研究主题与检索范围', '关键词和检索策略', '代表性文献清单', '文献分类框架',
        '不同研究方向的综合分析', '主要技术路线比较', '文献比较表', '研究空白分析表',
        '未来研究方向', '完整综述文本',
    ):
        assert section in body
    assert not re.search(r'^#{1,4}\s*.*(?:讨论|discussion).*$', body, flags=re.M | re.I)
    assert '必须提供本文结果' not in body
    assert '## 完整引言' not in body


def test_d_real_offline_delivery_and_ppt_reverification(tmp_path, monkeypatch):
    def forbid_live_figure_loader(*args, **kwargs):
        pytest.fail('offline D delivery must not invoke the live figure loader')

    monkeypatch.setattr('app.ppt_figures.prepare_d_figures', forbid_live_figure_loader)
    task, output = produce_mode('D', tmp_path)
    result = deliver_mode('D', task, output, tmp_path)
    assert_common_delivery('D', output, result)

    body = result['调研初稿.md'].read_text(encoding='utf-8')
    headings = (
        '## 一、研究背景与主题介绍',
        '## 二、检索策略与总体概况',
        '## 三、国内外研究进展',
        '## 四、核心方法与技术路线',
        '## 五、代表作精读',
        '## 六、现有研究不足',
        '## 七、发展趋势',
        '## 八、潜在选题推荐',
        '## 九、总结与组会讨论',
    )
    positions = [body.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert body.count('### 精读页') == 3
    assert body.count('**阅读深度**') == 3
    for field in (
        '研究问题', '研究动机', '核心方法', '技术实现', '数据来源', '实验设置',
        '主要结果', '创新点', '局限', '对团队研究的启发',
    ):
        assert body.count(f'**{field}**') == 3
    assert body.count('第 1 推荐') == 1
    assert body.count('第 2 推荐') == 1
    assert body.count('第 3 推荐') == 1
    assert body.count('**组会讨论问题**') == 1
    assert '方法对比' in output.components.markdown

    presentation = Presentation(ppt_path(result))
    assert 20 <= len(presentation.slides) <= 30
    assert result['汇报文本.md'].exists()
    ppt_report = result['verify_report_ppt.txt'].read_text(encoding='utf-8')
    assert '[FAIL]' not in ppt_report
    report = result['verify_report.txt'].read_text(encoding='utf-8')
    unbound_numbers = re.findall(r'^  (.+未绑定台账原句——待人工确认.+)$', report, flags=re.M)
    assert len(unbound_numbers) == 1
    assert unbound_numbers[0].startswith('3（句引[1, 2, 3]）')
    assert '3. 乳酸化—MVP—PD-L1 机制应在哪一层与髓系指标对解' in body


def run_c_pair_orchestrator(tmp_path, monkeypatch, mutate_fixtures=None):
    fixtures = {mode: load_fixture(mode) for mode in MODE_SPECS}
    if mutate_fixtures is not None:
        mutate_fixtures(fixtures)
    assert fixtures['C1']['papers_document'] == fixtures['C2']['papers_document']
    engine = create_engine(
        'sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr('app.orchestration.SessionLocal', factory)
    try:
        with factory() as db:
            db.add(InviteSession(id='offline-owner'))
            db.add(SkillVersion(
                id='offline-version',
                version=1,
                state='published',
                content={'templates': {
                    mode: (PROJECT_ROOT / 'skill_runtime' / 'templates' / filename).read_text(encoding='utf-8')
                    for mode, filename in (
                        ('C1', 'C1_引言段落卡骨架.md'),
                        ('C2', 'C2_文献综述骨架.md'),
                    )
                }},
                content_hash='offline-fixture-hash',
                created_at=datetime.now(timezone.utc),
            ))
            task = Task(id='c-pair-offline', session_id='offline-owner', skill_version_id='offline-version')
            db.add(task)
            db.commit()
            db.refresh(task)

        task_dir = tmp_path / task.id
        task_dir.mkdir(parents=True)
        (task_dir / 'papers.json').write_text(
            json.dumps(fixtures['C1']['papers_document'], ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        (task_dir / 'analysis.json').write_text('{"limited": {}}', encoding='utf-8')
        (task_dir / 'search_log.md').write_text(SEARCH_LOG, encoding='utf-8')
        service = Orchestrator(
            artifact_root=tmp_path,
            model=OfflineModel(fixtures),
            delivery_factory=lambda root: DeliveryService(
                workspace_root=root,
                reference_checker=offline_reference_checker,
            ),
        )
        stage_input = {
            'answers': [
                {'card_id': 'direction', 'value': {'direction': DIRECTION}},
                {'card_id': 'mode', 'value': {'mode': 'C', 'c_route': 'C1+C2', 'project': PROJECT}},
                {'card_id': 'terms', 'value': {'terms': ['hepatocellular carcinoma immunotherapy resistance']}},
                {'card_id': 'years', 'value': {'from_year': 2023}},
                {'card_id': 'delivery', 'value': {'form': 'ALL'}},
            ],
        }
        result = service.generate_stage(task, stage_input)
        return task.id, result
    finally:
        engine.dispose()


def test_c1_c2_have_separate_reports_and_real_combined_delivery(tmp_path, monkeypatch):
    task_id, stage_result = run_c_pair_orchestrator(tmp_path, monkeypatch)
    root = tmp_path / task_id
    c1_report = (root / 'verify_report_C1.txt').read_text(encoding='utf-8')
    c2_report = (root / 'verify_report_C2.txt').read_text(encoding='utf-8')
    assert '⑧模式形态(--mode C1)' in c1_report
    assert '⑧模式形态(--mode C2)' in c2_report
    assert stage_result['checkpoint']['clean'] is True
    assert stage_result['checkpoint']['failures'] == []
    assert stage_result['checkpoint']['combined_delivered'] is True
    assert stage_result['checkpoint']['linkage'] == {
        'passed': True,
        'gap_consistent': True,
        'initial_duplicates': 0,
        'remaining_duplicates': 0,
    }
    for mode, report in (('C1', c1_report), ('C2', c2_report)):
        assert '台账: 15条' in report
        assert '15/15 条摘要原句逐字命中' in report
        assert '[FAIL]' not in report
        independent_report = (tmp_path / f'{task_id}-{mode}' / 'verify_report.txt').read_text(encoding='utf-8')
        assert '台账: 15条' in independent_report
        assert '[FAIL]' not in independent_report
        assert (tmp_path / f'{task_id}-C1' / 'dialogue.json').exists()
        assert (tmp_path / f'{task_id}-C2' / 'dialogue.json').exists()
    assert 'C1+C2 衔接与重复检查' in c2_report
    assert 'C1+C2 无重复段落（实得 0 段）' in c2_report

    linkage = (root / 'linkage_check.md').read_text(encoding='utf-8')
    assert '空白点与引用一致性：**通过**' in linkage
    assert '原始归一化重复长段：**0 段**' in linkage
    assert '处理后剩余重复长段：**0 段**' in linkage
    assert '通过，允许合并交付' in linkage

    c1_body = (root / 'C1_引言.md').read_text(encoding='utf-8')
    c2_body = (root / 'C2_文献综述.md').read_text(encoding='utf-8')
    assert c1_body == (tmp_path / f'{task_id}-C1' / 'C1_引言.md').read_text(encoding='utf-8')
    assert c2_body == (tmp_path / f'{task_id}-C2' / 'C2_文献综述.md').read_text(encoding='utf-8')
    assert '## 完整引言' in c1_body
    assert '## 完整综述文本' in c2_body
    assert '## 参考文献' in c1_body and '## 参考文献' in c2_body
    assert not re.search(r'^#{1,4}\s*.*(?:讨论|discussion).*$', c2_body, flags=re.M | re.I)

    combined = (root / '综述初稿.md').read_text(encoding='utf-8')
    assert '## 独立文献综述' in combined
    assert '## 完整引言' in combined
    assert '## 完整综述文本' in combined
    combined_report = (root / 'verify_report.txt').read_text(encoding='utf-8')
    assert '台账: 30条' in combined_report
    assert '30/30 条摘要原句逐字命中' in combined_report
    assert '[FAIL]' not in combined_report
    assert len(Document(next(root.glob('*.docx'))).paragraphs) > 20
    assert len(Presentation(next(root.glob('*.pptx'))).slides) > 0


def test_c_pair_gap_mismatch_blocks_combined_office_delivery(tmp_path, monkeypatch):
    def mismatch_gap_reference(fixtures):
        old = '| 多机制对解 | 三条机制链分别有证据 | 缺少统一分层评价 | [1][2][3] |'
        new = '| 多机制对解 | 三条机制链分别有证据 | 缺少统一分层评价 | [1][2] |'
        assert old in fixtures['C1']['body']
        fixtures['C1']['body'] = fixtures['C1']['body'].replace(old, new)

    task_id, stage_result = run_c_pair_orchestrator(tmp_path, monkeypatch, mismatch_gap_reference)
    root = tmp_path / task_id
    checkpoint = stage_result['checkpoint']
    assert checkpoint['clean'] is False
    assert checkpoint['combined_delivered'] is False
    assert checkpoint['linkage']['gap_consistent'] is False
    assert any('研究方向、现有不足或引用集合不一致' in failure for failure in checkpoint['failures'])
    linkage = (root / 'linkage_check.md').read_text(encoding='utf-8')
    assert '引用：[1][2][3]' in linkage
    assert '引用：[1][2]' in linkage
    assert '未通过，禁止合并交付' in linkage
    for mode in ('C1', 'C2'):
        report = (root / f'verify_report_{mode}.txt').read_text(encoding='utf-8')
        assert '台账: 15条' in report
        assert '[FAIL]' not in report
    fallback_body = (root / '综述初稿.md').read_text(encoding='utf-8')
    assert '## 独立文献综述' in fallback_body
    assert (root / 'outline.md').stat().st_size > 100
    assert (root / 'sample.md').stat().st_size > 50
    assert not list(root.glob('*.docx'))
    assert not list(root.glob('*.pptx'))


def test_c_pair_normalized_duplicate_is_redirected_then_reverified(tmp_path, monkeypatch):
    duplicate = (
        '动态样本、循环指标与组织细胞状态应分别记录，并保留研究设计[1]、样本范围[2]和终点差异[3]；'
        '这些材料只支持后续分层评价，不能替代同一体系内的机制验证。'
    )

    def inject_duplicate(fixtures):
        # C1 插入额外空白和单换行；归一化后必须与 C2 识别为同一长段。
        c1_duplicate = duplicate[:24] + ' \n ' + duplicate[24:]
        fixtures['C1']['body'] = fixtures['C1']['body'].replace(
            '## 写作逻辑和学术质量检查', c1_duplicate + '\n\n## 写作逻辑和学术质量检查',
        )
        c2_body = fixtures['C2']['body'].replace(
            '综合归纳：三者可比较，但不能据此宣称联合验证已完成。', '',
        ).replace(
            '比较结论是方法互补，而非疗效排序；摘要未提供统一指标下的头对头结果。', '',
        )
        fixtures['C2']['body'] = c2_body.replace(
            '## 衔接与重复检查', duplicate + '\n\n## 衔接与重复检查',
        )

    task_id, stage_result = run_c_pair_orchestrator(tmp_path, monkeypatch, inject_duplicate)
    root = tmp_path / task_id
    checkpoint = stage_result['checkpoint']
    assert checkpoint['clean'] is True, checkpoint['failures']
    assert checkpoint['combined_delivered'] is True
    assert checkpoint['linkage']['initial_duplicates'] == 1
    assert checkpoint['linkage']['remaining_duplicates'] == 0
    c1_body = (root / 'C1_引言.md').read_text(encoding='utf-8')
    c2_body = (root / 'C2_文献综述.md').read_text(encoding='utf-8')
    display_duplicates = {}
    for mode in ('C1', 'C2'):
        citation_map = json.loads((tmp_path / f'{task_id}-{mode}' / 'citation_map.json').read_text(encoding='utf-8'))
        ref_to_display = {str(ref): display for display, ref in citation_map['display_to_ref'].items()}
        display_duplicates[mode] = re.sub(
            r'\[(\d+)\]', lambda match: f'[{ref_to_display[match.group(1)]}]', duplicate,
        )
        filename = 'C1_引言.md' if mode == 'C1' else 'C2_文献综述.md'
        independent_body = (tmp_path / f'{task_id}-{mode}' / filename).read_text(encoding='utf-8')
        assert re.sub(r'\s+', '', display_duplicates[mode]) in re.sub(r'\s+', '', independent_body)
    assert display_duplicates['C1'] != display_duplicates['C2']
    assert duplicate not in c1_body
    assert duplicate in c2_body
    assert display_duplicates['C2'] in c2_body
    assert '概括：该领域证据段保留在 C2《文献综述》中；此处仅作交叉指向，不再重复铺陈。' in c1_body
    linkage = (root / 'linkage_check.md').read_text(encoding='utf-8')
    assert '原始归一化重复长段：**1 段**' in linkage
    assert '处理后剩余重复长段：**0 段**' in linkage
    assert '保留位置：C2；改写位置：C1；理由：领域证据优先留在 C2' in linkage
    c2_report = (root / 'verify_report_C2.txt').read_text(encoding='utf-8')
    assert 'C1+C2 无重复段落（实得 0 段）' in c2_report
    assert '[FAIL]' not in c2_report
    Document(next(root.glob('*.docx')))
    Presentation(next(root.glob('*.pptx')))
