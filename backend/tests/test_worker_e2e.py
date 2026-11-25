"""Offline end-to-end acceptance through the real API and a real RQ worker.

Only this test and backend/tests/fixtures/worker are added. Production code,
frontend code and rate-limit files are intentionally untouched.
"""

import hashlib
import importlib.util
import io
import json
import logging
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import fakeredis
import pytest
import rq.job
import rq.worker
from fastapi.testclient import TestClient
from PIL import Image
from rq.job import Job
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis import AnalysisService
from app.config import get_settings
from app.db import get_db
from app.delivery import DeliveryService
from app.graphs import CHART_ORDER
from app.main import app
from app import queueing as queueing_module
from app.models import Base, SkillVersion, Task, TaskAnswer, TaskEvent, TaskJob
from app.orchestration import Orchestrator
from app.queueing import QUEUE_NAME, ProtectedSimpleWorker, QueueAdapter, STAGE_SERVICES
from app.schemas import CardId, TaskState
from app.skill_versions import SkillVersionService, load_base_config


FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures' / 'worker'
RESULT_ROOT = FIXTURE_ROOT / 'results'
_spec = importlib.util.spec_from_file_location('offline_worker_e2e', FIXTURE_ROOT / 'offline.py')
offline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offline)


@pytest.fixture
def session_factory():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def harness(monkeypatch, session_factory, tmp_path):
    artifact_root = tmp_path / 'artifacts'
    monkeypatch.setenv('ARTIFACT_ROOT', str(artifact_root))
    monkeypatch.setenv('SESSION_SECRET', 'offline-worker-e2e-session-secret')
    for name in (
        'QODER_SITES_ORIGIN', 'WORKER_SHARED_SECRET', 'OPENAI_API_KEY',
        'DASHSCOPE_API_KEY', 'QWEN_API_KEY',
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    def forbidden_network(*args, **kwargs):
        raise AssertionError('online access is forbidden in worker e2e acceptance')

    monkeypatch.setattr('urllib.request.urlopen', forbidden_network)
    monkeypatch.setattr('socket.create_connection', forbidden_network)
    monkeypatch.setattr('app.db.SessionLocal', session_factory)
    monkeypatch.setattr('app.task_flow.SessionLocal', session_factory)
    monkeypatch.setattr('app.queueing.SessionLocal', session_factory)
    monkeypatch.setattr('app.orchestration.SessionLocal', session_factory)

    connection = fakeredis.FakeStrictRedis()
    adapter = QueueAdapter(connection=connection, session_factory=session_factory)
    monkeypatch.setattr('app.main.queue_adapter', adapter)
    monkeypatch.setattr(
        'app.main.candidate_service',
        type('OfflineCandidates', (), {'generate': lambda self, direction, mode: []})(),
    )

    search_requests = []
    model = offline.OfflineQwen()

    def search_factory(output_dir):
        return offline.OfflineOpenAlex(output_dir, requests=search_requests)

    def delivery_factory(workspace_root):
        return DeliveryService(
            workspace_root=workspace_root,
            reference_checker=offline.offline_reference_checker,
        )

    orchestrator = Orchestrator(
        artifact_root=artifact_root,
        search_factory=search_factory,
        analysis_factory=AnalysisService,
        delivery_factory=delivery_factory,
        stats_runner=offline.offline_stats,
        model=model,
    )
    monkeypatch.setitem(STAGE_SERVICES, 'search', orchestrator.search_stage)
    monkeypatch.setitem(STAGE_SERVICES, 'generate', orchestrator.generate_stage)

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, base_url='https://testserver')
    with session_factory() as db:
        versions = SkillVersionService(db)
        draft = versions.create_draft(None, load_base_config(), actor='offline-worker-e2e')
        versions.run_regression(draft.id, lambda config: {'passed': True}, actor='offline-worker-e2e')
        versions.publish(draft.id, actor='offline-worker-e2e')

    yield SimpleNamespace(
        client=client,
        session_factory=session_factory,
        artifact_root=artifact_root,
        connection=connection,
        adapter=adapter,
        queue=adapter.queue,
        orchestrator=orchestrator,
        model=model,
        search_requests=search_requests,
    )

    client.close()
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def _answer(harness, task_id, card, value):
    response = harness.client.post(
        f'/api/tasks/{task_id}/answers/{card}',
        json={'value': value},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _task_payload(harness, task_id):
    response = harness.client.get(f'/api/tasks/{task_id}')
    assert response.status_code == 200, response.text
    return response.json()


def _run_real_worker(harness, scenario, stage):
    """Use SimpleWorker, an RQ Worker subclass that executes without forking."""

    job_ids = harness.queue.get_job_ids()
    assert len(job_ids) == 1, job_ids
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    rq_logger = logging.getLogger('rq')
    rq_logger.addHandler(handler)
    rq_logger.setLevel(logging.INFO)
    try:
        worker = ProtectedSimpleWorker(
            [harness.queue],
            connection=harness.connection,
            name=f'offline-e2e-{scenario}-{stage}-{uuid4().hex[:8]}',
        )
        assert worker.work(burst=True, logging_level='INFO') is True
    finally:
        rq_logger.removeHandler(handler)
        handler.close()
    jobs = [Job.fetch(job_id, connection=harness.connection) for job_id in job_ids]
    log_text = log_stream.getvalue()
    assert all(job_id in log_text for job_id in job_ids), log_text
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = RESULT_ROOT / f'{scenario}-{stage}-worker.log'
    log_path.write_text(log_text, encoding='utf-8')
    return {
        'worker_class': type(worker).__name__,
        'burst': True,
        'job_ids': job_ids,
        'job_statuses': [job.get_status() for job in jobs],
        'job_func_names': [job.func_name for job in jobs],
        'queue_count_after': harness.queue.count,
        'log_file': log_path.name,
        'log_text': log_text,
    }


def _database_snapshot(harness, task_id):
    with harness.session_factory() as db:
        task = db.get(Task, task_id)
        events = (
            db.query(TaskEvent)
            .filter_by(task_id=task_id)
            .order_by(TaskEvent.id)
            .all()
        )
        jobs = db.query(TaskJob).filter_by(task_id=task_id).order_by(TaskJob.kind).all()
        answers = db.query(TaskAnswer).filter_by(task_id=task_id).order_by(TaskAnswer.id).all()
        return {
            'state': task.state,
            'next_card': task.next_card,
            'jobs': [
                {'id': job.id, 'kind': job.kind, 'status': job.status, 'answer_id': job.answer_id}
                for job in jobs
            ],
            'answers': [
                {
                    'card_id': answer.card_id,
                    'result_state': answer.result_state,
                    'next_card': answer.next_card,
                    'job_id': answer.job_id,
                }
                for answer in answers
            ],
            'events': [
                {'kind': event.event_type, 'payload': event.payload}
                for event in events
            ],
            'progress': None if task.progress is None else {
                'stage': task.progress.stage,
                'message': task.progress.message,
                'input_hash': task.progress.input_hash,
                'checkpoint': task.progress.checkpoint,
                'traceback': task.progress.traceback,
            },
        }


def _artifact_manifest(artifact_root):
    manifest = []
    for path in sorted(artifact_root.rglob('*')):
        if not path.is_file():
            continue
        content = path.read_bytes()
        manifest.append({
            'path': path.relative_to(artifact_root).as_posix(),
            'size': len(content),
            'sha256': hashlib.sha256(content).hexdigest(),
        })
    return manifest


def _save_record(scenario, record):
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    record['recorded_at'] = datetime.now(timezone.utc).isoformat()
    path = RESULT_ROOT / f'{scenario}.json'
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        f"WORKER_E2E {scenario}: states={record['states']} "
        f"rq={record['rq']} artifacts={len(record.get('artifacts', []))}"
    )


