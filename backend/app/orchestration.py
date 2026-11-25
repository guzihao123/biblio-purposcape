import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.analysis import AnalysisService
from app.config import get_settings
from app.db import SessionLocal
from app.delivery import DeliveryService, DeliveryTask
from app.models import SkillVersion
from app.qwen import ChatModel
from app.schemas import CardId, TaskState
from app.search import SearchRequest, SearchService
from app.sites_store import SitesStorageClient
from app.writing import WritingService, WritingTask


_GAP_COLUMNS = {
    'C1': ('研究方向', '已有进展', '现有不足', '文献证据', '与本文研究问题的联系'),
    'C2': ('研究方向', '已有进展', '现有不足', '文献证据', '可深入研究的问题'),
}


def _normalized_paragraph(text):
    return re.sub(r'\s+', '', text)


def _restore_original_citations(text, citation_map=None):
    """Return an analysis copy using papers.json ref_no instead of display numbers."""
    if not citation_map:
        return text
    display_to_ref = citation_map.get('display_to_ref', {})

    def restore(match):
        display = match.group(1)
        return f'[{display_to_ref.get(display, display)}]'

    return re.sub(r'\[(\d+)\]', restore, text)


def _research_gap_rows(text, mode):
    """Read the exact five-column gap table required by the preset verifier."""
    columns = _GAP_COLUMNS[mode]
    lines = text.split('## 参考文献')[0].splitlines()
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if cells != list(columns):
            continue
        rows = []
        for data_line in lines[index + 1:]:
            if not data_line.strip().startswith('|'):
                break
            values = [cell.strip() for cell in data_line.strip().strip('|').split('|')]
            if len(values) != len(columns) or all(re.fullmatch(r':?-+:?', value) for value in values):
                continue
            row = dict(zip(columns, values))
            rows.append({
                'direction': row['研究方向'],
                'limitation': row['现有不足'],
                'refs': tuple(sorted({int(ref) for ref in re.findall(r'\[(\d+)\]', row['文献证据'])})),
            })
        return rows
    return []


def _gap_signature(row):
    return (
        _normalized_paragraph(row['direction']),
        _normalized_paragraph(row['limitation']),
        row['refs'],
    )


def _long_paragraphs(text, citation_map=None):
    paragraphs = {}
    for paragraph in re.split(r'\n\s*\n', text.split('## 参考文献')[0]):
        analysis_paragraph = _restore_original_citations(paragraph, citation_map)
        normalized = _normalized_paragraph(analysis_paragraph)
        if len(normalized) >= 50 and not paragraph.lstrip().startswith(('#', '|')):
            paragraphs[normalized] = paragraph
    return paragraphs


def _replace_long_paragraph(text, normalized, replacement, citation_map=None):
    parts = re.split(r'(\n\s*\n)', text)
    for index in range(0, len(parts), 2):
        analysis_paragraph = _restore_original_citations(parts[index], citation_map)
        if _normalized_paragraph(analysis_paragraph) == normalized:
            parts[index] = replacement
    return ''.join(parts)


