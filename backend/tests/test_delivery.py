import json
from pathlib import Path
import subprocess

import pytest

from app.delivery import DeliveryResult, DeliveryService, DeliveryTask


PAPERS = [
    {
        'ref_no': 1,
        'title': 'Drainage resilience study',
        'authors': ['Li, Wei', 'Smith, Jane'],
        'year': 2024,
        'venue': 'Urban Water Journal',
        'type': 'article',
        'doi': '10.1000/example.1',
        'abstract': 'The calibrated model reduced urban flood loss estimation error.',
        'evidence_level': 'B',
        'claim_eligible': True,
    },
    {
        'ref_no': 2,
        'title': 'Underground garage survey',
        'authors': ['Wang, Fang'],
        'year': 2023,
        'venue': 'Cities',
        'type': 'article',
        'doi': '10.1000/example.2',
        'abstract': 'The survey describes garage exposure and recovery across three districts.',
        'evidence_level': 'A',
        'claim_eligible': True,
    },
]

LEDGER = '''| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 |
|---|---|---|---|
| 校准模型降低损失估计误差 | [1] | The calibrated model reduced urban flood loss estimation error. | B |
| 调查描述暴露与恢复 | [2] | The survey describes garage exposure and recovery across three districts. | A |
'''


def d_components():
    return {
        'search_overview': {'databases': ['OpenAlex'], 'queries': ['urban flooding'], 'pool_count': 2},
        'progress': [
            {'direction': '损失评估', 'summary': '校准模型降低误差 [1]（据摘要）'},
            {'direction': '暴露调查', 'summary': '调查描述恢复差异 [2]'},
            {'direction': '联合校准', 'summary': '两类研究提供互补线索（分析）'},
        ],
        'method_comparison': [
            {'family': '计算建模与仿真', 'technique': '校准模型', 'data': '未说明', 'strength': '误差评估', 'limitation': '暴露约束未确认', 'refs': [1]},
            {'family': '问卷调查与观察性数据', 'technique': '地区调查', 'data': '三个地区', 'strength': '恢复情景', 'limitation': '模型联动未确认', 'refs': [2]},
            {'family': '文献与二手数据', 'technique': '比较综合', 'data': '池内摘要', 'strength': '横向比较', 'limitation': '仅摘要', 'refs': [1, 2]},
        ],
        'reading_cards': [
            {'ref': 1, 'title': 'Drainage resilience study', 'reason': '方法代表', 'research_question': '损失误差', 'data': '未说明', 'method': '校准模型', 'findings': '误差降低 [1]（据摘要）', 'limitations': '细节未确认', 'team_relevance': '校准流程', 'reading_depth': '仅摘要'},
            {'ref': 2, 'title': 'Underground garage survey', 'reason': '数据代表', 'research_question': '暴露恢复', 'data': '三个地区', 'method': '调查', 'findings': '恢复差异 [2]', 'limitations': '联动未确认', 'team_relevance': '调查设计', 'reading_depth': '仅摘要'},
            {'ref': 1, 'title': '联合校准复核', 'reason': '交叉复核', 'research_question': '联合校准', 'data': '池内摘要', 'method': '比较分析', 'findings': '互补线索（分析）', 'limitations': '仅摘要', 'team_relevance': '形成讨论', 'reading_depth': '仅摘要'},
        ],
        'limitations': ['数据口径', '方法联动', '外部验证', '全文深度', '团队基础'],
        'trends': ['联合校准与跨区比较值得进一步验证（分析）'],
        'discussion_questions': ['需要哪些新增数据？', '团队能否复用调查？'],
    }


def make_task(form='ALL', mode='A', body=None):
    return DeliveryTask(
        id=f'{mode}-{form}-task',
        mode=mode,
        direction='城市内涝与地下车库韧性',
        papers=PAPERS,
        body=body or '该领域分为损失评估与暴露调查两块。\n\n校准模型降低了损失估计误差 [1]（据摘要）。调查描述了暴露与恢复 [2]。\n\n【待核实】公开数据集的可用性仍需确认。',
        evidence_ledger=LEDGER,
        components=d_components() if mode == 'D' else {'landscape': ['损失评估', '暴露调查']},
        outline='1. 背景\n2. 进展\n3. 不足\n4. 方向',
        delivery_form=form,
        requirements=[{'requirement': '使用用户选择的交付形式', 'location': '交付文件', 'passed': True}],
    )