def _start_through_years(harness, mode_value):
    session_response = harness.client.post('/api/session', json={})
    assert session_response.status_code == 201, session_response.text
    created = harness.client.post('/api/tasks', json={})
    assert created.status_code == 201, created.text
    task_id = created.json()['id']
    _answer(harness, task_id, 'direction', {'direction': '城市内涝与地下车库韧性'})
    _answer(harness, task_id, 'mode', mode_value)
    _answer(harness, task_id, 'terms', {'terms': ['urban flooding', 'underground garage']})
    years_value = {'choice': 'B', 'from_year': 2020}
    years = _answer(harness, task_id, 'years', years_value)
    assert years['state'] == TaskState.SEARCHING.value
    assert years['job_id']
    repeated = _answer(harness, task_id, 'years', years_value)
    assert repeated['job_id'] == years['job_id']
    assert harness.queue.count == 1
    with harness.session_factory() as db:
        assert db.query(TaskAnswer).filter_by(task_id=task_id, card_id='years').count() == 1
        assert db.query(TaskJob).filter_by(task_id=task_id, kind='search').count() == 1
    return task_id


def _complete_flow(harness, scenario, mode_value, form):
    states = ['searching']
    task_id = _start_through_years(harness, mode_value)
    search_rq = _run_real_worker(harness, scenario, 'search')
    assert search_rq['job_statuses'] == ['finished'], search_rq['log_text']
    assert search_rq['queue_count_after'] == 0
    dashboard = _task_payload(harness, task_id)
    assert dashboard['state'] == TaskState.DASHBOARD_READY.value
    assert dashboard['next_card'] == CardId.ADJUSTMENT.value
    states.append('dashboard_ready')
    search_checkpoint = dashboard['progress']['checkpoint']

    adjustment = _answer(harness, task_id, 'adjustment', {'adjustment': ['continue']})
    assert adjustment['state'] == TaskState.ADJUSTING.value
    assert adjustment['next_card'] == CardId.DELIVERY.value
    assert harness.queue.count == 0
    states.append('adjusting')

    delivery = _answer(harness, task_id, 'delivery', {'form': form})
    assert delivery['state'] == TaskState.GENERATING.value
    assert delivery['job_id']
    repeated_delivery = _answer(harness, task_id, 'delivery', {'form': form})
    assert repeated_delivery['job_id'] == delivery['job_id']
    assert harness.queue.count == 1
    with harness.session_factory() as db:
        assert db.query(TaskAnswer).filter_by(task_id=task_id, card_id='delivery').count() == 1
        assert db.query(TaskJob).filter_by(task_id=task_id, kind='generate').count() == 1
    states.append('generating')

    generate_rq = _run_real_worker(harness, scenario, 'generate')
    assert generate_rq['job_statuses'] == ['finished'], generate_rq['log_text']
    assert generate_rq['queue_count_after'] == 0
    done = _task_payload(harness, task_id)
    assert done['state'] == TaskState.DONE.value
    assert done['next_card'] is None
    states.append('done')
    if not done['progress']['checkpoint']['clean']:
        failure_report = harness.artifact_root / task_id / 'verify_report.txt'
        print('WORKER_VERIFY_FAILURE\n' + failure_report.read_text(encoding='utf-8'))
    snapshot = _database_snapshot(harness, task_id)
    assert snapshot['progress']['traceback'] is None
    assert [job['status'] for job in snapshot['jobs']] == ['completed', 'completed']
    event_kinds = [event['kind'] for event in snapshot['events']]
    assert event_kinds.count('queued') == 2
    assert event_kinds.count('started') == 2
    assert event_kinds.count('checkpoint') == 2
    assert event_kinds.count('completed') == 2
    assert 'failed' not in event_kinds

    return {
        'scenario': scenario,
        'task_id': task_id,
        'states': states,
        'rq': {'search': search_rq, 'generate': generate_rq},
        'checkpoints': {'search': search_checkpoint, 'generate': done['progress']['checkpoint']},
        'database': snapshot,
        'search_requests': harness.search_requests,
        'offline_model_calls': harness.model.calls,
    }


