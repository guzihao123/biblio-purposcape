#!/usr/bin/env python3
"""Collect competition-evidence run outputs into evidence/, write result.json and
a screenshots manifest. Run after run_all.sh completes."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path('/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web')
EVID = PROJECT / 'dev' / 'acceptance' / 'competition-evidence'
RUN = EVID / 'run'
SHOTS = EVID / 'screenshots'
EVIDENCE = EVID / 'evidence'

FLOW_BY_PREFIX = {
    '01': 'A 模式：匿名入口 → 方向/用途/术语/年限确认卡 → 检索进度 → 图谱 → 交付形式 → 对话交付 → 历史',
    '02': 'B 模式：项目卡 → RQ 检索 → 七类图谱满血/轻量 → 年限调整 → Word 报告/证据复核/下载',
    '03': 'C 模式：三步固定卡 → C1+C2 衔接 → 合并 Word',
    '04': 'D 模式：团队背景 → 检索 → 20–30 页 PPT 下载',
    '05': 'Skill 管理：草稿 → 真实回归 → 发布 → 回退',
}
PAGE_HINTS = [
    ('anonymous', '匿名入口'), ('direction', '研究方向卡'), ('mode-receipt', '用途确认卡'),
    ('terms', '术语确认卡'), ('years', '年限确认卡'), ('search', '检索进度'),
    ('dashboard', '文献图谱仪表盘'), ('light', '轻量版图谱'), ('graph-evidence', '图谱证据交互面板'),
    ('b-project', 'B 项目卡'), ('delivery', '交付形式卡'), ('report', '调研交付报告'),
    ('history', '研究历史'), ('admin', 'Skill 版本管理'), ('published', 'Skill 发布结果'),
    ('rollback', 'Skill 回退结果'), ('c-mode', 'C 模式卡'), ('c-route', 'C 路线卡'),
    ('c-info', 'C 本文信息卡'), ('c-years', 'C 年限卡'), ('c-dashboard', 'C 仪表盘'),
    ('c-report', 'C 报告'), ('d-team', 'D 团队背景卡'), ('d-years', 'D 年限卡'),
    ('d-dashboard', 'D 仪表盘'), ('three-step-confirmed', 'C 三步确认'),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not RUN.exists():
        print(f'run dir missing: {RUN}', file=sys.stderr)
        return 1
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # 1. Download file hashes
    downloads = {}
    downloads_root = RUN / 'downloads'
    if downloads_root.exists():
        for path in sorted(downloads_root.rglob('*')):
            if path.is_file():
                downloads[str(path.relative_to(RUN))] = {'sha256': sha256(path), 'bytes': path.stat().st_size}
    (EVIDENCE / 'download-sha256.json').write_text(json.dumps(downloads, ensure_ascii=False, indent=2), encoding='utf-8')

    # 2. Copy run-level evidence
    copied = {}
    for pattern in ('*-layout.json', '*-browser-events.json', '*-office-verification.json',
                    '*-owner-boundary.json', '*-adjusted-search.json', '*-search-submission.json',
                    '*-first-poll.json', '*-final-task.json'):
        for path in sorted(RUN.glob(pattern)):
            target = EVIDENCE / path.name
            shutil.copy2(path, target)
            copied[path.name] = str(target.relative_to(EVID))
    for name in ('runtime.json', 'state-summary.json', 'test-exit-code.json',
                 'skill-regression-report.json', 'sanitization.log'):
        path = RUN / name
        if path.exists():
            shutil.copy2(path, EVIDENCE / name)
            copied[name] = f'evidence/{name}'
    for name in ('redis.log', 'web.log', 'worker.log', 'frontend.log'):
        path = RUN / name
        if path.exists():
            shutil.copy2(path, EVIDENCE / f'runtime-{name}')
            copied[f'runtime-{name}'] = f'evidence/runtime-{name}'

    # 2b. Skill-regression sub-suite results (produced by this run on ports 8027/5195)
    regression_summaries = {}
    for run_id, label in (('motion-8027', 'skill-regression-motion'), ('main-8027', 'skill-regression-task-browser')):
        source = PROJECT / 'frontend' / 'test-results' / run_id / 'acceptance-results.json'
        if source.exists():
            target = EVIDENCE / f'{label}-results.json'
            shutil.copy2(source, target)
            payload = json.loads(source.read_text(encoding='utf-8'))
            regression_summaries[label] = payload.get('stats', {})
    (EVIDENCE / 'skill-regression-summaries.json').write_text(
        json.dumps(regression_summaries, ensure_ascii=False, indent=2), encoding='utf-8')

    # 3. Layout summary
    layout_summary = {}
    layout_files = sorted(EVIDENCE.glob('*-layout.json'))
    for path in layout_files:
        reports = json.loads(path.read_text(encoding='utf-8'))
        ok = all('detached' not in report and report['scrollWidth'] <= report['clientWidth'] + 1
                 and not report['offenders'] for report in reports)
        layout_summary[path.name] = {'frames': len(reports), 'no_horizontal_overflow': ok}
    (EVIDENCE / 'layout-summary.json').write_text(json.dumps(layout_summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # 4. Browser events summary
    events_summary = {}
    for path in sorted(EVIDENCE.glob('*-browser-events.json')):
        events = json.loads(path.read_text(encoding='utf-8'))
        events_summary[path.name] = {'unexpected_event_count': len(events), 'events': events[:20]}
    (EVIDENCE / 'browser-events-summary.json').write_text(json.dumps(events_summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # 5. Playwright results
    results_path = EVIDENCE / 'playwright-results.json'
    tests = []
    overall_ok = False
    if results_path.exists():
        payload = json.loads(results_path.read_text(encoding='utf-8'))
        overall_ok = (payload.get('stats', {}).get('unexpected', 0) == 0)
        def visit(suite):
            for test in suite.get('specs', []):
                tests.append({
                    'title': test.get('title'),
                    'ok': test.get('ok'),
                    'duration_ms': (test.get('results') or [{}])[0].get('duration'),
                })
            for child in suite.get('suites', []):
                visit(child)
        for suite in payload.get('suites', []):
            visit(suite)

    # 6. Screenshots manifest
    manifest = []
    for path in sorted(SHOTS.glob('*.png')):
        match = re.match(r'(\d+)-(.+)-(\d+x\d+)\.png$', path.name)
        prefix = match.group(1) if match else '?'
        stem = match.group(2) if match else path.stem
        viewport = match.group(3) if match else 'unknown'
        page = next((hint for key, hint in PAGE_HINTS if key in stem), stem)
        manifest.append({
            'file': f'screenshots/{path.name}',
            'flow': FLOW_BY_PREFIX.get(prefix, '未知流程'),
            'page': page,
            'viewport': viewport,
            'sha256': sha256(path),
            'bytes': path.stat().st_size,
        })
    (EVIDENCE / 'screenshots-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    # 7. Secret/sensitive-content scan over textual evidence (screenshots are PNG, skipped here)
    secret_markers = re.compile(r'(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{20,}|ADMIN_TOKEN["\']?\s*[:=]\s*["\'][A-Za-z0-9_-]{16,}|SESSION_SECRET["\']?\s*[:=]\s*["\'][A-Za-z0-9_-]{16,})')
    findings = []
    for path in sorted(EVIDENCE.rglob('*')):
        if path.is_file() and path.suffix.lower() not in {'.png', '.jpg', '.webm'}:
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if secret_markers.search(line):
                    findings.append({'file': str(path.relative_to(EVID)), 'line': line_no})
    (EVIDENCE / 'sensitive-scan.json').write_text(json.dumps(
        {'pattern': 'api-key / bearer / raw ADMIN_TOKEN / raw SESSION_SECRET', 'findings': findings},
        ensure_ascii=False, indent=2), encoding='utf-8')

    exit_codes = json.loads((RUN / 'test-exit-code.json').read_text(encoding='utf-8')) if (RUN / 'test-exit-code.json').exists() else {}

    result = {
        'package': '本地候选比赛证据包（非公开发布证明）',
        'run_id_prefix': 'competition-',
        'generated_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'environment': {
            'browser': 'Chromium (Playwright 1.65.1, headless)',
            'backend': 'real FastAPI + SQLite + RQ worker + redislite Redis',
            'providers': 'offline HCC OpenAlex/statistics/model/reference fixtures; 未调用真实 OpenAlex/千问或任何付费模型',
            'ports': {'api': 8026, 'skill_regression_api': 8027, 'frontend': 5194,
                      'skill_regression_frontend': 5195, 'redis': 6394},
            'run_dir': 'dev/acceptance/competition-evidence/run',
        },
        'viewports': {'desktop': '1440x900', 'narrow': '390x844'},
        'tests': tests,
        'checks': {
            'all_tests_passed': overall_ok,
            'layout_audits': layout_summary,
            'browser_event_files': {name: item['unexpected_event_count'] for name, item in events_summary.items()},
            'downloads': downloads,
            'exit_codes': exit_codes,
            'sensitive_scan_findings': findings,
        },
        'artifacts': copied,
        'skill_regression_suites': regression_summaries,
        'screenshots_manifest': 'evidence/screenshots-manifest.json',
        'boundaries': [
            '真实 Provider（OpenAlex/千问）未验证，仅离线确定性夹具',
            '云 Storage、公网部署、公开 URL 未创建未验证',
            'PowerPoint 桌面端渲染（LibreOffice/QuickLook 视觉验收）未闭环',
            '本证据包为本地候选比赛证据包，不是公开发布证明',
        ],
    }
    (EVID / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': str(EVID / 'result.json'), 'tests': len(tests),
                      'passed': overall_ok, 'layout_audits': len(layout_summary),
                      'downloads': len(downloads), 'screenshots': len(manifest),
                      'sensitive_findings': len(findings)}, ensure_ascii=False, indent=2))
    return 0 if overall_ok and not findings else 2


if __name__ == '__main__':
    raise SystemExit(main())