def passing_reference_checker(papers_path, output_path):
    Path(output_path).write_text('# 著录核验\n\n离线测试：两条题录均已核对。\n', encoding='utf-8')
    return {'clean': True, 'issues': []}


def passing_verifier(task, body_path, report_name):
    report = '模拟复核：证据项通过。\n'
    (body_path.parent / report_name).write_text(report, encoding='utf-8')
    return {'clean': True, 'failures': [], 'warnings': [], 'report': report}


def service(tmp_path, verifier=None):
    return DeliveryService(
        workspace_root=tmp_path,
        verification_runner=verifier or passing_verifier,
        reference_checker=passing_reference_checker,
    )


def test_pending_number_confirmation_is_parsed_from_the_verifier_report():
    from app.delivery import _pending_confirmations, _reference_issues

    report = (
        '交付前脚本复核报告\n'
        '[PASS] ①证据等级\n'
        '④ 待人工确认（未绑定台账原句，须交付说明披露并人工判定）:\n'
        '  20（句引[9]）未绑定台账原句——待人工确认是否结构性数字\n'
        '============================================================\n'
        '总结论: 全部 9 项无失败\n'
    )
    notes = _pending_confirmations(report)
    assert notes == ['20（句引[9]）未绑定台账原句——待人工确认是否结构性数字']

    reference_report = (
        '## [13] Sample title\n'
        '- DOI：10.1000/x｜核验通道：crossref\n'
        '- 作者名不一致：Crossref「Pachan, Molly」vs 本地「Molly K. Pachan」\n'
        '- 结论：**需人工核对**（见上）\n'
    )
    issues = _reference_issues(reference_report)
    assert issues[0].startswith('[ref 13] 作者名不一致')


def test_conformance_discloses_pending_number_confirmations(tmp_path):
    def verifier(task, body_path, report_name):
        (body_path.parent / report_name).write_text('复核通过\n', encoding='utf-8')
        return {
            'clean': True,
            'failures': [],
            'warnings': ['20（句引[9]）未绑定台账原句——待人工确认是否结构性数字'],
            'report': '复核通过\n',
        }

    result = DeliveryService(
        workspace_root=tmp_path,
        verification_runner=verifier,
        reference_checker=passing_reference_checker,
    ).deliver(make_task())
    conformance = result['conformance.md'].read_text(encoding='utf-8')

    assert '另有 1 项待人工确认' in conformance
    assert '20（句引[9]）' in conformance


def test_docx_skips_duplicate_title_from_the_body(tmp_path):
    body = '# 城市内涝与地下车库韧性｜模式 A 调研报告\n\n该领域分为损失评估与暴露调查两块 [1]。'
    result = service(tmp_path).deliver(make_task(body=body))
    from docx import Document

    texts = [paragraph.text for paragraph in Document(result['综述初稿.docx']).paragraphs]
    assert texts[0] == '城市内涝与地下车库韧性'
    assert not any(text.startswith('城市内涝与地下车库韧性｜模式') for text in texts)


def test_docx_and_pptx_are_real_openable_files(tmp_path):
    task = make_task()
    result = service(tmp_path).deliver(task)

    assert result['综述初稿.docx'].read_bytes().startswith(b'PK')
    assert result['城市内涝与地下车库韧性组会汇报.pptx'].read_bytes().startswith(b'PK')
    assert result['verify_report.txt'].exists()
    assert result['references_check.md'].exists()
    assert result['conformance.md'].exists()
    assert result.clean is True

    from docx import Document
    from pptx import Presentation
    document = Document(result['综述初稿.docx'])
    presentation = Presentation(result['城市内涝与地下车库韧性组会汇报.pptx'])
    assert len(document.paragraphs) > 3
    assert 8 <= len(presentation.slides) <= 12


def test_pending_verification_is_highlighted_in_word_and_red_bold_in_ppt(tmp_path):
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from pptx import Presentation
    result = service(tmp_path).deliver(make_task())

    document = Document(result['综述初稿.docx'])
    assert any(
        run.font.highlight_color == WD_COLOR_INDEX.YELLOW and '【待核实】' in run.text
        for paragraph in document.paragraphs
        for run in paragraph.runs
    )
    presentation = Presentation(result['城市内涝与地下车库韧性组会汇报.pptx'])
    pending_runs = [
        run
        for slide in presentation.slides
        for shape in slide.shapes
        if getattr(shape, 'has_text_frame', False)
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
        if '【待核实】' in run.text
    ]
    assert pending_runs
    assert all(run.font.bold for run in pending_runs)
    assert all(run.font.color.rgb is not None for run in pending_runs)