def _resolve_c_pair_linkage(c1_text, c2_text, c1_citation_map=None, c2_citation_map=None):
    """Compare original ref_no evidence, then rewrite only the less suitable display paragraph."""
    bodies = {'C1': c1_text, 'C2': c2_text}
    citation_maps = {'C1': c1_citation_map, 'C2': c2_citation_map}
    analysis_bodies = {
        mode: _restore_original_citations(bodies[mode], citation_maps[mode])
        for mode in ('C1', 'C2')
    }
    rows = {mode: _research_gap_rows(analysis_bodies[mode], mode) for mode in ('C1', 'C2')}
    failures = []
    for mode in ('C1', 'C2'):
        if not rows[mode]:
            failures.append(f'{mode} Research Gap 表缺失或没有数据行')
        for row in rows[mode]:
            if not row['direction'] or not row['limitation'] or not row['refs']:
                failures.append(f'{mode} Research Gap 表存在空白的方向、不足或引用')
    signatures = {mode: sorted(_gap_signature(row) for row in rows[mode]) for mode in ('C1', 'C2')}
    gap_consistent = bool(rows['C1'] and rows['C2']) and signatures['C1'] == signatures['C2']
    if rows['C1'] and rows['C2'] and not gap_consistent:
        failures.append('C1/C2 Research Gap 表的研究方向、现有不足或引用集合不一致')

    redirects = []
    initial_duplicates = (
        set(_long_paragraphs(c1_text, c1_citation_map))
        & set(_long_paragraphs(c2_text, c2_citation_map))
    )
    while True:
        c1_paragraphs = _long_paragraphs(bodies['C1'], c1_citation_map)
        c2_paragraphs = _long_paragraphs(bodies['C2'], c2_citation_map)
        duplicates = set(c1_paragraphs) & set(c2_paragraphs)
        if not duplicates:
            break
        for normalized in sorted(duplicates):
            positioning = ''.join(
                _restore_original_citations(paragraphs[normalized], citation_maps[mode])
                for mode, paragraphs in (('C1', c1_paragraphs), ('C2', c2_paragraphs))
            )
            keep = 'C1' if re.search(r'本文|本研究|研究思路|研究贡献', positioning) else 'C2'
            rewrite = 'C2' if keep == 'C1' else 'C1'
            replacement = (
                f'概括：该{"本文定位" if keep == "C1" else "领域证据"}段保留在 '
                f'{keep}《{"引言" if keep == "C1" else "文献综述"}》中；此处仅作交叉指向，不再重复铺陈。'
            )
            bodies[rewrite] = _replace_long_paragraph(
                bodies[rewrite], normalized, replacement, citation_maps[rewrite],
            )
            redirects.append({
                'kept': keep,
                'rewritten': rewrite,
                'reason': '本文定位内容优先留在 C1' if keep == 'C1' else '领域证据优先留在 C2',
                'fingerprint': normalized[:100],
            })
            if keep == 'C1':
                c2_paragraphs = _long_paragraphs(bodies['C2'], c2_citation_map)
            else:
                c1_paragraphs = _long_paragraphs(bodies['C1'], c1_citation_map)

    remaining = (
        set(_long_paragraphs(bodies['C1'], c1_citation_map))
        & set(_long_paragraphs(bodies['C2'], c2_citation_map))
    )
    if remaining:
        failures.append(f'重复长段处理后仍剩余 {len(remaining)} 段')
    passed = not failures
    return {
        'bodies': bodies,
        'gap_rows': rows,
        'gap_signatures': signatures,
        'gap_consistent': gap_consistent,
        'initial_duplicate_count': len(initial_duplicates),
        'remaining_duplicate_count': len(remaining),
        'redirects': redirects,
        'failures': failures,
        'passed': passed,
        'summary': (
            f'Research Gap 表{"一致" if gap_consistent else "不一致"}；'
            f'原始重复 {len(initial_duplicates)} 段，处理后剩余 {len(remaining)} 段；'
            f'衔接门禁{"通过" if passed else "未通过"}。'
        ),
    }


def _linkage_report(linkage, independent, root_checks=None):
    lines = [
        '# C1+C2 衔接检查', '',
        '本报告由实际 Research Gap 表解析、归一化长段比对和预置复核结果生成。', '',
        '## Research Gap 表逐项比对', '',
    ]
    for mode in ('C1', 'C2'):
        lines.append(f'### {mode}（{"存在数据行" if linkage["gap_rows"][mode] else "缺失或无数据行"}）')
        lines.append('')
        if not linkage['gap_rows'][mode]:
            lines.append('- 未解析到有效数据行。')
        for row in linkage['gap_rows'][mode]:
            refs = ''.join(f'[{ref}]' for ref in row['refs']) or '无引用'
            lines.append(f'- 研究方向：{row["direction"]}；现有不足：{row["limitation"]}；引用：{refs}')
        lines.append('')
    lines.extend([
        f'- 空白点与引用一致性：**{"通过" if linkage["gap_consistent"] else "未通过"}**。',
        f'- 原始归一化重复长段：**{linkage["initial_duplicate_count"]} 段**。',
        f'- 处理后剩余重复长段：**{linkage["remaining_duplicate_count"]} 段**。', '',
        '## 重复段处理记录', '',
    ])
    if not linkage['redirects']:
        lines.append('- 未发现需重定向的重复长段。')
    for item in linkage['redirects']:
        lines.extend([
            f'- 保留位置：{item["kept"]}；改写位置：{item["rewritten"]}；理由：{item["reason"]}。',
            f'  重复段归一化前缀：{item["fingerprint"]}',
            '  改写结果：非保留处替换为“概括＋交叉指向”，不复制原长段。',
        ])
    lines.extend(['', '## 独立交付复核', ''])
    for mode in ('C1', 'C2'):
        lines.append(f'- {mode} 独立交付：{"通过" if independent[mode].clean else "未通过"}。')
    lines.extend(['', '## 根目录 C1/C2 预置复核', ''])
    if root_checks is None:
        lines.append('- 待运行；此时尚不允许合并交付。')
    else:
        for mode in ('C1', 'C2'):
            detail = (
                '完成 C1 独立形态复核。' if mode == 'C1'
                else '完成 C2 独立形态复核，并在同目录执行 C1+C2 衔接及重复段检查。'
            )
            lines.append(
                f'- {mode}（verify_report_{mode}.txt）：'
                f'{"通过" if root_checks[mode]["clean"] else "未通过"}；{detail}'
            )
    if linkage['failures']:
        lines.extend(['', '## 衔接失败明细', ''] + [f'- {failure}' for failure in linkage['failures']])
    root_clean = root_checks is not None and all(result['clean'] for result in root_checks.values())
    allowed = linkage['passed'] and all(result.clean for result in independent.values()) and root_clean
    lines.extend([
        '', '## 最终门禁', '',
        f'- 结论：**{"通过，允许合并交付" if allowed else "未通过，禁止合并交付"}**。',
    ])
    return '\n'.join(lines) + '\n'


