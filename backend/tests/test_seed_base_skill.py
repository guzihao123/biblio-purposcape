from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import seed_base_skill
from app.models import Base, SkillVersion


def test_seed_base_skill_publishes_once():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(bind=engine)

    seed_base_skill(engine)
    seed_base_skill(engine)

    with Session(bind=engine) as db:
        versions = db.query(SkillVersion).all()
        assert len(versions) == 1
        version = versions[0]
        assert version.state == 'published'
        assert version.version == 1
        assert version.content['cards']['order'] == [
            'direction', 'mode', 'terms', 'years', 'adjustment', 'delivery',
        ]
        assert version.regression_report == {'passed': True, 'checks': {}, 'errors': []}


def test_seed_base_skill_keeps_existing_version():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(bind=engine)
    with Session(bind=engine) as db:
        db.add(SkillVersion(
            id='existing',
            version=1,
            parent_id=None,
            state='draft',
            content={'cards': {'order': []}},
            content_hash='x',
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    seed_base_skill(engine)

    with Session(bind=engine) as db:
        versions = db.query(SkillVersion).all()
        assert len(versions) == 1
        assert versions[0].id == 'existing'