def test_dialogue_delivery_has_bounded_points_and_representative_references(tmp_path):
    result = service(tmp_path).deliver(make_task(form='B'))

    assert '综述初稿.docx' not in result.artifacts
    assert not any(name.endswith('.pptx') for name in result.artifacts)
    payload = result.dialogue
    assert 1 <= len(payload['key_points']) <= 8
    assert 1 <= len(payload['references']) <= 10
    assert all('[1]' in point or '[2]' in point or '【待核实】' in point for point in payload['key_points'])
    assert json.loads(result['dialogue.json'].read_text())['mode'] == 'A'


def test_dialogue_a_includes_seven_topic_slots_and_full_body(tmp_path):
    task = make_task(form='B', mode='A_DIALOGUE')
    task.components = {
        'topic_groups': [{'category': '理论创新型选题', 'slots': [{'title': '机制 A'}, {'title': '机制 B'}]}],
        'overall_first': {'topic': '机制 A', 'reason': '直接回应空白', 'risk': '数据未确认'},
    }

    result = service(tmp_path).deliver(task)

    assert result.dialogue['topic_groups'][0]['category'] == '理论创新型选题'
    assert len(result.dialogue['topic_groups'][0]['slots']) == 2
    assert result.dialogue['overall_first']['topic'] == '机制 A'
    assert '该领域分为损失评估与暴露调查两块' in result.dialogue['body']
    assert len(result.dialogue['key_points']) <= 8
    assert len(result.dialogue['references']) <= 10


def test_b_c_delivery_writes_citation_map_without_rewriting_evidence_ledger(tmp_path):
    task = make_task(form='B', mode='C1', body='第二次研究 [2]。第一次研究 [1]（据摘要）。')

    result = service(tmp_path).deliver(task)

    mapping = json.loads(result['citation_map.json'].read_text())
    assert mapping['display_to_ref'] == {'1': 2, '2': 1}
    assert result['C1_引言.md'].read_text().startswith('第二次研究 [1]。第一次研究 [2]（据摘要）。')
    assert 'The calibrated model reduced urban flood loss estimation error.' in result['evidence_ledger.md'].read_text()
    assert result.clean is True


def test_failed_verification_blocks_clean_delivery(tmp_path):
    invalid = make_task(
        form='B',
        body='校准模型降低了损失估计误差 [1]。',
    )
    result = DeliveryService(
        workspace_root=tmp_path,
        reference_checker=passing_reference_checker,
    ).deliver(invalid)

    assert isinstance(result, DeliveryResult)
    assert result.clean is False
    assert result.failures
    assert result['verify_report.txt'].exists()
    conformance = result['conformance.md'].read_text()
    assert '未通过' in conformance


def test_d_ppt_has_twenty_to_thirty_slides_and_separate_text_verification(tmp_path):
    result = service(tmp_path).deliver(make_task(mode='D', form='C'))

    from pptx import Presentation
    deck_path = next(path for path in result.artifacts.values() if path.name.endswith('组会汇报.pptx'))
    presentation = Presentation(deck_path)
    assert 20 <= len(presentation.slides) <= 30
    assert result['汇报文本.md'].exists()
    assert result['verify_report_ppt.txt'].exists()
    assert result['ppt_asset_manifest.json'].exists()
    assert result['verify_ppt_report.txt'].exists()
    assert result['layout_manifest.json'].exists()
    assert result['layout_check.json'].exists()
    assert '结果：PASS' in result['verify_ppt_report.txt'].read_text()
    assert json.loads(result['layout_check.json'].read_text())['ok'] is True
    assert any(shape.has_chart for slide in presentation.slides for shape in slide.shapes if hasattr(shape, 'has_chart'))
    slide_text = '\n'.join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if hasattr(shape, 'text')
    )
    assert '研究背景' in slide_text
    assert '文献检索' in slide_text
    assert '优先方向' in slide_text
    assert '下一步' in slide_text
    assert '选题推荐' not in slide_text
    assert '参考文献' in slide_text