def _assert_real_dashboard(harness, record):
    task_dir = harness.artifact_root / record['task_id']
    checkpoint = record['checkpoints']['search']
    assert checkpoint['stage'] == 'search'
    assert checkpoint['limited_count'] == 2
    assert checkpoint['unlimited_count'] == 3
    assert checkpoint['graph_artifacts'] == 6
    assert checkpoint['storage_synced'] == 0
    assert len(checkpoint['input_hash']) == 64

    dashboard = json.loads((task_dir / 'dashboard_data.json').read_text(encoding='utf-8'))
    assert dashboard['chart_order'] == list(CHART_ORDER)
    assert dashboard['scope_switch']['available'] == ['all', 'limited']
    assert dashboard['scopes']['all']['pool_count'] == 3
    assert dashboard['scopes']['limited']['pool_count'] == 2
    assert dashboard['trend_status'] == 'ready'
    assert dashboard['compare_status'] == 'ready'
    for scope in ('all', 'limited'):
        scoped = dashboard['scopes'][scope]
        assert scoped['topics_status'] == 'ready'
        assert scoped['network']['status'] == 'ready'
        assert scoped['knowledge']['status'] == 'ready'
        assert scoped['methods']['status'] == 'ready'
        assert scoped['relations']['status'] == 'ready'

    analysis = json.loads((task_dir / 'analysis.json').read_text(encoding='utf-8'))
    assert set(analysis) == {'all', 'limited'}
    assert len(analysis['all']['classify']['clusters']) == 3
    assert len(analysis['limited']['classify']['clusters']) == 2
    for scoped in analysis.values():
        assert scoped['factor_votes']
        assert scoped['relations']
    assert json.loads((task_dir / 'papers.json').read_text())['count'] == 2
    assert json.loads((task_dir / 'papers_all.json').read_text())['count'] == 3

    for name in ('文献图谱仪表盘.html', 'desktop.html', 'mobile.html', 'index.html'):
        text = (task_dir / name).read_text(encoding='utf-8')
        assert '<html' in text.lower() and '</html>' in text.lower(), name
        assert '城市内涝与地下车库韧性' in text, name
    svg_path = task_dir / '文献图谱仪表盘.svg'
    svg_root = ET.parse(svg_path).getroot()
    assert svg_root.tag.endswith('svg')
    assert list(svg_root)
    png_path = task_dir / '文献图谱仪表盘.png'
    assert png_path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    with Image.open(png_path) as image:
        image.load()
        assert image.width > 0 and image.height > 0


