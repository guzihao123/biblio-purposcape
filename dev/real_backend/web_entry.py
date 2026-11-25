import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from offline_providers import OfflineModel, install

install()

from app.main import app
from app.skill_versions import SkillVersionService, load_base_config
from app.db import SessionLocal

with SessionLocal() as db:
    service = SkillVersionService(db)
    if service.active_version() is None:
        version = service.create_draft(parent_id=None, content=load_base_config(), actor='real-backend-acceptance-bootstrap')
        # The initial version is the project's frozen base. The admin test below
        # executes a new, real regression before creating the next publication.
        version.regression_report = {
            'passed': True,
            'checks': {'hcc': 'project-fixture-baseline', 'frontend_visual': 'fixture-baseline'},
            'errors': [],
        }
        db.commit()
        service.publish(version.id, actor='real-backend-acceptance-bootstrap')

import app.main as main_module
main_module.candidate_service._model = OfflineModel()
main_module.candidate_service.count_runner = lambda query: 4

if __name__ == '__main__':
    import os
    import uvicorn
    uvicorn.run(
        app,
        host='127.0.0.1',
        port=int(os.environ.get('REAL_BACKEND_PORT', '8000')),
        log_level='info',
    )
