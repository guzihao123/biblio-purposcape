"""B-mode [M] material wiring: parsing, citations, listing and delivery."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.answer_validation import validate_answer_value
from app.delivery import DeliveryService, DeliveryTask
from app.models import Base, InviteSession, SkillVersion, Task
from app.orchestration import Orchestrator
from app.policy_search import collect_b_materials
from app.task_presenters import _mode_card
from app.writing import B_MATERIAL_RULE, WritingInputError, WritingService, WritingTask
from test_delivery import LEDGER, PAPERS, passing_reference_checker
from test_policy_search import source as policy_source
from test_writing import EVIDENCE, component_data


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIRECTION = '道路交通事故严重程度致因识别'
PROJECT = {'name': '多源证据联合校准', 'goal': '形成分层验证方案', 'funding': '未指定'}
PASTED = '''标题：道路交通安全示范建设规划
发布机构：国务院
文号：国发〔2024〕1号
成文日期：2024-01-01
链接：https://www.gov.cn/zhengce/example.htm
正文：
到2030年形成完整示范体系。各地应当完善风险评估机制，保障数据供给。

---
标题：某省道路交通统计公报
发布机构：某省统计局
文号：统字〔2024〕2号
成文日期：2024-03-01
来源：gov.cn 转载
转载发布日期：2024-03-05
原文链接：https://www.gov.cn/zhengce/original.htm
链接：https://www.gov.cn/zhengce/repost.htm
正文：
全省事故数下降。必须加强统计口径管理。'''
MATERIAL_BODY = '政策目标见（据材料 M1），文献事实 [1]。'


class MaterialModel:
    def __init__(self, body):
        self.body = body
        self.payloads = []

    def complete_json(self, system_prompt, payload):
        self.payloads.append((payload['stage'], payload, system_prompt))
        if payload['stage'] == 'components':
            return {'components': component_data('B')}
        return {'body': self.body, 'evidence': [EVIDENCE]}


def writing_task(materials=None):
    return WritingTask(
        id='b-material', mode='B', direction=DIRECTION, papers=PAPERS,
        project=dict(PROJECT), materials=list(materials or []),
    )


def stub_verifier(task, body_path, report_name):
    report = '模拟复核：通过。\n'
    (body_path.parent / report_name).write_text(report, encoding='utf-8')
    return {'clean': True, 'failures': [], 'warnings': [], 'report': report}


def test_b_card_exposes_optional_material_textarea():
    fields = _mode_card()['conditional_fields']['B']
    material = [field for field in fields if field['name'] == 'policy_materials']
    assert len(material) == 1
    assert material[0]['kind'] == 'textarea'
    assert material[0].get('required') is None
    assert '政策/报告/统计材料' in material[0]['label']


def test_mode_answer_accepts_material_text_within_size_limit():
    validate_answer_value('mode', {'mode': 'B', 'theme': {'name': '材料主题', 'custom': '材料主题'}, 'project': {'name': '项目', 'goal': '目标'}, 'policy_materials': PASTED})
    with pytest.raises(HTTPException) as error:
        validate_answer_value('mode', {'mode': 'B', 'theme': {'name': '材料主题', 'custom': '材料主题'}, 'project': {'name': '项目', 'goal': '目标'}, 'policy_materials': 'x' * 16_001})
    assert error.value.status_code == 422


def test_pasted_materials_are_archived_and_listed_verbatim(tmp_path):
    def no_network(_):
        raise AssertionError('pasted text must not trigger network access')

    collection = collect_b_materials(tmp_path, PASTED, fetcher=no_network)
    assert collection.rejected == []
    assert [item['citation'] for item in collection.items] == ['[M1]', '[M2]']
    first = collection.items[0]
    assert first['included_in_n_pool'] is False
    assert first['issuer'] == '国务院'
    assert first['document_number'] == '国发〔2024〕1号'
    assert '到2030年形成完整示范体系。' in [item['text'] for item in first['excerpts']]
    assert Path(first['original_path']).exists()
    assert Path(first['original_path']).parent.name == 'policy_docs'

    listing = (tmp_path / '非论文材料清单.md').read_text(encoding='utf-8')
    for field in ('## [M1]', '发布机构：国务院', '文号：国发〔2024〕1号',
                  '成文日期：2024-01-01', '链接：https://www.gov.cn/zhengce/example.htm',
                  '关键句逐字摘录：', '到2030年形成完整示范体系。'):
        assert field in listing
    assert '[M] 与论文 [n] 分通道著录' in listing


def test_gov_cn_repost_is_noted_without_verifying_online(tmp_path):
    def no_network(_):
        raise AssertionError('pasted repost must not be verified online')

    collection = collect_b_materials(tmp_path, PASTED, fetcher=no_network)
    repost = collection.items[1]
    assert repost['source_type'] == 'user_material'
    assert 'gov.cn 转载文本' in repost['repost_note']
    assert 'https://www.gov.cn/zhengce/original.htm' in repost['repost_note']
    listing = (tmp_path / '非论文材料清单.md').read_text(encoding='utf-8')
    assert '转载注明：gov.cn 转载文本' in listing
    assert '转载发布日期：2024-03-05' in listing


def test_bare_url_without_authorized_fetcher_is_a_declared_boundary(tmp_path):
    collection = collect_b_materials(tmp_path, 'https://www.gov.cn/zhengce/only.htm')
    assert collection.items == []
    assert '未发起网络请求' in collection.rejected[0]
    assert not (tmp_path / '非论文材料清单.md').exists()


def test_targeted_official_url_with_fetcher_is_accepted(tmp_path):
    calls = []

    def fetcher(candidate):
        calls.append(candidate['url'])
        return policy_source(url=candidate['url'], html='<p>目标逐年下降。</p>')

    collection = collect_b_materials(
        tmp_path, 'https://www.gov.cn/zhengce/only.htm', fetcher=fetcher,
    )
    assert calls == ['https://www.gov.cn/zhengce/only.htm']
    assert len(collection.items) == 1
    assert collection.items[0]['source_type'] == 'official'
    assert '目标逐年下降。' in (tmp_path / '非论文材料清单.md').read_text(encoding='utf-8')


def test_b_payloads_carry_materials_listing_and_material_rule(tmp_path):
    materials = collect_b_materials(tmp_path, PASTED).items
    model = MaterialModel(MATERIAL_BODY)
    output = WritingService(workspace_root=tmp_path, model=model).produce(
        writing_task(materials),
    )
    component_payload = next(payload for stage, payload, _ in model.payloads if stage == 'components')
    body_payload = next(payload for stage, payload, _ in model.payloads if stage == 'body')
    for payload in (component_payload, body_payload):
        assert payload['materials'][0]['citation'] == '[M1]'
        assert '非论文材料索引' in payload['material_index']
        assert '（据材料 M1）' in payload['material_rules']
    assert B_MATERIAL_RULE in next(
        prompt for stage, _, prompt in model.payloads if stage == 'body'
    )
    assert '非论文材料索引' in output.components.markdown
    assert '（据材料 M1）' in output.body
    assert 'M1' not in (tmp_path / 'b-material' / 'evidence_ledger.md').read_text(encoding='utf-8')


def test_material_citations_are_checked_and_never_join_the_n_ledger(tmp_path):
    materials = collect_b_materials(tmp_path, PASTED).items
    with pytest.raises(WritingInputError, match='M3'):
        WritingService(workspace_root=tmp_path, model=MaterialModel('无依据（据材料 M3）[1]。')).produce(
            writing_task(materials),
        )

    with pytest.raises(WritingInputError, match='未提供非论文材料'):
        WritingService(workspace_root=tmp_path, model=MaterialModel(MATERIAL_BODY)).produce(
            writing_task(),
        )

    assert '非论文材料索引' not in WritingService(
        workspace_root=tmp_path, model=MaterialModel('文献 [1]。'),
    ).produce(writing_task()).components.markdown


def test_delivery_artifacts_include_listing_and_flattened_original(tmp_path):
    collection = collect_b_materials(tmp_path, PASTED)
    task = DeliveryTask(
        id='b-material-delivery', mode='B', direction=DIRECTION, papers=PAPERS,
        body=MATERIAL_BODY, evidence_ledger=LEDGER,
        material_listing=collection.listing_text,
        material_originals=collection.originals,
        requirements=[{'requirement': '[M] 原件与清单', 'location': '非论文材料清单.md', 'passed': True}],
    )
    result = DeliveryService(
        workspace_root=tmp_path,
        verification_runner=stub_verifier,
        reference_checker=passing_reference_checker,
    ).deliver(task)

    assert result.clean, result.failures
    assert result['非论文材料清单.md'].exists()
    originals = [name for name in result.artifacts if name.startswith('M1_')]
    assert originals and result[originals[0]].exists()
    assert result[originals[0]].parent == tmp_path / task.id
    assert '（据材料 M1）' in result['综述初稿.md'].read_text(encoding='utf-8')


def run_b_stage(tmp_path, monkeypatch, raw_materials, body):
    engine = create_engine(
        'sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr('app.orchestration.SessionLocal', factory)
    try:
        with factory() as db:
            db.add(InviteSession(id='bm-owner'))
            db.add(SkillVersion(
                id='bm-version', version=1, state='published',
                content={'templates': {'B': (
                    PROJECT_ROOT / 'skill_runtime' / 'templates' / 'B_立项依据骨架.md'
                ).read_text(encoding='utf-8')}},
                content_hash='bm-hash', created_at=datetime.now(timezone.utc),
            ))
            task = Task(id='bm-task', session_id='bm-owner', skill_version_id='bm-version')
            db.add(task)
            db.commit()
            db.refresh(task)

        task_dir = tmp_path / task.id
        task_dir.mkdir(parents=True)
        (task_dir / 'papers.json').write_text(json.dumps({
            'topic': DIRECTION, 'count': len(PAPERS), 'papers': PAPERS,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        (task_dir / 'analysis.json').write_text('{}', encoding='utf-8')
        (task_dir / 'search_log.md').write_text('离线接线回归', encoding='utf-8')

        service = Orchestrator(
            artifact_root=tmp_path,
            model=MaterialModel(body),
            delivery_factory=lambda root: DeliveryService(
                workspace_root=root,
                verification_runner=stub_verifier,
                reference_checker=passing_reference_checker,
            ),
        )
        stage_input = {'answers': [
            {'card_id': 'direction', 'value': {'direction': DIRECTION}},
            {'card_id': 'mode', 'value': {
                'mode': 'B', 'project': PROJECT, 'policy_materials': raw_materials,
            }},
            {'card_id': 'terms', 'value': {'terms': ['road accident']}},
            {'card_id': 'years', 'value': {'years': 'D'}},
            {'card_id': 'delivery', 'value': {'form': 'A'}},
        ]}
        result = service.generate_stage(task, stage_input)
        return task.id, result
    finally:
        engine.dispose()


def test_b_stage_delivers_materials_without_polluting_n_evidence(tmp_path, monkeypatch):
    task_id, result = run_b_stage(tmp_path, monkeypatch, PASTED, MATERIAL_BODY)
    checkpoint = result['checkpoint']
    assert checkpoint['clean'] is True, checkpoint['failures']
    assert checkpoint['materials']['accepted'] == 2
    assert checkpoint['materials']['rejected'] == []

    root = tmp_path / task_id
    assert (root / '非论文材料清单.md').exists()
    originals = [path.name for path in root.iterdir() if path.name.startswith('M') and '_' in path.name]
    assert any(name.startswith('M1_') for name in originals)
    assert any(name.startswith('M2_') for name in originals)
    assert '（据材料 M1）' in (root / '综述初稿.md').read_text(encoding='utf-8')
    assert 'M1' not in (root / 'evidence_ledger.md').read_text(encoding='utf-8')
    assert '[M] 材料 2 条' in (root / 'conformance.md').read_text(encoding='utf-8')


def test_b_stage_without_materials_declares_coverage_boundary(tmp_path, monkeypatch):
    task_id, result = run_b_stage(tmp_path, monkeypatch, '', '文献事实 [1]。')
    checkpoint = result['checkpoint']
    assert checkpoint['clean'] is True, checkpoint['failures']
    assert checkpoint['materials'] == {'accepted': 0, 'rejected': []}
    root = tmp_path / task_id
    assert not (root / '非论文材料清单.md').exists()
    assert not [path for path in root.iterdir() if path.name.startswith('M1_')]
    assert '未提供非论文材料' in (root / 'conformance.md').read_text(encoding='utf-8')
    assert '据材料' not in (root / '综述初稿.md').read_text(encoding='utf-8')
