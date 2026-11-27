"""Read report documents with a deterministic fallback when artifacts are absent."""

from pathlib import Path

from app.writing import BODY_FILES


def _read(directory, name):
    path = Path(directory) / name
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def _fallback_notice(label):
    return f'> 提示：{label}尚未生成或制品未同步，请重新运行任务或联系管理员。\n'


def read_report_documents(directory, mode):
    mode = str(mode or 'A').upper()
    body_name = BODY_FILES.get(mode, '综述初稿.md')
    body = _read(directory, body_name)
    outline = _read(directory, 'outline.md')
    sample = _read(directory, 'sample.md')
    components = _read(directory, 'components.md')
    missing = []
    if not body:
        missing.append(body_name)
    if not outline:
        missing.append('outline.md')
    if not sample:
        missing.append('sample.md')

    if mode in {'C', 'C1+C2'}:
        if not body:
            c1_body = _read(directory, 'C1_引言.md')
            c2_body = _read(directory, 'C2_文献综述.md')
            if c1_body or c2_body:
                body = c1_body + ('\n\n## 独立文献综述\n\n' + c2_body if c2_body else '')
        if not outline:
            parts = [_read(directory, 'outline_C1.md'), _read(directory, 'outline_C2.md')]
            outline = '\n\n---\n\n'.join(part for part in parts if part)
        if not sample:
            parts = [_read(directory, 'sample_C1.md'), _read(directory, 'sample_C2.md')]
            sample = '\n\n---\n\n'.join(part for part in parts if part)

    if not body and components.strip():
        body = '## 构件与正文回退（正文文件未生成）\n\n' + components
    if not outline and body.strip():
        outline = '## 提纲（原提纲未生成，以下为正文摘录）\n\n' + body[:4000]
    if not sample and body.strip():
        sample = '## 样章（原样章未生成，以下为正文摘录）\n\n' + body[:2000]
    if not body.strip():
        body = _fallback_notice('正文')
    if not outline.strip():
        outline = _fallback_notice('提纲')
    if not sample.strip():
        sample = _fallback_notice('样章')
    return {
        'body': body,
        'outline': outline,
        'sample': sample,
        'missing': missing,
    }

def read_figure_diagnosis(directory):
    """Summarize D figure acquisition without requiring the user to find files."""
    import json

    manifest = Path(directory) / 'ppt_asset_manifest.json'
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    rows = payload.get('figure_acquisition') or []
    if not isinstance(rows, list):
        return None
    items = []
    succeeded = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        count = int(row.get('figure_count') or 0)
        if count > 0:
            succeeded += 1
        items.append({
            'ref_no': row.get('ref_no'),
            'status': row.get('status') or '未记录',
            'figure_count': count,
            'pdf_backend': row.get('pdf_backend') or '',
            'failures': [str(item)[:300] for item in (row.get('failures') or [])[:3]],
        })
    return {
        'available': True,
        'succeeded': succeeded,
        'failed': len(items) - succeeded,
        'items': items,
    }
