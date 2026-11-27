import json
from types import SimpleNamespace

from app.orchestration import Orchestrator


def test_recover_generate_restores_pool_without_building_graphs(tmp_path):
    task = SimpleNamespace(id='task-recover')
    service = Orchestrator(artifact_root=tmp_path, model=object())
    requests = []
    generated = []

    class Search:
        def run(self, request):
            requests.append(request)
            papers = [{
                'ref_no': 1,
                'title': 'Recovered paper',
                'abstract': 'The recovered abstract supports the project.',
                'evidence_level': 'B',
                'claim_eligible': True,
            }]
            (tmp_path / task.id / 'papers.json').write_text(json.dumps({'papers': papers}), encoding='utf-8')
            return {
                'limited': {'count': 1, 'papers': papers},
                'unlimited': {'count': 1, 'papers': papers},
            }

    class Analysis:
        def classify(self, papers):
            return {'clusters': ['recovered']}

        def extract_factor_votes(self, papers):
            return []

        def extract_relations(self, papers):
            return []

    def forbidden_graph(*args, **kwargs):
        raise AssertionError('graph builder must not run during recovery')

    def generate(task, stage_input):
        generated.append(stage_input)
        return {'state': 'done', 'checkpoint': {'stage': 'generate', 'clean': True}}

    service.search_factory = lambda root: Search()
    service.analysis_factory = lambda model: Analysis()
    service.stats_runner = lambda *args: {'counts': {'2026': 1}}
    service.graph_builder = forbidden_graph
    service.generate_stage = generate
    stage_input = {
        'answers': [
            {'card_id': 'direction', 'value': {'direction': '城市内涝'}},
            {'card_id': 'mode', 'value': {'mode': 'B'}},
            {'card_id': 'terms', 'value': {'terms': ['urban flooding']}},
            {'card_id': 'years', 'value': {'years': 'A'}},
            {'card_id': 'delivery', 'value': {'delivery': 'A'}},
        ],
    }

    result = service.recover_generate_stage(task, stage_input)

    assert requests[0].terms == ['urban flooding']
    assert generated == [stage_input]
    assert result['checkpoint']['recovered_search'] is True
    assert result['checkpoint']['graph_artifacts'] == 0
    assert (tmp_path / task.id / 'analysis.json').is_file()
    assert (tmp_path / task.id / 'stats.json').is_file()
