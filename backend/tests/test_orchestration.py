import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.delivery import DeliveryResult
from app.models import Base, InviteSession, SkillVersion, Task
from app.orchestration import Orchestrator, register_stage_services


PAPERS = [
    {'ref_no': 1, 'title': 'One', 'abstract': 'One abstract sentence.', 'evidence_level': 'B', 'claim_eligible': True},
    {'ref_no': 2, 'title': 'Two', 'abstract': 'Two abstract sentence.', 'evidence_level': 'A', 'claim_eligible': True},
]


@pytest.fixture
def session_factory():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db(session_factory, monkeypatch):
    monkeypatch.setattr('app.orchestration.SessionLocal', session_factory)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def task(db):
    db.add(InviteSession(id='owner'))
    db.add(SkillVersion(
        id='version-old', version=1, state='published',
        content={'templates': {'A': 'PINNED A TEMPLATE'}}, content_hash='hash',
        created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
    ))
    task = Task(id='task-1', session_id='owner', skill_version_id='version-old')
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def stage_input(form='A', years=None, mode='A', c_route=None, custom=None, theme=None):
    mode_value = {'mode': mode}
    if c_route is not None:
        mode_value['c_route'] = c_route
    if custom is not None:
        mode_value['custom'] = custom
    if theme is not None:
        mode_value['theme'] = theme
    return {
        'answers': [
            {'card_id': 'direction', 'value': {'direction': '城市内涝'}},
            {'card_id': 'mode', 'value': mode_value},
            {'card_id': 'terms', 'value': {'terms': ['urban flooding']}},
            {'card_id': 'years', 'value': years or {'years': 'D'}},
            {'card_id': 'delivery', 'value': {'delivery': form}},
        ],
    }


class FakeSearch:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def run(self, request):
        self.request = request
        for name in ('papers.json', 'papers_all.json'):
            (self.output_dir / name).write_text(json.dumps({'count': 2, 'papers': PAPERS}), encoding='utf-8')
        (self.output_dir / 'search_log.md').write_text('OpenAlex test double', encoding='utf-8')
        return {
            'limited': {'count': 2, 'papers': PAPERS},
            'unlimited': {'count': 2, 'papers': PAPERS},
        }


class FakeAnalysis:
    def __init__(self, model):
        self.model = model

    def classify(self, papers):
        return {'clusters': [{'ref': 1, 'name': '损失评估'}], 'methods': [{'ref': 1, 'family': '计算建模', 'technique': '校准'}]}

    def extract_factor_votes(self, papers):
        return []

    def extract_relations(self, papers):
        return []


def graph_builder(task_dir, pools, analysis, stats, **kwargs):
    (task_dir / 'dashboard_data.json').write_text(json.dumps({'overview': '2 篇'}), encoding='utf-8')
    for name in ('desktop.html', 'mobile.html', 'index.html'):
        (task_dir / name).write_text('<html>real graph fixture</html>', encoding='utf-8')
    return {'artifact_count': 4, 'pools': pools, 'analysis': analysis, 'stats': stats}


def writing_factory(workspace_root, model, version):
    class FakeWriting:
        def __init__(self):
            self.version = version

        def produce(self, writing_task, body_writer=None):
            body_path = workspace_root / writing_task.id / '综述初稿.md'
            body_path.write_text('真实写作服务测试正文 [1]（据摘要）。', encoding='utf-8')
            (workspace_root / writing_task.id / 'evidence_ledger.md').write_text(
                '| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |\n|---|---|---|---|\n| 测试 | [1] | One abstract sentence. | B |\n',
                encoding='utf-8',
            )
            return SimpleNamespace(body_path=body_path, evidence=[{'ref': 1}])

    return FakeWriting()


def delivery_factory(workspace_root):
    class FakeDelivery:
        def deliver(self, delivery_task):
            path = workspace_root / delivery_task.id / 'report.docx'
            path.write_bytes(b'PK')
            return DeliveryResult(
                artifacts={'report.docx': path}, clean=True, failures=[], warnings=[],
            )

    return FakeDelivery()


