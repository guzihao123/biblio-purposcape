from pathlib import Path

from app.report_docs import read_report_documents


def test_missing_single_mode_files_return_explicit_notices(tmp_path):
    result = read_report_documents(tmp_path, 'A')

    assert '提示' in result['outline']
    assert '提示' in result['sample']
    assert '提示' in result['body']
    assert '综述初稿.md' in result['missing']
    assert 'outline.md' in result['missing']
    assert 'sample.md' in result['missing']


def test_missing_outline_and_sample_fall_back_to_body(tmp_path):
    (tmp_path / '综述初稿.md').write_text('# 标题\n\n正文内容 [1]。', encoding='utf-8')

    result = read_report_documents(tmp_path, 'B')

    assert '正文内容' in result['body']
    assert '正文摘录' in result['outline']
    assert '正文摘录' in result['sample']
    assert result['missing'] == ['outline.md', 'sample.md']


def test_components_are_used_when_body_is_missing(tmp_path):
    (tmp_path / 'components.md').write_text('## 构件\n\n保留的构件文字。', encoding='utf-8')

    result = read_report_documents(tmp_path, 'D')

    assert '保留的构件文字' in result['body']
    assert '保留的构件文字' in result['outline']
    assert '调研初稿.md' in result['missing']


def test_c_pair_documents_are_combined_when_combined_files_are_missing(tmp_path):
    (tmp_path / 'C1_引言.md').write_text('# 引言\n\n引言正文。', encoding='utf-8')
    (tmp_path / 'C2_文献综述.md').write_text('# 综述\n\n综述正文。', encoding='utf-8')
    (tmp_path / 'outline_C1.md').write_text('提纲一', encoding='utf-8')
    (tmp_path / 'outline_C2.md').write_text('提纲二', encoding='utf-8')
    (tmp_path / 'sample_C1.md').write_text('样章一', encoding='utf-8')
    (tmp_path / 'sample_C2.md').write_text('样章二', encoding='utf-8')

    result = read_report_documents(tmp_path, 'C')

    assert '引言正文' in result['body']
    assert '## 独立文献综述' in result['body']
    assert '综述正文' in result['body']
    assert '提纲一' in result['outline'] and '提纲二' in result['outline']
    assert '样章一' in result['sample'] and '样章二' in result['sample']