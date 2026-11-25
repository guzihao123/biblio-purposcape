from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.candidates import CandidateService
from app.models import Base, InviteSession, SkillVersion, Task, TaskEvent
from app.task_presenters import card_for


class FakeModel:
    def complete_json(self, system_prompt, payload):
        return {
            'candidates': [
                {'zh': '城市内涝', 'en': 'urban flooding', 'description': '降雨与积水问题', 'best_for': '领域全景'},
                {'zh': '地下车库', 'en': 'underground parking', 'description': '地下空间场景', 'best_for': '财产损失评估'},
                {'zh': '韧性城市', 'en': 'resilient cities', 'description': '适应与恢复能力', 'best_for': '交叉方向'},
                {'zh': '内涝损失', 'en': 'flood loss estimation', 'description': '损失量化', 'best_for': '影响评估'},
                {'zh': '多余候选', 'en': 'extra candidate', 'description': '不应返回', 'best_for': '测试'},
            ]
        }


def count_runner(query):
    return {
        'urban flooding': 1200,
        'underground parking': 300,
        'resilient cities': 5000,
        'flood loss estimation': 80,
    }[query]


def test_candidates_use_chinese_labels_real_counts_and_highest_hit_recommendation():
    options = CandidateService(model=FakeModel(), count_runner=count_runner).generate('城市内涝与地下车库', 'A')

    assert len(options) == 4
    assert options[0]['value'] == 'urban flooding'
    assert options[0]['label'] == '城市内涝（命中 1200）'
    assert options[0]['preview'].startswith('urban flooding\n')
    recommended = [option for option in options if '推荐' in option['label']]
    assert len(recommended) == 1
    assert recommended[0]['value'] == 'resilient cities'
    assert recommended[0]['label'].startswith('韧性城市（命中 5000，推荐')


def test_count_failure_is_disclosed_without_fabricating_a_number():
    def flaky_count(query):
        if query == 'urban flooding':
            raise RuntimeError('429')
        return count_runner(query)

    options = CandidateService(model=FakeModel(), count_runner=flaky_count).generate('城市内涝', 'A')

    assert options[0]['label'] == '城市内涝（命中未知）'
    assert options[0]['hits'] is None
    assert '推荐' not in options[0]['label']


def test_project_themes_are_concrete_deduplicated_and_bounded_to_three():
    class ThemeModel:
        def complete_json(self, system_prompt, payload):
            assert payload['direction'] == '城市内涝与地下车库'
            return {
                'themes': [
                    {
                        'name': '车库暴露约束下的内涝损失联合校准',
                        'goal': '建立暴露、恢复与损失的联合校准方法',
                        'object': '城市地下车库',
                        'method': '联合建模与情景比较',
                        'expected_output': '校准方法与验证协议',
                    },
                    {
                        'name': '车库暴露约束下的内涝损失联合校准',
                        'goal': '重复主题不得保留',
                        'object': '重复',
                        'method': '重复',
                        'expected_output': '重复',
                    },
                    {
                        'name': '跨区内涝恢复过程的情景比较',
                        'goal': '比较不同恢复路径对损失评估的影响',
                        'object': '三个城区的车库',
                        'method': '调查研究与情景分析',
                        'expected_output': '情景比较报告',
                    },
                    {
                        'name': '缺少目标的主题',
                        'object': '车库',
                    },
                    {
                        'name': '第三个有效主题',
                        'goal': '形成可复用调查口径',
                        'object': '地下空间',
                        'method': '问卷与访谈',
                        'expected_output': '调查口径清单',
                    },
                    {
                        'name': '超过上限的主题',
                        'goal': '不应返回',
                        'object': '车库',
                        'method': '模型',
                        'expected_output': '报告',
                    },
                ]
            }

    options = CandidateService(model=ThemeModel()).generate_project_themes('城市内涝与地下车库')

    assert [option['value'] for option in options] == ['theme-1', 'theme-2', 'theme-3']
    assert [option['label'] for option in options] == [
        '车库暴露约束下的内涝损失联合校准',
        '跨区内涝恢复过程的情景比较',
        '第三个有效主题',
    ]
    assert all(option['description'] for option in options)
    assert options[0]['theme']['object'] == '城市地下车库'
    assert '研究对象：城市地下车库' in options[0]['preview']
    assert '方法：联合建模与情景比较' in options[0]['preview']
    assert '预期产出：校准方法与验证协议' in options[0]['preview']


def test_project_theme_model_failure_or_empty_result_returns_no_options():
    class EmptyModel:
        def complete_json(self, system_prompt, payload):
            return {'themes': []}

    assert CandidateService(model=EmptyModel()).generate_project_themes('城市内涝') == []


def test_terms_card_reads_latest_generated_candidates():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(InviteSession(id='owner'))
        db.add(SkillVersion(
            id='v1', version=1, state='published', content={'cards': {}}, content_hash='x',
            created_at=datetime.now(timezone.utc),
        ))
        task = Task(id='task-1', session_id='owner', skill_version_id='v1', next_card='terms')
        db.add(task)
        options = CandidateService(model=FakeModel(), count_runner=count_runner).generate('城市内涝', 'A')
        db.add(TaskEvent(task_id=task.id, event_type='terms_candidates', payload={'options': options}))
        db.commit()

        card = card_for(db, task)
        assert len(card['options']) == 4
        assert card['options'][0]['label'] == '城市内涝（命中 1200）'
        assert card['options'][0]['value'] == 'urban flooding'