def test_reference_checker_failure_is_disclosed_and_not_clean(tmp_path):
    def failed_checker(papers_path, output_path):
        Path(output_path).write_text('# 著录核验\n\n网络失败，未核验。\n', encoding='utf-8')
        return {'clean': False, 'issues': ['Crossref 网络失败']}

    custom = DeliveryService(
        workspace_root=tmp_path,
        verification_runner=passing_verifier,
        reference_checker=failed_checker,
    )
    result = custom.deliver(make_task(form='B'))

    assert result.clean is False
    assert 'Crossref 网络失败' in result['conformance.md'].read_text()


def test_hcc_fixture_generates_openable_office_files_and_passes_preset_verifier(tmp_path):
    fixture = Path(__file__).resolve().parents[2] / 'fixtures' / 'hcc-20261122'
    papers = json.loads((fixture / 'papers.json').read_text())['papers']
    task = DeliveryTask(
        id='hcc-delivery',
        mode='A',
        direction='肝细胞癌免疫治疗耐药',
        papers=papers,
        body=(fixture / '综述初稿.md').read_text(),
        evidence_ledger=(fixture / 'evidence_ledger.md').read_text(),
        components={'landscape': ['免疫微环境', '预测标志物', '联合治疗']},
        outline='1. 领域格局\n2. 研究空白\n3. 方向卡',
        search_log=(fixture / 'search_log.md').read_text(),
        requirements=[{'requirement': 'HCC 样板证据与形态复核', 'location': 'verify_report.txt', 'passed': True}],
    )
    result = DeliveryService(
        workspace_root=tmp_path,
        reference_checker=passing_reference_checker,
    ).deliver(task)

    assert result.clean is True
    from docx import Document
    from pptx import Presentation
    assert len(Document(result['综述初稿.docx']).paragraphs) > 20
    presentation = Presentation(result['肝细胞癌免疫治疗耐药组会汇报.pptx'])
    assert 8 <= len(presentation.slides) <= 12
    slide_text = '\n'.join(
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if hasattr(shape, 'text')
    )
    assert '第1推荐' in slide_text
    assert '储备方向' in slide_text
    report = result['verify_report.txt'].read_text()
    assert '全部 9 项无失败' in report


def test_verifier_clean_false_without_details_still_blocks_clean_delivery(tmp_path):
    def failed_verifier(task, body_path, report_name):
        (body_path.parent / report_name).write_text('复核服务未返回明细。\n', encoding='utf-8')
        return {'clean': False, 'failures': [], 'warnings': [], 'report': 'failed'}

    result = service(tmp_path, verifier=failed_verifier).deliver(make_task(form='B'))

    assert result.clean is False
    assert result.failures


def test_reference_checker_timeout_returns_a_disclosed_failure(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd='verify_references', timeout=180)

    monkeypatch.setattr('app.delivery.subprocess.run', timeout)
    output = tmp_path / 'references_check.md'
    result = DeliveryService(workspace_root=tmp_path)._run_reference_checker(tmp_path / 'papers.json', output)

    assert result['clean'] is False
    assert result['issues']
    assert '失败' in output.read_text()


def test_e_mode_delivery_a_writes_the_survey_word_file(tmp_path):
    from docx import Document

    fixture = Path(__file__).resolve().parents[2] / 'fixtures' / 'hcc-20261122'
    papers = json.loads((fixture / 'papers.json').read_text())['papers']
    task = DeliveryTask(
        id='e-delivery',
        mode='E',
        direction='肝细胞癌免疫治疗耐药',
        papers=papers,
        body=(fixture / '综述初稿.md').read_text(),
        evidence_ledger=(fixture / 'evidence_ledger.md').read_text(),
        components={'markdown': '按用户用途组织的构件'},
        outline='1. 按用户用途定制的提纲',
        search_log=(fixture / 'search_log.md').read_text(),
        delivery_form='A',
        requirements=[{'requirement': 'E 自定义用途交付 Word', 'location': '综述初稿.docx', 'passed': True}],
    )
    result = DeliveryService(
        workspace_root=tmp_path,
        reference_checker=passing_reference_checker,
    ).deliver(task)

    assert result.clean is True
    assert '综述初稿.docx' in result.artifacts
    assert result['综述初稿.docx'].read_bytes().startswith(b'PK')
    assert len(Document(result['综述初稿.docx']).paragraphs) > 20
    assert result['综述初稿.md'].read_text(encoding='utf-8').startswith('# 肝癌免疫治疗耐药机制')
    assert '## 参考文献' in result['综述初稿.md'].read_text(encoding='utf-8')
