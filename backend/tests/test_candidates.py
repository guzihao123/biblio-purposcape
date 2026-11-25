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
