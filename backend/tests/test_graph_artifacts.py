import json
from pathlib import Path

from app.graph_artifacts import build_graph_artifacts
from app.graphs import GraphService


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'graphs'
TRANSLATIONS = {
    'Cancer Immunotherapy and Biomarkers': '癌症免疫治疗与生物标志物',
    'Hepatocellular Carcinoma Treatment and Prognosis': '肝细胞癌治疗与预后',
    'Immune cells in cancer': '癌症中的免疫细胞',
    'Colorectal Cancer Treatments and Studies': '结直肠癌治疗与研究',
}


def load(name):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding='utf-8'))


def test_real_graph_data_renders_desktop_mobile_index_svg_and_png(tmp_path):
    GraphService().build(
        pools={'all': load('papers_all.json'), 'limited': load('papers.json')},
        stats={
            'year': load('stats_year.json'),
            'topics': {
                'all': load('stats_topics_all.json'),
                'limited': load('stats_topics_limited.json'),
            },
            'series': [load(f'stats_series_{index}.json') for index in range(1, 5)],
        },
        analysis=load('analysis.json'),
        topic='肝癌免疫治疗耐药机制的最新进展',
        condition='模式 A；真实测试样本',
        sources='OpenAlex 真实聚合与论文池',
        translations=TRANSLATIONS,
        generated_at='2026-11-24',
        output_dir=tmp_path,
    )

    result = build_graph_artifacts(tmp_path, '肝癌免疫治疗耐药机制', 50)

    assert result['artifact_count'] == 6
    for name in ('index.html', 'desktop.html', 'mobile.html', '文献图谱仪表盘.html'):
        text = (tmp_path / name).read_text(encoding='utf-8')
        assert '语义关系' in text
        assert '因素' in text
        assert '方法' in text
    index = (tmp_path / 'index.html').read_text(encoding='utf-8')
    assert '满血版' in index and '轻量版' in index
    assert (tmp_path / '文献图谱仪表盘.svg').read_text(encoding='utf-8').startswith('<svg')
    assert (tmp_path / '文献图谱仪表盘.png').read_bytes().startswith(b'\x89PNG')
