import html as html_lib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from app.graph_artifacts import build_graph_artifacts
from app.graphs import GraphService


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'graphs'
SCRIPT_ROOT = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts'
HTML_NAMES = ('文献图谱仪表盘.html', 'desktop.html', 'mobile.html')
CHART_TITLES = ('总体趋势', '主题分布', '比较分析', '引用', '因素', '研究方法', '语义关系')
TRANSLATIONS = {
    'Cancer Immunotherapy and Biomarkers': '癌症免疫治疗与生物标志物',
    'Hepatocellular Carcinoma Treatment and Prognosis': '肝细胞癌治疗与预后',
    'Immune cells in cancer': '癌症中的免疫细胞',
    'Colorectal Cancer Treatments and Studies': '结直肠癌治疗与研究',
}


def load(name):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding='utf-8'))


def graph_inputs(all_only=False, empty=False):
    if empty:
        pools = {'all': {'papers': []}}
        if not all_only:
            pools['limited'] = {'papers': [], 'from_year': 2023}
        return {
            'pools': pools,
            'stats': {
                'year': {'groups': []},
                'topics': {scope: {'groups': []} for scope in pools},
                'series': [],
            },
            'analysis': {
                scope: {'classify': {'clusters': [], 'methods': []}, 'factor_votes': [], 'relations': []}
                for scope in pools
            },
        }
    pools = {'all': load('papers_all.json')}
    if not all_only:
        pools['limited'] = load('papers.json')
    return {
        'pools': pools,
        'stats': {
            'year': load('stats_year.json'),
            'topics': {
                'all': load('stats_topics_all.json'),
                **({} if all_only else {'limited': load('stats_topics_limited.json')}),
            },
            'series': [load(f'stats_series_{index}.json') for index in range(1, 5)],
        },
        'analysis': load('analysis.json'),
    }


def build_artifacts(output_dir, all_only=False, empty=False):
    inputs = graph_inputs(all_only=all_only, empty=empty)
    data = GraphService().build(
        **inputs,
        topic='肝癌免疫治疗耐药机制离线验收',
        condition='本地 fixture；无网络',
        sources='OpenAlex 本地验收样本',
        translations=TRANSLATIONS,
        generated_at='2026-11-24',
        output_dir=output_dir,
    )
    build_graph_artifacts(output_dir, data['topic'], data['scopes']['all']['pool_count'])
    return data


@pytest.fixture(scope='module')
def real_artifacts(tmp_path_factory):
    output = tmp_path_factory.mktemp('offline-real')
    data = build_artifacts(output)
    return output, data


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.subresources = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
            if attrs.get('src'):
                self.subresources.append((tag, attrs['src']))
        for key in ('src', 'href', 'poster'):
            value = attrs.get(key, '')
            if tag in {'img', 'link', 'iframe', 'source', 'video', 'audio'} and value:
                self.subresources.append((tag, value))


def embedded_data(html, variable='DATA'):
    match = re.search(r'const ' + re.escape(variable) + r' = (.*?);\n', html, re.S)
    assert match, 'interactive data payload is missing'
    return json.loads(match.group(1).replace('<\\/', '</'))


def assert_seven_titles(text):
    for title in CHART_TITLES:
        assert title in text, title


def test_echarts_is_embedded_and_pages_have_no_external_subresources(real_artifacts):
    output, _ = real_artifacts
    vendor = (SCRIPT_ROOT / 'vendor' / 'echarts.min.js').read_text(encoding='utf-8')
    for name in HTML_NAMES:
        text = (output / name).read_text(encoding='utf-8')
        parser = ResourceParser()
        parser.feed(text)
        assert vendor.replace('</script', '<\\/script') in text
        assert all(
            not re.match(r'^[a-z][a-z0-9+.-]*:', value, re.I)
            and not value.startswith('//') and not value.startswith('/')
            for _, value in parser.subresources
        ), parser.subresources
        assert all('src' not in script for script in parser.scripts)
        assert not re.search(r'@import|@font-face', text, re.I)
        for host in ('cdn.jsdelivr.net', 'registry.npmmirror.com', 'unpkg.com'):
            assert host not in text


def test_missing_vendor_fails_closed_instead_of_using_cdn(monkeypatch):
    import sys
    sys.path.insert(0, str(SCRIPT_ROOT))
    from build_dashboard import echarts_scripts

    monkeypatch.setattr('os.path.exists', lambda path: False)
    with pytest.raises(RuntimeError, match='ECharts'):
        echarts_scripts()


