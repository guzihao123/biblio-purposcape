from app.task_presenters import _delivery_card, _mode_card, _years_card


def test_years_card_has_no_recommendation_markers():
    for mode in ('A', 'B', 'C', 'D'):
        labels = [option['label'] for option in _years_card(mode)['options']]
        assert all('推荐' not in label for label in labels)


def test_delivery_card_keeps_form_letters_when_order_changes():
    labels = [option['label'] for option in _delivery_card('A')['options']]
    values = [option['value'] for option in _delivery_card('A')['options']]
    assert labels[0] == 'B 仅对话中给要点和代表文献'
    assert values[0] == 'B'
    assert labels[1] == 'A 正式调研报告（Word，含文献依据）'

    d_labels = [option['label'] for option in _delivery_card('D')['options']]
    d_values = [option['value'] for option in _delivery_card('D')['options']]
    assert d_labels[0] == 'C 展示 PPT'
    assert d_values[0] == 'C'
    assert d_labels[1] == 'A 正式调研报告（Word，含文献依据）'

    b_labels = [option['label'] for option in _delivery_card('B')['options']]
    assert b_labels[0] == 'A 正式调研报告（Word，含文献依据）'


def test_c_mode_card_has_three_info_routes_material_and_optional_journal():
    fields = _mode_card()['conditional_fields']['C']
    by_name = {field['name']: field for field in fields}

    assert [option['value'] for option in by_name['c_info_route']['options']] == ['skip', 'upload', 'oral']
    assert [option['label'] for option in by_name['c_info_route']['options']] == [
        '跳过，按通用口径写框架',
        '已有论文初稿，提供文件',
        '现场口述研究问题与方法',
    ]
    assert [option['description'] for option in by_name['c_info_route']['options']] == [
        '不提供本文细节，只给框架与占位提示，并在交付中注明。',
        '用户提供论文文件或粘贴内容后，先提取研究目标、方法、数据与创新，再决定补检索。',
        '用户直接说明研究问题、方法与创新，据此填写本文研究思路与贡献相关内容。',
    ]
    assert by_name['c_material']['kind'] == 'textarea'
    assert '题目、摘要、方法、结果、创新' in by_name['c_material']['label']
    assert 'target_journal' not in by_name
    assert 'user_results' not in by_name


def test_b_mode_card_asks_project_fields_and_optional_materials():
    fields = _mode_card()['conditional_fields']['B']
    names = [field['name'] for field in fields]

    assert names == ['name', 'goal', 'funding', 'b_input_path', 'project_draft', 'policy_materials']
    assert [field.get('required') for field in fields] == [True, True, None, None, None, None]
    assert fields[-1]['kind'] == 'textarea'
    for generated in ('research_contents', 'technical_route', 'feasibility', 'expected_outcomes'):
        assert generated not in names


def test_mode_card_exposes_custom_e_option_and_generic_custom_field():
    card = _mode_card()
    options = {option['value']: option for option in card['options']}

    assert 'E' in options
    assert options['E']['label'] == 'E 其他用途（自定义）'
    assert card['custom']['label'] == '自定义用途'
    assert card['custom']['required'] is True
    assert card['custom_for'] == ['E']


def test_delivery_previews_cover_dialogue_and_long_ppt_requirements():
    options = {option['value']: option for option in _delivery_card('A')['options']}
    assert '七类各 2 个选题槽位' in options['B']['preview']
    d_options = {option['value']: option for option in _delivery_card('D')['options']}
    assert '20–30 页' in d_options['C']['preview']
    assert '真实图表' in d_options['C']['preview']


def test_d_delivery_card_exposes_custom_other_form():
    card = _delivery_card('D')
    values = [option['value'] for option in card['options']]
    assert 'OTHER' in values
    assert card['custom_for'] == ['OTHER']
    assert card['custom']['required'] is True
    assert 'OTHER' not in [option['value'] for option in _delivery_card('A')['options']]