def orchestrator(tmp_path):
    return Orchestrator(
        artifact_root=tmp_path,
        search_factory=FakeSearch,
        analysis_factory=FakeAnalysis,
        graph_builder=graph_builder,
        writing_factory=writing_factory,
        delivery_factory=delivery_factory,
        stats_runner=lambda task_dir, terms, from_year: {'terms': terms, 'from_year': from_year},
        model=object(),
    )


def test_search_builds_real_stage_outputs_and_moves_to_adjustment(task, tmp_path):
    result = orchestrator(tmp_path).search_stage(task, stage_input())

    assert result['state'] == 'dashboard_ready'
    assert result['next_card'] == 'adjustment'
    assert result['checkpoint']['limited_count'] == 2
    assert (tmp_path / task.id / 'dashboard_data.json').exists()
    assert (tmp_path / task.id / 'analysis.json').exists()
    stats = json.loads((tmp_path / task.id / 'stats.json').read_text())
    assert stats['from_year'] is None


def test_generate_uses_pinned_version_and_selected_delivery_form(task, tmp_path):
    service = orchestrator(tmp_path)
    service.search_stage(task, stage_input())
    result = service.generate_stage(task, stage_input(form='A'))

    assert result['state'] == 'done'
    assert result['checkpoint']['clean'] is True
    assert (tmp_path / task.id / 'report.docx').read_bytes() == b'PK'


def test_missing_graph_builder_fails_instead_of_claiming_dashboard_ready(task, tmp_path, monkeypatch):
    def fail_graphs(*args, **kwargs):
        raise RuntimeError('GraphService unavailable')

    monkeypatch.setattr(Orchestrator, '_default_graph_builder', fail_graphs)
    service = Orchestrator(
        artifact_root=tmp_path,
        search_factory=FakeSearch,
        analysis_factory=FakeAnalysis,
        graph_builder=None,
        stats_runner=lambda *args: {},
        model=object(),
    )

    with pytest.raises(RuntimeError, match='GraphService'):
        service.search_stage(task, stage_input())


def test_stage_registration_binds_real_search_and_generate_handlers():
    from app.queueing import STAGE_SERVICES

    register_stage_services()

    assert STAGE_SERVICES['search'].__name__ == 'search_stage'
    assert STAGE_SERVICES['generate'].__name__ == 'generate_stage'