def _assert_evidence_and_texts(task_dir, body_name, require_clean=True):
    for name in ('outline.md', 'sample.md', body_name, 'evidence_ledger.md', 'conformance.md'):
        path = task_dir / name
        assert path.is_file() and path.stat().st_size > 100, name
    body = (task_dir / body_name).read_text(encoding='utf-8')
    assert '## 参考文献' in body
    ledger = (task_dir / 'evidence_ledger.md').read_text(encoding='utf-8')
    assert offline.EVIDENCE_ONE['quotes']['1'] in ledger
    assert offline.EVIDENCE_TWO['quotes']['2'] in ledger
    ledger_refs = [
        cells[1]
        for line in ledger.splitlines()
        if line.strip().startswith('|')
        for cells in [[cell.strip() for cell in line.strip().strip('|').split('|')]]
        if len(cells) >= 4 and cells[1].isdigit()
    ]
    assert {'1', '2'} <= set(ledger_refs), ledger
    verify = (task_dir / 'verify_report.txt').read_text(encoding='utf-8')
    if require_clean:
        assert '[FAIL]' not in verify, verify
        assert '无失败' in verify, verify
    return verify


def _acceptance_linkage_review(harness, record, scenario):
    """Run the real C2 gate with C1 co-located, independently of production wiring."""

    c1_dir = harness.artifact_root / f"{record['task_id']}-C1"
    c2_dir = harness.artifact_root / f"{record['task_id']}-C2"
    original_report = (c2_dir / 'verify_report.txt').read_bytes()
    copied_c1 = c2_dir / 'C1_引言.md'
    shutil.copyfile(c1_dir / 'C1_引言.md', copied_c1)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(c2_dir / 'verify_delivery.py'),
                'C2_文献综述.md',
                '800-1200',
                '--mode',
                'C2',
            ],
            cwd=c2_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        linkage_report = (c2_dir / 'verify_report.txt').read_text(encoding='utf-8')
        (c2_dir / 'worker_linkage_verify_report.txt').write_text(linkage_report, encoding='utf-8')
    finally:
        (c2_dir / 'verify_report.txt').write_bytes(original_report)
        copied_c1.unlink(missing_ok=True)
    production_c2_report = (
        harness.artifact_root / record['task_id'] / 'verify_report_C2.txt'
    ).read_text(encoding='utf-8')
    return {
        'acceptance_linkage_returncode': completed.returncode,
        'acceptance_linkage_report': f"{record['task_id']}-C2/worker_linkage_verify_report.txt",
        'acceptance_linkage_report_text': linkage_report,
        'production_c2_report_executed_linkage_gate': 'C1+C2 衔接与重复检查' in production_c2_report,
    }


