import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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

    def generate_project_themes(self, direction):
        """Return 1–3 concrete project themes for the B-mode entry step.

        The model only proposes structure (name/goal/object/method/expected
        output); no counts, papers, institutions, or results are invented here.
        """
        response = self.model.complete_json(
            '你是科研项目选题助手。基于用户的研究方向，凝练 1–3 个彼此不同、可执行的具体项目主题。'
            '严格返回 JSON {"themes": [...]}，最多 3 个。每项必须含：'
            'name（项目名称，具体到研究对象与问题）、goal（一句话目标）、'
            'object（研究对象/场景）、method（拟用方法或技术路线）、'
            'expected_output（预期产出）。'
            '不得编造论文、数据、团队基础、资助结论或命中数；信息不足时用概括表述，不得写空。',
            {'direction': direction, 'max_themes': 3},
        )
        raw = response.get('themes', []) if isinstance(response, dict) else []
        if not raw and isinstance(response, dict):
            raw = response.get('candidates', [])
        options = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            goal = str(item.get('goal') or '').strip()
            if not name or not goal or name in seen:
                continue
            seen.add(name)
            theme = {
                'name': name,
                'goal': goal,
                'object': str(item.get('object') or '').strip(),
                'method': str(item.get('method') or '').strip(),
                'expected_output': str(item.get('expected_output') or '').strip(),
            }
            preview_lines = [
                f"研究对象：{theme['object'] or '未提供'}",
                f"方法：{theme['method'] or '未提供'}",
                f"预期产出：{theme['expected_output'] or '未提供'}",
            ]
            options.append({
                'value': f'theme-{len(options) + 1}',
                'label': name,
                'description': goal,
                'preview': '\n'.join(preview_lines),
                'theme': theme,
            })
            if len(options) == 3:
                break
        return options

    def _count(self, query):
        script = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts' / 'search_papers.py'
        completed = subprocess.run(
            [sys.executable, str(script), 'openalex', '--query', query, '--count-only'],
            capture_output=True,
            text=True,
            timeout=20,
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

        def safe_count(candidate):
            try:
                return self.count_runner(candidate['en'])
            except Exception:
                return None

        if candidates:
            with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
                hits = list(pool.map(safe_count, candidates))
        else:
            hits = []
        options = [
            {**candidate, 'hits': candidate_hits}
            for candidate, candidate_hits in zip(candidates, hits)
        ]
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