def test_c1_c2_generates_separate_bodies_verifications_and_combined_delivery(task, tmp_path):
    produced_modes = []
    delivered_modes = []

    def c_writing_factory(workspace_root, model, version):
        class Writing:
            def produce(self, writing_task, body_writer=None):
                produced_modes.append(writing_task.mode)
                target = workspace_root / writing_task.id
                target.mkdir(parents=True, exist_ok=True)
                is_c1 = writing_task.mode == 'C1'
                filename = 'C1_引言.md' if is_c1 else 'C2_文献综述.md'
                body_path = target / filename
                last_column = '与本文研究问题的联系' if is_c1 else '可深入研究的问题'
                response = '本文纳入联合校准' if is_c1 else '如何建立联合校准'
                body_path.write_text(
                    f'{writing_task.mode} 正文 [1]（据摘要）。\n\n'
                    f'| 研究方向 | 已有进展 | 现有不足 | 文献证据 | {last_column} |\n'
                    '|---|---|---|---|---|\n'
                    f'| 联合评估 | 分别发展 | 缺少联合校准 | [1] | {response} |\n',
                    encoding='utf-8',
                )
                (target / 'evidence_ledger.md').write_text(
                    '| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |\n|---|---|---|---|\n| 测试 | 1 | One abstract sentence. | B |\n',
                    encoding='utf-8',
                )
                if is_c1:
                    (target / '写法参考卡.md').write_text('# 目标期刊写法参考卡\n', encoding='utf-8')
                return SimpleNamespace(
                    body_path=body_path,
                    outline=f'{writing_task.mode} 提纲',
                    sample=f'{writing_task.mode} 样章',
                    components=SimpleNamespace(data={'mode': writing_task.mode}),
                )
        return Writing()

    def c_delivery_factory(workspace_root):
        class Delivery:
            def verification_runner(self, delivery_task, body_path, report_name):
                report = body_path.parent / report_name
                report.write_text(f'{delivery_task.mode} passed', encoding='utf-8')
                return {'clean': True, 'failures': [], 'warnings': [], 'report': report.read_text(encoding='utf-8')}

            def deliver(self, delivery_task):
                delivered_modes.append(delivery_task.mode)
                target = workspace_root / delivery_task.id
                target.mkdir(parents=True, exist_ok=True)
                (target / 'verify_report.txt').write_text('passed', encoding='utf-8')
                artifacts = {'verify_report.txt': target / 'verify_report.txt'}
                if delivery_task.delivery_form == 'A':
                    (target / 'report.docx').write_bytes(b'PK')
                    artifacts['report.docx'] = target / 'report.docx'
                return DeliveryResult(artifacts=artifacts, clean=True, failures=[])
        return Delivery()

    service = Orchestrator(
        artifact_root=tmp_path,
        search_factory=FakeSearch,
        analysis_factory=FakeAnalysis,
        graph_builder=graph_builder,
        writing_factory=c_writing_factory,
        delivery_factory=c_delivery_factory,
        stats_runner=lambda *args: {},
        model=object(),
    )
    service.search_stage(task, stage_input(mode='C', c_route='C1+C2'))
    result = service.generate_stage(task, stage_input(form='A', mode='C', c_route='C1+C2'))

    assert produced_modes == ['C1', 'C2']
    assert delivered_modes == ['C1', 'C2', 'E']
    assert (tmp_path / task.id / 'C1_引言.md').exists()
    assert (tmp_path / task.id / 'C2_文献综述.md').exists()
    assert (tmp_path / task.id / 'verify_report_C1.txt').exists()
    assert (tmp_path / task.id / 'verify_report_C2.txt').exists()
    assert (tmp_path / task.id / 'linkage_check.md').exists()
    assert (tmp_path / task.id / 'C1_写法参考卡.md').exists()
    assert result['checkpoint']['clean'] is True
    assert result['checkpoint']['combined_delivered'] is True
    assert result['checkpoint']['linkage']['gap_consistent'] is True


def test_c_single_route_only_generates_the_selected_mode(task, tmp_path):
    produced = []
    delivered = []

    def single_writing_factory(workspace_root, model, version):
        class Writing:
            def produce(self, writing_task, body_writer=None):
                produced.append(writing_task.mode)
                target = workspace_root / writing_task.id
                target.mkdir(parents=True, exist_ok=True)
                body_path = target / ('C1_引言.md' if writing_task.mode == 'C1' else 'C2_文献综述.md')
                body_path.write_text(f'{writing_task.mode} 正文 [1]', encoding='utf-8')
                (target / 'evidence_ledger.md').write_text('| 论断 |\n|---|\n| 测试 |\n', encoding='utf-8')
                return SimpleNamespace(body_path=body_path)
        return Writing()

    def single_delivery_factory(workspace_root):
        class Delivery:
            def verification_runner(self, delivery_task, body_path, report_name):
                return {'clean': True, 'failures': [], 'warnings': []}

            def deliver(self, delivery_task):
                delivered.append(delivery_task.mode)
                return DeliveryResult(artifacts={}, clean=True, failures=[])
        return Delivery()

    service = Orchestrator(
        artifact_root=tmp_path,
        search_factory=FakeSearch,
        analysis_factory=FakeAnalysis,
        graph_builder=graph_builder,
        writing_factory=single_writing_factory,
        delivery_factory=single_delivery_factory,
        stats_runner=lambda *args: {},
        model=object(),
    )
    service.search_stage(task, stage_input(mode='C', c_route='C1'))
    service.generate_stage(task, stage_input(form='A', mode='C', c_route='C1'))

    assert produced == ['C1']
    assert delivered == ['C1']
    assert not (tmp_path / task.id / 'C2_文献综述.md').exists()
    assert (tmp_path / task.id / '用户要求台账.md').exists()