@pytest.mark.parametrize(
    ('scenario', 'form'),
    [('c-pair-word', 'A'), ('c-pair-ppt', 'C')],
)
def test_c_pair_real_rq_worker_word_ppt_and_evidence(harness, scenario, form):
    record = _complete_flow(harness, scenario, {'mode': 'C', 'c_route': 'C1+C2'}, form)
    _assert_real_dashboard(harness, record)
    assert record['search_requests'] == [{
        'terms': ['urban flooding', 'underground garage'],
        'from_year': 2020,
        'mode': 'C1',
    }]
    assert [call['mode'] for call in record['offline_model_calls'] if call['stage'] == 'components'] == ['C1', 'C2']
    assert [call['mode'] for call in record['offline_model_calls'] if call['stage'] == 'body'] == ['C1', 'C2']

    task_dir = harness.artifact_root / record['task_id']
    c1_dir = harness.artifact_root / f"{record['task_id']}-C1"
    c2_dir = harness.artifact_root / f"{record['task_id']}-C2"
    c1_verify = _assert_evidence_and_texts(c1_dir, 'C1_引言.md', require_clean=False)
    c2_verify = _assert_evidence_and_texts(c2_dir, 'C2_文献综述.md', require_clean=False)
    combined_verify = _assert_evidence_and_texts(task_dir, '综述初稿.md', require_clean=False)
    record['verification'] = {
        'C1': c1_verify,
        'C2': c2_verify,
        'combined': combined_verify,
    }
    assert '⑧模式形态(--mode C1)' in c1_verify
    assert '⑧模式形态(--mode C2)' in c2_verify
    assert (task_dir / 'verify_report_C1.txt').read_bytes() == (c1_dir / 'verify_report.txt').read_bytes()
    independent_c2_lines = (c2_dir / 'verify_report.txt').read_text(encoding='utf-8').splitlines()
    root_c2_lines = (task_dir / 'verify_report_C2.txt').read_text(encoding='utf-8').splitlines()
    assert len(root_c2_lines) == len(independent_c2_lines)
    for independent_line, root_line in zip(independent_c2_lines, root_c2_lines):
        if independent_line.startswith('[PASS] ⑧模式形态(--mode C2)'):
            assert root_line.startswith(independent_line)
            assert 'C1+C2 衔接与重复检查' in root_line[len(independent_line):]
        else:
            assert root_line == independent_line
    assert (task_dir / 'outline_C1.md').stat().st_size > 100
    assert (task_dir / 'outline_C2.md').stat().st_size > 100
    assert (task_dir / 'sample_C1.md').stat().st_size > 50
    assert (task_dir / 'sample_C2.md').stat().st_size > 50
    combined_body = (task_dir / '综述初稿.md').read_text(encoding='utf-8')
    assert '## 独立文献综述' in combined_body
    assert '## 完整引言' in combined_body
    assert '## 完整综述文本' in combined_body
    conformance = (task_dir / 'conformance.md').read_text(encoding='utf-8')
    assert 'C1 与 C2 分离并分别复核' in conformance
    assert '完成衔接与重复检查' in conformance

    if form == 'A':
        word = task_dir / '综述初稿.docx'
        assert zipfile.is_zipfile(word)
        from docx import Document
        document = Document(word)
        assert len(document.paragraphs) > 20
        assert '城市内涝与地下车库韧性' in '\n'.join(p.text for p in document.paragraphs)
        assert not list(task_dir.glob('*.pptx'))
        record['office_validation'] = {
            'format': 'docx',
            'zip_container': True,
            'paragraphs': len(document.paragraphs),
        }
    else:
        ppt = task_dir / '城市内涝与地下车库韧性组会汇报.pptx'
        assert zipfile.is_zipfile(ppt)
        from pptx import Presentation
        presentation = Presentation(ppt)
        assert 8 <= len(presentation.slides) <= 12
        slide_text = '\n'.join(
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if hasattr(shape, 'text')
        )
        assert '城市内涝与地下车库韧性' in slide_text
        assert '参考文献' in slide_text
        assert not list(task_dir.glob('*.docx'))
        record['office_validation'] = {
            'format': 'pptx',
            'zip_container': True,
            'slides': len(presentation.slides),
        }

    record['linkage'] = _acceptance_linkage_review(harness, record, scenario)
    record['artifacts'] = _artifact_manifest(harness.artifact_root)
    _save_record(scenario, record)

    # Persist evidence first, then evaluate every gate so one production defect
    # cannot hide a separate linkage or evidence-ledger failure.
    acceptance_failures = []
    if record['checkpoints']['generate']['clean'] is not True:
        acceptance_failures.append('generate checkpoint clean=false: ' + json.dumps(
            record['checkpoints']['generate']['failures'], ensure_ascii=False,
        ))
    linkage = record['linkage']
    if linkage['production_c2_report_executed_linkage_gate'] is not True:
        acceptance_failures.append('production C2 report did not execute the C1+C2 linkage gate')
    if linkage['acceptance_linkage_returncode'] != 0:
        acceptance_failures.append(
            f"co-located C2 gate returned {linkage['acceptance_linkage_returncode']}:\n"
            + linkage['acceptance_linkage_report_text']
        )
    for expected in (
        '有 C1+C2 衔接与重复检查',
        '有 C1+C2 空白点一致性检查',
        '有 C1+C2 重复检查与处理',
        '有 C1+C2 空白点交叉指向',
        '有 C1+C2 无重复段落',
    ):
        if expected not in linkage['acceptance_linkage_report_text']:
            acceptance_failures.append('missing linkage check: ' + expected)
    assert not acceptance_failures, '\n\n'.join(acceptance_failures)


