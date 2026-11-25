import re
import subprocess
import sys
from pathlib import Path

from app.qwen import ChatModel


class CandidateService:
    def __init__(self, model=None, count_runner=None):
        self._model = model
        self.count_runner = count_runner or self._count

    @property
    def model(self):
        if self._model is None:
            self._model = ChatModel()
        return self._model

    def _count(self, query):
        script = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts' / 'search_papers.py'
        completed = subprocess.run(
            [sys.executable, str(script), 'openalex', '--query', query, '--count-only'],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if completed.returncode != 0:
            raise RuntimeError('OpenAlex candidate count failed')
        match = re.search(r'命中总数\(标题\+摘要\):\s*(\d+)', completed.stdout)
        if not match:
            raise RuntimeError('OpenAlex candidate count was unreadable')
        return int(match.group(1))

    def generate(self, direction, mode):
        response = self.model.complete_json(
            '你是科研检索术语助手。基于用户方向和用途返回 JSON {"candidates": [...]}，最多 4 个。每项含 zh（中文术语）、en（用于 OpenAlex 的准确英文检索词）、description、best_for。不得编造命中数或论文。',
            {'direction': direction, 'mode': mode, 'max_candidates': 4},
        )
        raw = response.get('candidates', []) if isinstance(response, dict) else []
        candidates = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            zh = str(item.get('zh') or '').strip()
            en = str(item.get('en') or '').strip()
            if not zh or not en or en in seen:
                continue
            seen.add(en)
            candidates.append({
                'zh': zh,
                'en': en,
                'description': str(item.get('description') or '').strip(),
                'best_for': str(item.get('best_for') or '').strip(),
            })
            if len(candidates) == 4:
                break

        options = []
        for candidate in candidates:
            try:
                hits = self.count_runner(candidate['en'])
            except Exception:
                hits = None
            options.append({
                **candidate,
                'hits': hits,
            })
        valid_hits = [option['hits'] for option in options if option['hits'] is not None]
        recommended = max(valid_hits) if valid_hits else None
        recommended_assigned = False
        for option in options:
            hits = option['hits']
            label = f"{option['zh']}（命中 {hits}）" if hits is not None else f"{option['zh']}（命中未知）"
            if hits is not None and hits == recommended and not recommended_assigned:
                label = f"{option['zh']}（命中 {hits}，推荐）"
                recommended_assigned = True
            preview = option['en'] + '\n' + option['description']
            if option['best_for']:
                preview += f"\n适合：{option['best_for']}"
            preview += '\n命中数只证明该词有相关文献，不证明检索精准。'
            option['label'] = label
            option['description'] = option['description'] or '由当前研究方向生成的候选术语'
            option['preview'] = preview
            option['value'] = option['en']
        return options