def test_default_writing_factory_enables_thinking_on_a_separate_chat_model(tmp_path):
    from types import SimpleNamespace

    from app.qwen import ChatModel

    base = ChatModel(client=object())
    service = Orchestrator(artifact_root=tmp_path, model=base)
    version = SimpleNamespace(content={})

    writing = service._default_writing_factory(tmp_path, base, version)

    assert isinstance(writing.model, ChatModel)
    assert writing.model is not base
    assert writing.model.thinking is False
    assert writing.model.request_timeout == 300
    assert writing.model.attempts == 1
    assert base.thinking is False


def test_sync_artifacts_uploads_to_web_origin(tmp_path, monkeypatch):
    import urllib.request

    from app.orchestration import Orchestrator

    task_dir = tmp_path / 'task-1'
    task_dir.mkdir()
    (task_dir / 'report.md').write_text('body', encoding='utf-8')
    monkeypatch.setenv('WORKER_SHARED_SECRET', 'worker-secret')
    monkeypatch.setenv('WEB_API_ORIGIN', 'https://web.example')

    captured = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        urllib.request,
        'urlopen',
        lambda request, timeout=0: captured.append(request) or Response(),
    )

    count = Orchestrator(artifact_root=tmp_path)._sync_artifacts(task_dir)

    assert count == 1
    assert captured[0].full_url == 'https://web.example/api/internal/artifacts/task-1/report.md'
    assert captured[0].data == b'body'


def test_sync_artifacts_skips_optional_static_dashboard_files(tmp_path, monkeypatch):
    import urllib.request

    from app.orchestration import Orchestrator

    task_dir = tmp_path / 'task-1'
    task_dir.mkdir()
    (task_dir / 'report.md').write_text('body', encoding='utf-8')
    (task_dir / '文献图谱仪表盘.html').write_text('optional', encoding='utf-8')
    monkeypatch.setenv('WORKER_SHARED_SECRET', 'worker-secret')
    monkeypatch.setenv('WEB_API_ORIGIN', 'https://web.example')
    captured = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(urllib.request, 'urlopen', lambda request, timeout=0: captured.append(request) or Response())
    count = Orchestrator(artifact_root=tmp_path)._sync_artifacts(task_dir)

    assert count == 1
    assert [request.full_url.rsplit('/', 1)[-1] for request in captured] == ['report.md']


def test_sync_artifacts_retries_a_transient_upload_failure(tmp_path, monkeypatch):
    import urllib.error
    import urllib.request

    from app.orchestration import Orchestrator

    task_dir = tmp_path / 'task-1'
    task_dir.mkdir()
    (task_dir / 'report.md').write_text('body', encoding='utf-8')
    monkeypatch.setenv('WORKER_SHARED_SECRET', 'worker-secret')
    monkeypatch.setenv('WEB_API_ORIGIN', 'https://web.example')
    attempts = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout=0):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise urllib.error.URLError('temporary gateway failure')
        return Response()

    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    count = Orchestrator(artifact_root=tmp_path)._sync_artifacts(task_dir)

    assert count == 1
    assert len(attempts) == 2
    assert attempts[0] == 30


