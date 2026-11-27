from copy import deepcopy

from app.writing import WritingService, _d_display_language_errors, _repair_d_components
from test_writing import PAPERS, component_data, make_task


def test_d_repair_adds_reading_cards_from_pool_abstracts():
    data = component_data('D')
    data['reading_cards'] = data['reading_cards'][:1]

    repaired = _repair_d_components(deepcopy(data), PAPERS)

    assert 3 <= len(repaired['reading_cards']) <= 5
    for card in repaired['reading_cards']:
        assert card['ref'] in {1, 2}
        assert card['reading_depth'] == '仅摘要'
        quote = card['evidence'][0]['quotes'][str(card['ref'])]
        paper = next(paper for paper in PAPERS if paper['ref_no'] == card['ref'])
        assert quote in paper['abstract']
    assert _d_display_language_errors(repaired) == []


def test_d_component_generation_repairs_instead_of_stopping(tmp_path):
    data = component_data('D')
    data['reading_cards'] = []

    class ShortCardsModel:
        def complete_json(self, system_prompt, payload):
            if payload.get('stage') == 'components':
                return {'components': data}
            raise AssertionError('body generation is not part of this test')

    task = make_task('D', tmp_path, component_data=None)
    components = WritingService(workspace_root=tmp_path, model=ShortCardsModel()).produce_components(task)

    assert 3 <= len(components.data['reading_cards']) <= 5
    assert any(event.kind == 'd_components_repaired' for event in task.events)
    assert '精读页' in components.markdown or '精读' in components.markdown