class Orchestrator:
    def __init__(
        self,
        artifact_root=None,
        search_factory=SearchService,
        analysis_factory=AnalysisService,
        graph_builder=None,
        writing_factory=None,
        delivery_factory=None,
        stats_runner=None,
        model=None,
    ):
        self.artifact_root = Path(artifact_root or get_settings().artifact_root)
        self.search_factory = search_factory
        self.analysis_factory = analysis_factory
        self.graph_builder = graph_builder or self._default_graph_builder
        self.writing_factory = writing_factory or self._default_writing_factory
        self.delivery_factory = delivery_factory or self._default_delivery_factory
        self.stats_runner = stats_runner or self._default_stats_runner
        self._model = model

    @property
    def model(self):
        if self._model is None:
            self._model = ChatModel()
        return self._model

    def _default_graph_builder(self, task_dir, pools, analysis, stats, topic='', condition=''):
        from app.graphs import GraphService
        from app.graph_artifacts import build_graph_artifacts

        GraphService().build(
            pools=pools,
            stats=stats,
            analysis=analysis,
            topic=topic,
            condition=condition,
            sources='OpenAlex 真实聚合与论文池',
            output_dir=task_dir,
        )
        return build_graph_artifacts(task_dir, topic or '文献研究', pools.get('limited', pools.get('unlimited', {})).get('count', 0))

    def _default_writing_factory(self, workspace_root, model, version):
        from app.qwen import ChatModel

        if isinstance(model, ChatModel):
            thinking = os.environ.get('QWEN_WRITING_THINKING', 'false').strip().lower() in {
                '1', 'true', 'yes', 'on',
            }
            model = ChatModel(
                client=model._client,
                model=model.model,
                thinking=thinking,
                request_timeout=600 if thinking else 300,
            )
        return WritingService(
            workspace_root=workspace_root,
            model=model,
            template_overrides=version.content.get('templates'),
        )

    def _default_delivery_factory(self, workspace_root):
        return DeliveryService(workspace_root=workspace_root)

    def _default_stats_runner(self, task_dir, terms, from_year):
        script = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts' / 'search_papers.py'

        def retrieve(stat, output, year=None, topic_id=None):
            command = [sys.executable, str(script), 'openalex']
            for term in terms:
                command.extend(['--query', term])
            command.extend(['--stats', stat, '--out', str(output)])
            if year is not None:
                command.extend(['--from-year', str(year)])
            if topic_id:
                command.extend(['--topic-series', topic_id])
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if completed.returncode != 0:
                raise RuntimeError(f'OpenAlex {stat} aggregation failed')
            return json.loads(output.read_text(encoding='utf-8'))

        result = {
            'year': retrieve('year', task_dir / 'stats_year.json'),
            'topics': {
                'all': retrieve('topics', task_dir / 'stats_topics_all.json'),
            },
            'series': [],
        }
        if from_year is not None:
            result['topics']['limited'] = retrieve(
                'topics',
                task_dir / 'stats_topics_limited.json',
                year=from_year,
            )
        for index, group in enumerate(result['topics']['all'].get('groups', [])[:4], 1):
            result['series'].append(retrieve(
                'year',
                task_dir / f'stats_series_{index}.json',
                topic_id=group.get('key'),
            ))
        return result

    def _answers(self, stage_input):
        return {item['card_id']: item['value'] for item in stage_input.get('answers', [])}

    def _mode(self, answers):
        selected = str(answers.get('mode', {}).get('mode', 'A')).upper()
        if selected == 'C':
            return str(answers.get('mode', {}).get('c_route', 'C1')).upper()
        return selected

    def _search_mode(self, mode):
        return 'C1' if mode == 'C1+C2' else mode

    def _from_year(self, answers):
        value = answers.get('years', {})
        choice = value.get('choice', value.get('years', 'D'))
        if choice == 'D':
            return None
        if value.get('from_year') is not None:
            return int(value['from_year'])
        offsets = {'A': 3, 'B': 5, 'C': 10}
        return datetime.now(timezone.utc).year - offsets.get(str(choice), 5)

    def _version(self, task):
        if get_settings().task_store_authority == 'sites':
            from app.task_store_sync import configured_task_store_sync

            version = configured_task_store_sync().get_skill_version(
                session_id=task.session_id,
                skill_version_id=task.skill_version_id,
            )
            if version is None:
                raise RuntimeError('task Skill version is missing')
            return version
        with SessionLocal() as db:
            version = db.get(SkillVersion, task.skill_version_id)
        if version is None:
            raise RuntimeError('task Skill version is missing')
        return version

    def _sync_artifacts(self, task_dir):
        secret = os.environ.get('WORKER_SHARED_SECRET') or ''
        web_origin = (os.environ.get('WEB_API_ORIGIN') or '').rstrip('/')
        if web_origin and secret:
            return self._upload_to_web(task_dir, web_origin, secret)
        origin = os.environ.get('QODER_SITES_ORIGIN')
        if not origin or not secret:
            return 0
        client = SitesStorageClient(origin=origin, shared_secret=secret)
        count = 0
        for path in task_dir.iterdir():
            if not path.is_file() or path.stat().st_size > 50_000_000:
                continue
            client.put_bytes(
                task_dir.name,
                path.name,
                path.read_bytes(),
                self._content_type(path),
            )
            count += 1
        return count

    def _upload_to_web(self, task_dir, origin, secret):
        import urllib.request
        from urllib.parse import quote

        count = 0
        for path in task_dir.iterdir():
            if not path.is_file() or path.stat().st_size > 50_000_000:
                continue
            url = '{}/api/internal/artifacts/{}/{}'.format(
                origin,
                quote(task_dir.name, safe=''),
                quote(path.name, safe=''),
            )
            request = urllib.request.Request(
                url,
                data=path.read_bytes(),
                method='PUT',
                headers={
                    'X-Worker-Token': secret,
                    'Content-Type': self._content_type(path),
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status not in (200, 201):
                    raise RuntimeError('artifact upload failed with status {}'.format(response.status))
            count += 1
        return count

    def _content_type(self, path):
        return {
            '.html': 'text/html; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.md': 'text/markdown; charset=utf-8',
            '.txt': 'text/plain; charset=utf-8',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.png': 'image/png',
            '.svg': 'image/svg+xml',
        }.get(path.suffix.lower(), 'application/octet-stream')

    def search_stage(self, task, stage_input):
        answers = self._answers(stage_input)
        mode = self._mode(answers)
        terms = answers.get('terms', {}).get('terms') or []
        from_year = self._from_year(answers)
        task_dir = self.artifact_root / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        pools = self.search_factory(task_dir).run(SearchRequest(
            terms=terms,
            from_year=from_year,
            mode=self._search_mode(mode),
        ))
        papers = pools['limited']['papers']
        analyzer = self.analysis_factory(self.model)

        def analyze(paper_pool):
            classified = analyzer.classify(paper_pool)
            return {
                'classify': classified,
                'factor_votes': [asdict(vote) for vote in analyzer.extract_factor_votes(paper_pool)],
                'relations': [asdict(relation) for relation in analyzer.extract_relations(paper_pool)],
            }

        analysis = {'all': analyze(pools['unlimited']['papers'])}
        if from_year is not None:
            analysis['limited'] = analyze(papers)
        (task_dir / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
        stats = self.stats_runner(task_dir, terms, from_year)
        (task_dir / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
        graph_pools = dict(pools)
        if from_year is None:
            graph_pools.pop('limited', None)
        graph_result = self.graph_builder(
            task_dir,
            graph_pools,
            analysis,
            stats,
            topic=answers.get('direction', {}).get('direction', ''),
            condition=f'模式 {mode}',
        )
        synced = self._sync_artifacts(task_dir)
        return {
            'state': TaskState.DASHBOARD_READY.value,
            'next_card': CardId.ADJUSTMENT.value,
            'message': '双范围检索、分析与七类图谱已生成',
            'checkpoint': {
                'stage': 'search',
                'limited_count': pools['limited']['count'],
                'unlimited_count': pools['unlimited']['count'],
                'graph_artifacts': graph_result.get('artifact_count', 0) if isinstance(graph_result, dict) else 0,
                'storage_synced': synced,
            },
        }

    def _writing_task(self, task, answers, mode, papers, analysis, task_id=None):
        project = dict(answers.get('mode', {}).get('project', {}))
        if isinstance(project.get('research_contents'), str):
            project['research_contents'] = [
                item.strip() for item in re.split(r'[\n；;]+', project['research_contents']) if item.strip()
            ]
        project.setdefault('funding', '未指定')
        return WritingTask(
            id=task_id or task.id,
            mode=mode,
            direction=answers.get('direction', {}).get('direction', ''),
            papers=papers,
            component_data=None,
            analysis=analysis,
            search_overview={
                'databases': ['OpenAlex'],
                'queries': answers.get('terms', {}).get('terms', []),
                'from_year': self._from_year(answers),
                'pool_count': len(papers),
            },
            project=project,
            user_results=answers.get('mode', {}).get('user_results', ''),
            target_journal=answers.get('mode', {}).get('target_journal', ''),
            team_context=answers.get('mode', {}).get('team_context', ''),
        )

    def _generate_c_pair(self, task, answers, papers, analysis, version):
        task_dir = self.artifact_root / task.id
        written = {}
        writing_tasks = {}
        deliveries = {}
        for mode in ('C1', 'C2'):
            writing_task = self._writing_task(task, answers, mode, papers, analysis, task_id=f'{task.id}-{mode}')
            writing_tasks[mode] = writing_task
            writing = self.writing_factory(self.artifact_root, self.model, version)
            output = writing.produce(writing_task)
            written[mode] = output
            subtask_dir = self.artifact_root / writing_task.id
            delivery_task = DeliveryTask(
                id=writing_task.id,
                mode=mode,
                direction=writing_task.direction,
                papers=papers,
                body=output.body_path.read_text(encoding='utf-8'),
                evidence_ledger=(subtask_dir / 'evidence_ledger.md').read_text(encoding='utf-8'),
                components=getattr(output.components, 'data', {}),
                outline=output.outline,
                sample=output.sample,
                delivery_form='B',
                search_log=(task_dir / 'search_log.md').read_text(encoding='utf-8') if (task_dir / 'search_log.md').exists() else '',
                requirements=[{'requirement': f'{mode} 独立复核', 'location': 'verify_report.txt', 'passed': True}],
            )
            deliveries[mode] = self.delivery_factory(self.artifact_root).deliver(delivery_task)

        citation_maps = {}
        for mode in ('C1', 'C2'):
            map_path = self.artifact_root / f'{task.id}-{mode}' / 'citation_map.json'
            citation_maps[mode] = json.loads(map_path.read_text(encoding='utf-8')) if map_path.exists() else None
        delivered_bodies = {
            mode: written[mode].body_path.read_text(encoding='utf-8')
            for mode in ('C1', 'C2')
        }
        linkage = _resolve_c_pair_linkage(
            delivered_bodies['C1'], delivered_bodies['C2'],
            citation_maps['C1'], citation_maps['C2'],
        )
        linkage_path = task_dir / 'linkage_check.md'
        linkage_path.write_text(_linkage_report(linkage, deliveries), encoding='utf-8')
        if not (task_dir / 'papers.json').exists():
            (task_dir / 'papers.json').write_text(json.dumps({
                'topic': answers.get('direction', {}).get('direction', ''),
                'count': len(papers),
                'papers': papers,
            }, ensure_ascii=False, indent=2), encoding='utf-8')

        combined_components = {}
        for mode, filename in (('C1', 'C1_引言.md'), ('C2', 'C2_文献综述.md')):
            output = written[mode]
            (task_dir / filename).write_text(linkage['bodies'][mode], encoding='utf-8')
            (task_dir / f'outline_{mode}.md').write_text(output.outline, encoding='utf-8')
            (task_dir / f'sample_{mode}.md').write_text(output.sample, encoding='utf-8')
            combined_components[mode] = getattr(output.components, 'data', {})
        combined_components['linkage'] = linkage['summary']

        root_checks = {}
        for mode, filename in (('C1', 'C1_引言.md'), ('C2', 'C2_文献综述.md')):
            (task_dir / 'evidence_ledger.md').write_text(
                (self.artifact_root / f'{task.id}-{mode}' / 'evidence_ledger.md').read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            subtask_map = self.artifact_root / f'{task.id}-{mode}' / 'citation_map.json'
            if subtask_map.exists():
                shutil.copyfile(subtask_map, task_dir / 'citation_map.json')
            result = self.delivery_factory(self.artifact_root).verification_runner(
                writing_tasks[mode], task_dir / filename, f'verify_report_{mode}.txt',
            )
            if not result.get('clean') and not result.get('failures'):
                result['failures'] = [f'{mode} 根目录复核未通过，未返回失败明细']
            root_checks[mode] = result
        linkage_path.write_text(_linkage_report(linkage, deliveries, root_checks), encoding='utf-8')

        independent_clean = all(result.clean for result in deliveries.values())
        roots_clean = all(result['clean'] for result in root_checks.values())
        can_combine = independent_clean and linkage['passed'] and roots_clean
        failures = [failure for result in deliveries.values() for failure in result.failures]
        failures.extend(failure for result in root_checks.values() for failure in result['failures'])
        failures.extend(linkage['failures'])
        warnings = [warning for result in deliveries.values() for warning in result.warnings]
        warnings.extend(warning for result in root_checks.values() for warning in result.get('warnings', []))
        linkage_checkpoint = {
            'passed': linkage['passed'],
            'gap_consistent': linkage['gap_consistent'],
            'initial_duplicates': linkage['initial_duplicate_count'],
            'remaining_duplicates': linkage['remaining_duplicate_count'],
        }
        if not can_combine:
            failures.append('C1+C2 独立交付、衔接检查或根目录复核未通过，已阻止合并交付')
            synced = self._sync_artifacts(task_dir)
            return {
                'state': TaskState.DONE.value,
                'next_card': None,
                'message': 'C1/C2 已分别生成并复核，但衔接门禁未通过，未执行合并交付',
                'checkpoint': {
                    'stage': 'generate',
                    'clean': False,
                    'failures': failures,
                    'warnings': warnings,
                    'storage_synced': synced,
                    'combined_delivered': False,
                    'linkage': linkage_checkpoint,
                },
            }

        combined_body_parts = [
            _restore_original_citations(linkage['bodies'][mode], citation_maps[mode])
            .split('## 参考文献')[0].rstrip()
            for mode in ('C1', 'C2')
        ]
        combined_body = combined_body_parts[0] + '\n\n## 独立文献综述\n\n' + combined_body_parts[1] + '\n'
        combined_outline = written['C1'].outline + '\n\n---\n\n' + written['C2'].outline
        combined_sample = written['C1'].sample + '\n\n---\n\n' + written['C2'].sample
        (task_dir / 'outline.md').write_text(combined_outline, encoding='utf-8')
        (task_dir / 'sample.md').write_text(combined_sample, encoding='utf-8')
        combined_ledger = (self.artifact_root / f'{task.id}-C1' / 'evidence_ledger.md').read_text(encoding='utf-8')
        combined_ledger += '\n' + (self.artifact_root / f'{task.id}-C2' / 'evidence_ledger.md').read_text(encoding='utf-8')
        (task_dir / 'evidence_ledger.md').write_text(combined_ledger, encoding='utf-8')
        delivery_answer = answers.get('delivery', {})
        form = str(delivery_answer.get('form', delivery_answer.get('delivery', 'A'))).upper()
        combined = DeliveryTask(
            id=task.id,
            mode='E',
            direction=answers.get('direction', {}).get('direction', ''),
            papers=papers,
            body=combined_body,
            evidence_ledger=combined_ledger,
            components=combined_components,
            outline=combined_outline,
            sample=combined_sample,
            delivery_form=form,
            search_log=(task_dir / 'search_log.md').read_text(encoding='utf-8') if (task_dir / 'search_log.md').exists() else '',
            requirements=[
                {
                    'requirement': 'C1 与 C2 分离并分别复核',
                    'location': 'verify_report_C1.txt / verify_report_C2.txt',
                    'passed': independent_clean and roots_clean,
                },
                {
                    'requirement': '完成衔接与重复检查',
                    'location': 'linkage_check.md',
                    'passed': linkage['passed'],
                },
            ],
        )
        combined_delivery = self.delivery_factory(self.artifact_root).deliver(combined)
        deliveries['combined'] = combined_delivery
        clean = can_combine and all(result.clean for result in deliveries.values())
        failures.extend(combined_delivery.failures)
        warnings.extend(combined_delivery.warnings)
        synced = self._sync_artifacts(task_dir)
        return {
            'state': TaskState.DONE.value,
            'next_card': None,
            'message': 'C1 与 C2 已分别生成并复核，真实衔接门禁通过，合并交付已完成' if clean else 'C1/C2 已生成，但仍有需要修订或人工核对的项目',
            'checkpoint': {
                'stage': 'generate',
                'clean': clean,
                'failures': failures,
                'warnings': warnings,
                'storage_synced': synced,
                'combined_delivered': True,
                'linkage': linkage_checkpoint,
            },
        }

    def generate_stage(self, task, stage_input):
        answers = self._answers(stage_input)
        mode = self._mode(answers)
        task_dir = self.artifact_root / task.id
        papers = json.loads((task_dir / 'papers.json').read_text(encoding='utf-8'))['papers']
        analysis_document = json.loads((task_dir / 'analysis.json').read_text(encoding='utf-8')) if (task_dir / 'analysis.json').exists() else {}
        analysis = analysis_document.get('limited', analysis_document.get('all', analysis_document))
        version = self._version(task)
        if mode == 'C1+C2':
            return self._generate_c_pair(task, answers, papers, analysis, version)
        delivery_answer = answers.get('delivery', {})
        form = str(delivery_answer.get('form', delivery_answer.get('delivery', 'A'))).upper()
        writing_mode = 'A_DIALOGUE' if mode == 'A' and form == 'B' else mode
        writing_task = self._writing_task(task, answers, writing_mode, papers, analysis)
        writing = self.writing_factory(self.artifact_root, self.model, version)
        written = writing.produce(writing_task)
        body = written.body_path.read_text(encoding='utf-8')
        components = getattr(getattr(written, 'components', None), 'data', {})
        if (task_dir / 'stats.json').exists() and 'stats' not in components:
            components['stats'] = json.loads((task_dir / 'stats.json').read_text(encoding='utf-8'))
        delivery_task = DeliveryTask(
            id=task.id,
            mode=writing_task.mode,
            direction=writing_task.direction,
            papers=papers,
            body=body,
            evidence_ledger=(task_dir / 'evidence_ledger.md').read_text(encoding='utf-8'),
            components=components,
            outline=getattr(written, 'outline', ''),
            sample=getattr(written, 'sample', ''),
            delivery_form=form,
            search_log=(task_dir / 'search_log.md').read_text(encoding='utf-8') if (task_dir / 'search_log.md').exists() else '',
            requirements=[
                {'requirement': '实际检索术语与用户选择一致', 'location': 'search_log.md', 'passed': True},
                {'requirement': f'用途模式为 {mode}', 'location': written.body_path.name, 'passed': True},
                {'requirement': f'交付形式为 {form}', 'location': '交付文件', 'passed': True},
            ],
        )
        delivered = self.delivery_factory(self.artifact_root).deliver(delivery_task)
        synced = self._sync_artifacts(task_dir)
        return {
            'state': TaskState.DONE.value,
            'next_card': None,
            'message': '交付文件已生成；请查看复核与覆盖边界' if delivered.clean else '交付文件已生成，但仍有需要修订或人工核对的项目',
            'checkpoint': {
                'stage': 'generate',
                'clean': delivered.clean,
                'failures': delivered.failures,
                'warnings': delivered.warnings,
                'storage_synced': synced,
            },
        }


def register_stage_services():
    from app.queueing import STAGE_SERVICES

    orchestrator = Orchestrator()
    STAGE_SERVICES['search'] = orchestrator.search_stage
    STAGE_SERVICES['generate'] = orchestrator.generate_stage