def test_a_dialogue_real_rq_worker_has_seven_categories_and_two_slots(harness):
    scenario = 'a-dialogue'
    record = _complete_flow(harness, scenario, {'mode': 'A'}, 'B')
    _assert_real_dashboard(harness, record)
    assert record['checkpoints']['generate']['clean'] is True, record['checkpoints']['generate']
    assert record['checkpoints']['generate']['failures'] == []
    assert [call['mode'] for call in record['offline_model_calls'] if call['stage'] == 'components'] == ['A_DIALOGUE']
    assert [call['mode'] for call in record['offline_model_calls'] if call['stage'] == 'body'] == ['A_DIALOGUE']

    task_dir = harness.artifact_root / record['task_id']
    _assert_evidence_and_texts(task_dir, '综述初稿.md')
    dialogue = json.loads((task_dir / 'dialogue.json').read_text(encoding='utf-8'))
    assert dialogue['mode'] == 'A_DIALOGUE'
    assert [group['category'] for group in dialogue['topic_groups']] == offline.DIALOGUE_CATEGORIES
    assert len(dialogue['topic_groups']) == 7
    assert all(len(group['slots']) == 2 for group in dialogue['topic_groups'])
    assert sum(len(group['slots']) for group in dialogue['topic_groups']) == 14
    assert 1 <= len(dialogue['key_points']) <= 8
    assert 1 <= len(dialogue['references']) <= 10
    assert dialogue['overall_first']['topic']
    body = (task_dir / '综述初稿.md').read_text(encoding='utf-8')
    for index, category in enumerate(offline.DIALOGUE_CATEGORIES, 1):
        assert f'## {index}. {category}' in body
    assert body.count('选题 1｜') == 7
    assert body.count('选题 2｜') == 7
    assert '## 综合第 1 推荐' in body
    assert '推荐理由：' in body and '主要风险：' in body
    assert not list(task_dir.glob('*.docx'))
    assert not list(task_dir.glob('*.pptx'))

    record['artifacts'] = _artifact_manifest(harness.artifact_root)
    _save_record(scenario, record)


def test_graph_renderer_failure_is_real_rq_and_task_error(harness, monkeypatch):
    scenario = 'graph-error'
    task_id = _start_through_years(harness, {'mode': 'A'})

    def fail_renderer(*args, **kwargs):
        raise RuntimeError('OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE')

    monkeypatch.setattr('app.graph_artifacts.build_graph_artifacts', fail_renderer)
    search_rq = _run_real_worker(harness, scenario, 'search')
    assert search_rq['job_statuses'] == ['failed'], search_rq['log_text']
    assert search_rq['queue_count_after'] == 0
    snapshot = _database_snapshot(harness, task_id)
    assert snapshot['state'] == TaskState.ERROR.value
    assert snapshot['next_card'] is None
    assert snapshot['progress']['stage'] == 'search'
    assert snapshot['progress']['checkpoint'] is None
    assert snapshot['progress']['message'] == '任务执行失败，请稍后重试。'
    assert 'OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE' in snapshot['progress']['traceback']
    assert [event['kind'] for event in snapshot['events'][-3:]] == ['queued', 'started', 'failed']
    assert not {'checkpoint', 'completed'} & {event['kind'] for event in snapshot['events']}
    assert snapshot['events'][-1]['payload']['retryable'] is True
    assert snapshot['events'][-1]['payload']['retry_action'] == {'action': 'retry_stage', 'stage': 'search'}
    assert 'traceback' not in snapshot['events'][-1]['payload']
    assert [job['status'] for job in snapshot['jobs']] == ['failed']

    task_dir = harness.artifact_root / task_id
    # Real GraphService JSON may exist; renderer failure must not be relabelled ready.
    assert (task_dir / 'dashboard_data.json').is_file()
    assert not (task_dir / '文献图谱仪表盘.html').exists()
    assert not (task_dir / 'desktop.html').exists()
    assert not (task_dir / 'mobile.html').exists()
    assert harness.queue.count == 0
    assert _task_payload(harness, task_id)['state'] == TaskState.ERROR.value

    record = {
        'scenario': scenario,
        'task_id': task_id,
        'states': ['searching', 'error'],
        'rq': {'search': search_rq},
        'database': snapshot,
        'search_requests': harness.search_requests,
        'offline_model_calls': harness.model.calls,
        'artifacts': _artifact_manifest(harness.artifact_root),
    }
    _save_record(scenario, record)


