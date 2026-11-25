import json
import re
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def d_delivery(tmp_path):
    from test_mode_delivery_regression import deliver_mode, produce_mode
    from dev.real_backend.offline_providers import offline_stats

    task, output = produce_mode('D', tmp_path)
    output.components.data['stats'] = offline_stats(tmp_path, ['hepatocellular carcinoma'], None)
    return deliver_mode('D', task, output, tmp_path, form='C')


def slide_xml(result, page):
    deck = next(path for path in result.artifacts.values() if path.name.endswith('组会汇报.pptx'))
    with zipfile.ZipFile(deck) as archive:
        return archive.read(f'ppt/slides/slide{page}.xml').decode('utf-8')


def test_theme_declares_real_cjk_font(d_delivery):
    deck = next(path for path in d_delivery.artifacts.values() if path.name.endswith('组会汇报.pptx'))
    with zipfile.ZipFile(deck) as archive:
        theme = archive.read('ppt/theme/theme1.xml').decode('utf-8')
    assert re.search(r'<a:ea typeface="Noto Sans CJK SC"', theme)


def test_charts_have_legend_and_readable_data_labels(d_delivery):
    deck = next(path for path in d_delivery.artifacts.values() if path.name.endswith('组会汇报.pptx'))
    with zipfile.ZipFile(deck) as archive:
        charts = [name for name in archive.namelist() if re.fullmatch(r'ppt/charts/chart\d+\.xml', name)]
        assert len(charts) >= 2
        for name in charts:
            xml = archive.read(name).decode('utf-8')
            assert '<c:legend>' in xml, name
            assert '<c:dLbls>' in xml, name
            assert '<c:showCatName val="1"/>' in xml, name
            assert '<c:showVal val="1"/>' in xml, name


def test_flow_pages_have_real_nodes_and_connectors(d_delivery):
    for page, expected in ((3, '研究对象'), (12, '核心方法'), (22, '不足')):
        xml = slide_xml(d_delivery, page)
        assert xml.count('<p:sp>') >= 4, page
        assert xml.count('<p:cxnSp>') >= 3, page
        assert expected in xml


def test_year_and_topic_pages_exist(d_delivery):
    assert '年度趋势（真实聚合）' in slide_xml(d_delivery, 6)
    assert '主题分布（真实聚合）' in slide_xml(d_delivery, 7)


LEGEND_ENTRY_BUDGET_EM = 8.0
_LATIN_EM = 0.56
_SPACE_EM = 0.4


def _label_em_width(label):
    """Estimate single-line legend text width in CJK em units at the legend font size."""
    width = 0.0
    for char in label:
        if (
            '\u4e00' <= char <= '\u9fff'
            or '\u3000' <= char <= '\u303f'
            or '\uff00' <= char <= '\uffef'
        ):
            width += 1.0
        elif char == ' ':
            width += _SPACE_EM
        else:
            width += _LATIN_EM
    return width


def _pie_chart_labels(archive, name):
    xml = archive.read(name).decode('utf-8')
    if '<c:pieChart>' not in xml:
        return []
    labels = []
    for category_cache in re.findall(r'<c:cat>.*?</c:cat>', xml, flags=re.S):
        labels.extend(re.findall(r'<c:v>([^<]*)</c:v>', category_cache))
    return labels


def test_pie_legend_entries_fit_entry_budget_or_are_wrapped(d_delivery):
    """Structural regression for FOLLOWUP-P07-LEGEND (page 7 legend collision).

    Both WPS and LibreOffice pack bottom-legend entries with tight fixed gaps;
    the acceptance evidence shows an entry wider than ~8em collides with the
    neighbouring swatch and is clipped. Such entries must be explicitly wrapped
    onto two lines; shorter entries must stay untouched.
    """
    deck = next(path for path in d_delivery.artifacts.values() if path.name.endswith('组会汇报.pptx'))
    with zipfile.ZipFile(deck) as archive:
        charts = [name for name in archive.namelist() if re.fullmatch(r'ppt/charts/chart\d+\.xml', name)]
        failures = []
        labels = []
        for name in charts:
            for label in _pie_chart_labels(archive, name):
                labels.append(label)
                single_line = label.replace('\n', '').replace('\v', '')
                if (
                    _label_em_width(single_line) > LEGEND_ENTRY_BUDGET_EM
                    and '\n' not in label
                    and '\v' not in label
                ):
                    failures.append(
                        f'{name}: legend entry {label!r} exceeds '
                        f'{LEGEND_ENTRY_BUDGET_EM}em without a line wrap'
                    )
        assert not failures
        # all four real topic categories survive the wrapping (names and values intact)
        normalized = {re.sub(r'[\s\v]+', '', label) for label in labels}
        assert normalized == {
            '髓系代谢与S1P',
            'IL-8/CXCR2动态分层',
            '乳酸化与PD-L1',
            '免疫微环境综述',
        }