def test_all_entries_and_long_image_contain_the_same_seven_modules(real_artifacts):
    output, data = real_artifacts
    for name in HTML_NAMES:
        text = (output / name).read_text(encoding='utf-8')
        assert_seven_titles(text)
    dashboard = (output / '文献图谱仪表盘.html').read_text(encoding='utf-8')
    assert 'id="relations"' in dashboard
    assert embedded_data(dashboard) == data
    assert embedded_data((output / 'desktop.html').read_text(encoding='utf-8')) == data
    mobile = (output / 'mobile.html').read_text(encoding='utf-8')
    match = re.search(r'window\.__MDATA__=(.*?);</script>', mobile, re.S)
    assert match
    mobile_data = json.loads(match.group(1).replace('<\\/', '</'))
    assert mobile_data['trend'] == data['trend_all']
    assert mobile_data['compare'] == data['compare']
    assert all(mobile_data['scopes'][key]['topics'] == scope['topics'] for key, scope in data['scopes'].items())
    long_svg = (output / '文献图谱仪表盘.svg').read_text(encoding='utf-8')
    assert_seven_titles(long_svg)
    root = ET.fromstring(long_svg)
    assert root.tag.endswith('svg')
    assert root.attrib['viewBox'].startswith('0 0 1000 ')
    labels = ''.join(root.itertext())
    for scope in data['scopes'].values():
        assert scope['label'] in labels
        for topic in scope['topics'][:12]:
            assert topic['name_zh'] in labels or topic['name'][:21] in labels
        for node in scope['knowledge']['nodes']:
            assert node['name'] in labels
        for family in scope['methods']['children']:
            assert family['name'] in labels
        counts = {kind: sum(edge['type'] == kind for edge in scope['relations']['edges']) for kind in scope['relations']['types']}
        for kind, count in counts.items():
            assert '%s %s' % (scope['relations']['types'][kind]['name'], count) in labels
    inline_svgs = re.findall(r'<svg\b.*?</svg>', dashboard, re.S)
    assert inline_svgs
    for item in inline_svgs:
        ET.fromstring(item)


def test_empty_all_scope_is_explicit_in_every_entry_and_exports_valid_long_image(tmp_path):
    data = build_artifacts(tmp_path, all_only=True, empty=True)
    assert list(data['scopes']) == ['all']
    assert data['scope_switch']['available'] == ['all']
    assert all(not scope['network']['edges'] for scope in data['scopes'].values())
    assert all(not scope['relations']['edges'] for scope in data['scopes'].values())
    for name in HTML_NAMES:
        text = (tmp_path / name).read_text(encoding='utf-8')
        assert_seven_titles(text)
        assert '限定 2023' not in text
    long_svg = (tmp_path / '文献图谱仪表盘.svg').read_text(encoding='utf-8')
    assert_seven_titles(long_svg)
    assert '暂无' in long_svg or '无' in long_svg
    assert (tmp_path / '文献图谱仪表盘.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_year_d_has_only_unlimited_scope_and_other_years_keep_dual_scope(real_artifacts, tmp_path):
    output, dual = real_artifacts
    assert list(dual['scopes']) == ['all', 'limited']
    for name in ('文献图谱仪表盘.html', 'desktop.html'):
        assert list(embedded_data((output / name).read_text(encoding='utf-8'))['scopes']) == ['all', 'limited']
    build_artifacts(tmp_path, all_only=True)
    for name in ('文献图谱仪表盘.html', 'desktop.html'):
        payload = embedded_data((tmp_path / name).read_text(encoding='utf-8'))
        assert list(payload['scopes']) == ['all']
        assert payload['scope_switch']['available'] == ['all']
        assert '限定 2023' not in (tmp_path / name).read_text(encoding='utf-8')


def test_factor_and_semantic_edges_expose_verbatim_abstract_evidence(real_artifacts):
    output, data = real_artifacts
    dashboard = (output / '文献图谱仪表盘.html').read_text(encoding='utf-8')
    mobile = (output / 'mobile.html').read_text(encoding='utf-8')
    for scope in data['scopes'].values():
        for edge in scope['knowledge']['edges']:
            assert edge['evidence']
            for evidence in edge['evidence']:
                assert evidence['quote'] in dashboard
                assert html_lib.escape(evidence['quote']) in mobile
        for edge in scope['relations']['edges']:
            for quote in (edge['quote'], edge['basis_quote']):
                assert quote in dashboard
                assert html_lib.escape(quote) in mobile


def test_svg_png_and_chinese_labels_are_valid(real_artifacts):
    output, data = real_artifacts
    svg_text = (output / '文献图谱仪表盘.svg').read_text(encoding='utf-8')
    root = ET.fromstring(svg_text)
    labels = ''.join(root.itertext())
    assert '总体趋势' in labels
    assert '语义关系' in labels
    assert '癌症免疫治疗与生物标志物' in labels
    assert 'PingFang SC' in svg_text and 'Microsoft YaHei' in svg_text
    width = float(root.attrib['width'])
    height = float(root.attrib['height'])
    png = output / '文献图谱仪表盘.png'
    assert png.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    with Image.open(png) as image:
        image.verify()
    with Image.open(png) as image:
        assert image.format == 'PNG'
        assert image.width == int(width)
        assert image.height == int(height)
        assert image.width > 0 and image.height > 0


def test_long_image_url_preserves_signed_query():
    from build_static_site import relative_artifact_url

    assert relative_artifact_url(
        '/api/tasks/task-1/artifacts/文献图谱仪表盘.png?signature=abc%2F123'
    ) == '文献图谱仪表盘.png?signature=abc%2F123'