def test_sensitive_failure_real_rq_logs_events_and_response_are_redacted(
    harness, monkeypatch
):
    scenario = 'sensitive-error'
    task_id = _start_through_years(harness, {'mode': 'A'})
    environment_value = 'fake-environment-value-a90e'
    monkeypatch.setenv('WORKER_REDACTION_TEST_SECRET', environment_value)
    private_values = [
        'fake-token-redaction-7f3a',
        'fake-password-redaction-91b2',
        'fake-secret-redaction-c814',
        'fake-provider-body-private-record-52de',
        'fake_private_customers',
        'fake-url-password-63ad',
        '/Users/fake-worker/private/fake-task.db',
        r'C:\fake-server\private\fake-task.db',
        environment_value,
    ]
    marker = 'OFFLINE_FORCED_DASHBOARD_RENDERER_FAILURE'
    message = (
        f'{marker}; token=fake-token-redaction-7f3a; '
        'password="fake-password-redaction-91b2"; '
        'secret: fake-secret-redaction-c814; '
        'SQL: SELECT * FROM fake_private_customers; '
        'Provider response body={"private_record":'
        '"fake-provider-body-private-record-52de"}; '
        'redis://fake-user:fake-url-password-63ad@private.internal:6379/0; '
        '/Users/fake-worker/private/fake-task.db; '
        r'C:\fake-server\private\fake-task.db' + f'; env={environment_value}'
    )

    def fail_stage(task, stage_input):
        raise RuntimeError(message)

    monkeypatch.setitem(STAGE_SERVICES, 'search', fail_stage)
    search_rq = _run_real_worker(harness, scenario, 'search')

    assert search_rq['job_statuses'] == ['failed'], search_rq['log_text']
    snapshot = _database_snapshot(harness, task_id)
    public_payload = _task_payload(harness, task_id)
    job = Job.fetch(search_rq['job_ids'][0], connection=harness.connection)
    for module in (rq.worker, rq.job, queueing_module):
        assert str(Path(module.__file__).resolve()) not in (job.exc_info or '')
    assert '[REDACTED_PATH]' in (job.exc_info or '')
    exposed = '\n'.join([
        search_rq['log_text'],
        job.exc_info or '',
        json.dumps(snapshot, ensure_ascii=False),
        json.dumps(public_payload, ensure_ascii=False),
    ])
    for private_value in private_values:
        assert private_value not in exposed
    assert '/Users/' not in search_rq['log_text']
    assert r'C:\fake-server' not in search_rq['log_text']
    assert 'StageExecutionError' in search_rq['log_text']
    assert 'Traceback (most recent call last)' in search_rq['log_text']

    protected = snapshot['progress']['traceback']
    assert 'RuntimeError' in protected
    assert marker in protected
    assert 'SELECT' not in protected
    assert 'private_record' not in protected
    assert snapshot['progress']['stage'] == 'search'
    failure = snapshot['events'][-1]
    assert failure['kind'] == 'failed'
    assert failure['payload']['retryable'] is True
    assert failure['payload']['retry_action'] == {
        'action': 'retry_stage',
        'stage': 'search',
    }
    assert 'traceback' not in failure['payload']
    assert public_payload['progress']['message'] == '任务执行失败，请稍后重试。'
    assert 'traceback' not in public_payload['progress']

    _save_record(scenario, {
        'scenario': scenario,
        'task_id': task_id,
        'states': ['searching', 'error'],
        'rq': {'search': search_rq},
        'database': snapshot,
        'public_response': public_payload,
    })