def test_default_writing_factory_can_enable_thinking(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.qwen import ChatModel

    base = ChatModel(client=object())
    service = Orchestrator(artifact_root=tmp_path, model=base)
    monkeypatch.setenv('QWEN_WRITING_THINKING', 'true')

    writing = service._default_writing_factory(tmp_path, base, SimpleNamespace(content={}))

    assert writing.model.thinking is True
    assert writing.model.request_timeout == 600


def test_e_mode_passes_custom_purpose_to_writing_and_delivers_word(task, tmp_path):
    captured = {}

    def e_writing_factory(workspace_root, model, version):
        class Writing:
            def produce(self, writing_task, body_writer=None):
                captured['writing_mode'] = writing_task.mode
                captured['custom_purpose'] = writing_task.custom_purpose
                captured['project'] = writing_task.project
                target = workspace_root / writing_task.id
                target.mkdir(parents=True, exist_ok=True)
                body_path = target / '综述初稿.md'
                body_path.write_text('按自定义用途组织的正文 [1]（据摘要）。', encoding='utf-8')
                (target / 'evidence_ledger.md').write_text(
                    '| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |\n|---|---|---|---|\n'
                    '| 测试 | 1 | One abstract sentence. | B |\n',
                    encoding='utf-8',
                )
                return SimpleNamespace(
                    body_path=body_path,
                    outline='按用户用途定制的提纲',
                    sample='',
                    components=SimpleNamespace(data={'markdown': '用途落实'}),
                )
        return Writing()

    def e_delivery_factory(workspace_root):
        class Delivery:
            def deliver(self, delivery_task):
                captured['delivery_mode'] = delivery_task.mode
                captured['delivery_form'] = delivery_task.delivery_form
                target = workspace_root / delivery_task.id
                target.mkdir(parents=True, exist_ok=True)
                word = target / '综述初稿.docx'
                word.write_bytes(b'PK')
                return DeliveryResult(artifacts={'综述初稿.docx': word}, clean=True, failures=[])
        return Delivery()

    service = Orchestrator(
        artifact_root=tmp_path,
        search_factory=FakeSearch,
        analysis_factory=FakeAnalysis,
        graph_builder=graph_builder,
        writing_factory=e_writing_factory,
        delivery_factory=e_delivery_factory,
        stats_runner=lambda *args: {},
        model=object(),
    )
    answers = stage_input(
        form='A',
        mode='E',
        custom='为学院写一份面向政策制定的交通安全证据简报',
    )
    service.search_stage(task, answers)
    result = service.generate_stage(task, answers)

    assert captured['writing_mode'] == 'E'
    assert captured['custom_purpose'] == '为学院写一份面向政策制定的交通安全证据简报'
    assert captured['delivery_mode'] == 'E'
    assert captured['delivery_form'] == 'A'
    assert (tmp_path / task.id / '综述初稿.docx').read_bytes() == b'PK'
    assert result['checkpoint']['clean'] is True


def test_writing_task_carries_selected_b_theme_and_e_custom_purpose(task, tmp_path):
    service = Orchestrator(artifact_root=tmp_path, model=object())
    theme = {
        'name': '项目主题甲',
        'goal': '目标甲',
        'object': '对象甲',
        'method': '方法甲',
        'expected_output': '产出甲',
    }
    b_task = service._writing_task(
        task,
        {'mode': {'mode': 'B', 'project': {'name': '项目主题甲', 'goal': '目标甲'}, 'theme': theme}},
        'B',
        [],
        {},
    )
    assert b_task.project['theme'] == theme
    assert b_task.custom_purpose == ''

    e_task = service._writing_task(
        task,
        {'mode': {'mode': 'E', 'custom': '为政策制定写证据简报'}},
        'E',
        [],
        {},
    )
    assert e_task.custom_purpose == '为政策制定写证据简报'
    assert e_task.mode == 'E'


def test_requirements_ledger_covers_b_d_e_and_delivery_shape():
    from app.orchestration import _requirements_ledger_text

    b = _requirements_ledger_text({
        'mode': {'mode': 'B', 'theme': {'name': '主题'}, 'project': {'name': '项目', 'goal': '目标', 'funding': '面上'}},
        'delivery': {'form': 'A'},
    })
    assert '用途模式：B' in b and '交付形式：正式调研报告（Word）' in b

    d = _requirements_ledger_text({
        'mode': {'mode': 'D', 'team_context': ''},
        'delivery': {'form': 'C'},
    })
    assert '未提供团队背景' in d and '交付形式：展示 PPT' in d

    e = _requirements_ledger_text({'mode': {'mode': 'E', 'custom': '政策简报'}, 'delivery': {'form': 'B'}})
    assert '自定义用途：政策简报' in e and '交付形式：仅对话要点与代表文献' in e
