#!/usr/bin/env python3
"""Browser-acceptance API server.

Real FastAPI routes, SQLite persistence, cookies and artifact downloads are used.
Only paid/remote search, model generation, RQ and the recursive Skill regression
runner are replaced by deterministic local fixtures. Graph HTML is produced by
the project's actual GraphService and renderer from the checked-in graph fixtures.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = E2E_DIR.parent
PROJECT_ROOT = FRONTEND_DIR.parent
RUN_ID = os.environ.get(
    'ACCEPTANCE_RUN_ID',
    f'main-{os.environ.get("ACCEPTANCE_BACKEND_PORT", "8000")}',
)
RUNTIME_DIR = FRONTEND_DIR / 'test-results' / RUN_ID / 'acceptance-runtime'
DB_PATH = RUNTIME_DIR / 'acceptance.db'
ARTIFACT_ROOT = RUNTIME_DIR / 'artifacts'
GRAPH_TEMPLATE = RUNTIME_DIR / 'graph-template'
REPORT_TEMPLATE = RUNTIME_DIR / 'report-template'
GRAPH_FIXTURES = PROJECT_ROOT / 'backend' / 'tests' / 'fixtures' / 'graphs'
REPORT_FIXTURE = PROJECT_ROOT / 'fixtures' / 'hcc-20261122'

shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'
os.environ['ARTIFACT_ROOT'] = str(ARTIFACT_ROOT)
os.environ['SESSION_SECRET'] = 'browser-acceptance-session-secret'
os.environ['ADMIN_TOKEN'] = 'browser-acceptance-admin-token'
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
os.environ.pop('QODER_SITES_ORIGIN', None)
os.environ.pop('WORKER_SHARED_SECRET', None)
os.environ.pop('QWEN_API_KEY', None)

sys.path.insert(0, str(PROJECT_ROOT / 'backend'))

import fakeredis  # noqa: E402
import uvicorn  # noqa: E402
from docx import Document  # noqa: E402
from pptx import Presentation  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.graph_artifacts import build_graph_artifacts  # noqa: E402
from app.graphs import GraphService  # noqa: E402
from app.models import Task, TaskJob, TaskProgress  # noqa: E402
from app.rate_limit import DEFAULT_RULES, RateLimiter, RateLimitRule, get_rate_limiter  # noqa: E402
from app.skill_versions import SkillVersionService, load_base_config  # noqa: E402
import app.main as main  # noqa: E402
import app.queueing as queueing  # noqa: E402


def load_fixture(name):
    return json.loads((GRAPH_FIXTURES / name).read_text(encoding='utf-8'))


def prepare_graph_template():
    GRAPH_TEMPLATE.mkdir(parents=True, exist_ok=True)
    translations = {
        'Cancer Immunotherapy and Biomarkers': '癌症免疫治疗与生物标志物',
        'Hepatocellular Carcinoma Treatment and Prognosis': '肝细胞癌治疗与预后',
        'Immune cells in cancer': '癌症中的免疫细胞',
        'Colorectal Cancer Treatments and Studies': '结直肠癌治疗与研究',
    }
    GraphService().build(
        pools={'all': load_fixture('papers_all.json'), 'limited': load_fixture('papers.json')},
        stats={
            'year': load_fixture('stats_year.json'),
            'topics': {
                'all': load_fixture('stats_topics_all.json'),
                'limited': load_fixture('stats_topics_limited.json'),
            },
            'series': [load_fixture(f'stats_series_{index}.json') for index in range(1, 5)],
        },
        analysis=load_fixture('analysis.json'),
        topic='肝癌免疫治疗耐药机制的最新进展',
        condition='模式 A；真实浏览器验收样本',
        sources='OpenAlex 聚合与论文池夹具',
        translations=translations,
        generated_at='2026-11-24',
        output_dir=GRAPH_TEMPLATE,
    )
    build_graph_artifacts(GRAPH_TEMPLATE, '肝癌免疫治疗耐药机制', 50)
    shutil.copy2(GRAPH_FIXTURES / 'papers.json', GRAPH_TEMPLATE / 'papers.json')


def prepare_report_template():
    REPORT_TEMPLATE.mkdir(parents=True, exist_ok=True)
    body = (REPORT_FIXTURE / '综述初稿.md').read_text(encoding='utf-8')
    outline = (
        '# 提纲\n\n'
        '1. 背景与演进\n2. 主要研究格局与进展\n3. 分歧与争议\n'
        '4. 空白证据表与发展趋势\n5. 可做方向卡与排序\n6. 池内分布与结论\n7. 参考文献\n'
    )
    sample = (
        '# 样章\n\n## 免疫微环境：从单一细胞走向空间生态\n\n'
        '髓系 IL-8/CXCR2 通路与 MDSC 迁移、免疫抑制及免疫检查点治疗不应答相关[2]。\n'
        '空间组学进一步揭示多类细胞与空间位置共同塑造耐药生态[12]。\n'
    )
    (REPORT_TEMPLATE / '综述初稿.md').write_text(body, encoding='utf-8')
    (REPORT_TEMPLATE / 'outline.md').write_text(outline, encoding='utf-8')
    (REPORT_TEMPLATE / 'sample.md').write_text(sample, encoding='utf-8')
    (REPORT_TEMPLATE / 'verify_report.txt').write_text(
        '[PASS] 提纲、样章、正文、参考文献和交付文件均已读取。\n'
        '[PASS] 正文引用编号与参考文献夹具一致。\n'
        '[BOUNDARY] 本结果只覆盖浏览器验收夹具，不代表实时检索或模型生成质量。\n',
        encoding='utf-8',
    )
    (REPORT_TEMPLATE / 'conformance.md').write_text(
        '# 需求对账与覆盖边界\n\n'
        '- 已覆盖：匿名流程、图谱、调整、交付、下载、历史与管理界面。\n'
        '- 边界：外部 OpenAlex、付费模型、RQ/Redis 与生产存储不在本次执行范围。\n',
        encoding='utf-8',
    )
    (REPORT_TEMPLATE / 'dialogue.json').write_text(json.dumps({
        'topic': '肝癌免疫治疗耐药机制',
        'points': ['动态多组学耐药分型', '乳酸—巨噬细胞机制干预', '宿主因素分层'],
        'representative_references': [1, 2, 12],
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    document = Document()
    document.add_heading('肝癌免疫治疗耐药机制调研报告', 0)
    document.add_paragraph('真实浏览器验收生成文件。')
    document.add_paragraph('复核边界：本地确定性夹具，不用于临床或正式研究结论。')
    document.save(REPORT_TEMPLATE / '综述初稿.docx')

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    slide.shapes.title.text = '肝癌免疫治疗耐药机制'
    slide.placeholders[1].text = '真实浏览器验收 · 图谱与证据回溯'
    presentation.save(REPORT_TEMPLATE / '肝癌免疫治疗耐药机制组会汇报.pptx')


class FixtureCandidates:
    def generate(self, direction, mode):
        return [
            {
                'value': 'hepatocellular carcinoma',
                'label': '肝细胞癌（命中 1280）',
                'description': '疾病主题',
                'preview': 'hepatocellular carcinoma',
            },
            {
                'value': 'immunotherapy resistance',
                'label': '免疫治疗耐药（命中 436）',
                'description': '机制主题',
                'preview': 'immunotherapy resistance',
            },
            {
                'value': 'tumor microenvironment',
                'label': '肿瘤免疫微环境（命中 702）',
                'description': '微环境主题',
                'preview': 'tumor microenvironment',
            },
        ]

    def generate_project_themes(self, direction):
        return [
            {
                'value': 'theme-1',
                'label': '肝癌免疫治疗耐药的髓系代谢机制与分层验证',
                'description': '识别可干预的髓系代谢机制并形成分层验证方案。',
                'preview': '研究对象：肝癌免疫治疗耐药患者队列\n方法：单细胞与空间转录组\n预期产出：机制分层框架与验证方案',
                'theme': {
                    'name': '肝癌免疫治疗耐药的髓系代谢机制与分层验证',
                    'goal': '识别可干预的髓系代谢机制并形成分层验证方案。',
                    'object': '肝癌免疫治疗耐药患者队列',
                    'method': '单细胞与空间转录组',
                    'expected_output': '机制分层框架与验证方案',
                },
            },
            {
                'value': 'theme-2',
                'label': 'IL-8/CXCR2 通路动态监测与联合干预评价',
                'description': '建立 IL-8/CXCR2 动态监测指标并评价联合干预。',
                'preview': '研究对象：免疫治疗应答与不应答患者\n方法：纵向队列与通路阻断实验\n预期产出：动态监测指标与干预评价报告',
                'theme': {
                    'name': 'IL-8/CXCR2 通路动态监测与联合干预评价',
                    'goal': '建立 IL-8/CXCR2 动态监测指标并评价联合干预。',
                    'object': '免疫治疗应答与不应答患者',
                    'method': '纵向队列与通路阻断实验',
                    'expected_output': '动态监测指标与干预评价报告',
                },
            },
        ]


class FixtureQueue:
    def enqueue_stage(self, task_id, stage):
        with SessionLocal() as db:
            progress = db.get(TaskProgress, task_id) or TaskProgress(task_id=task_id)
            progress.stage = stage
            progress.message = '等待检索与论文池整理' if stage == 'search' else '等待生成交付文件'
            progress.checkpoint = None
            job = db.query(TaskJob).filter_by(task_id=task_id, kind=stage).first()
            if job is not None:
                job.status = 'queued'
            db.add(progress)
            db.commit()
        thread = threading.Thread(target=self._run, args=(task_id, stage), daemon=True)
        thread.start()
        return {'id': f'acceptance-{stage}-{task_id}'}

    def _run(self, task_id, stage):
        try:
            time.sleep(1.2)
            task_dir = ARTIFACT_ROOT / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            template = GRAPH_TEMPLATE if stage == 'search' else REPORT_TEMPLATE
            for source in template.iterdir():
                if source.is_file():
                    shutil.copy2(source, task_dir / source.name)
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                progress = db.get(TaskProgress, task_id)
                job = db.query(TaskJob).filter_by(task_id=task_id, kind=stage).first()
                if stage == 'search':
                    task.state = 'dashboard_ready'
                    task.next_card = 'adjustment'
                    progress.message = '双范围检索、分析与七类图谱已生成'
                else:
                    task.state = 'done'
                    task.next_card = None
                    progress.message = '交付文件已生成；请查看交付文件'
                progress.stage = stage
                progress.checkpoint = {'fixture': True, 'stage': stage}
                if job is not None:
                    job.status = 'completed'
                db.commit()
        except Exception:
            traceback.print_exc()
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                progress = db.get(TaskProgress, task_id)
                task.state = 'error'
                progress.message = '验收夹具执行失败，请查看服务日志。'
                db.commit()


prepare_graph_template()
prepare_report_template()

limiter = RateLimiter(connection=fakeredis.FakeStrictRedis())
limiter.rules = {
    operation: {
        dimension: RateLimitRule(limit=1000, window_seconds=3600)
        for dimension in dimensions
    }
    for operation, dimensions in DEFAULT_RULES.items()
}
main.app.dependency_overrides[get_rate_limiter] = lambda: limiter
queueing.get_rate_limiter = lambda: limiter
main.queue_adapter = FixtureQueue()
main.candidate_service = FixtureCandidates()
main.skill_regression_runner = lambda config: {
    'passed': True,
    'checks': {'deterministic_acceptance_fixture': 'passed'},
}

with SessionLocal() as db:
    service = SkillVersionService(db)
    draft = service.create_draft(None, load_base_config(), actor='browser-acceptance')
    service.run_regression(
        draft.id,
        lambda config: {'passed': True, 'checks': {'seed': 'passed'}},
        actor='browser-acceptance',
    )
    service.publish(draft.id, actor='browser-acceptance')


if __name__ == '__main__':
    uvicorn.run(
        main.app,
        host='127.0.0.1',
        port=int(os.environ.get('ACCEPTANCE_BACKEND_PORT', '8000')),
        log_level='warning',
    )
