import html
import subprocess
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts'


def build_graph_artifacts(task_dir, topic, pool_count):
    task_dir = Path(task_dir)
    outputs = {
        'dashboard': task_dir / '文献图谱仪表盘.html',
        'desktop': task_dir / 'desktop.html',
        'mobile': task_dir / 'mobile.html',
    }
    commands = [
        [sys.executable, str(SCRIPT_ROOT / 'build_dashboard.py'), '--data', str(task_dir / 'dashboard_data.json'), '--out', str(outputs['dashboard'])],
        [sys.executable, str(SCRIPT_ROOT / 'build_desktop_premium.py'), '--data', str(task_dir / 'dashboard_data.json'), '--out', str(outputs['desktop'])],
        [sys.executable, str(SCRIPT_ROOT / 'build_static_site.py'), '--data', str(task_dir / 'dashboard_data.json'), '--out', str(outputs['mobile']), '--long-image', str(task_dir / '文献图谱仪表盘.png')],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0:
            raise RuntimeError('dashboard renderer failed: ' + (completed.stderr or completed.stdout)[-500:])

    template = (SCRIPT_ROOT / 'index_template.html').read_text(encoding='utf-8')
    index = template.replace('__TOPIC__', html.escape(topic)).replace('__POOL_COUNT__', str(pool_count))
    index = index.replace('__DATE__', __import__('datetime').date.today().isoformat())
    (task_dir / 'index.html').write_text(index, encoding='utf-8')
    expected = [
        task_dir / 'index.html',
        outputs['desktop'],
        outputs['mobile'],
        outputs['dashboard'],
        task_dir / '文献图谱仪表盘.svg',
        task_dir / '文献图谱仪表盘.png',
    ]
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError('dashboard artifacts are incomplete: ' + ', '.join(missing))
    return {'artifact_count': len(expected), 'files': [str(path) for path in expected]}
