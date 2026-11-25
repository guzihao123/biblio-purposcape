from app.task_presenters import _delivery_card, _years_card


def test_years_card_has_no_recommendation_markers():
    for mode in ('A', 'B', 'C', 'D'):
        labels = [option['label'] for option in _years_card(mode)['options']]
        assert all('推荐' not in label for label in labels)


def test_delivery_card_letters_follow_position_not_form():
    labels = [option['label'] for option in _delivery_card('A')['options']]
    values = [option['value'] for option in _delivery_card('A')['options']]
    assert labels[0] == 'A 仅对话中给要点和代表文献'
    assert values[0] == 'B'

    d_labels = [option['label'] for option in _delivery_card('D')['options']]
    d_values = [option['value'] for option in _delivery_card('D')['options']]
    assert d_labels[0] == 'A 展示 PPT'
    assert d_values[0] == 'C'

    b_labels = [option['label'] for option in _delivery_card('B')['options']]
    assert b_labels[0] == 'A 正式调研报告（Word，含文献依据）'
