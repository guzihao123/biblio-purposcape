import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException


MAX_BODY_BYTES = 65_536
MAX_DEPTH = 8
MAX_ITEMS = 64
MAX_NODES = 1_024


def _error(status_code, code, message):
    raise HTTPException(status_code=status_code, detail={'code': code, 'message': message})


def _reject_constant(value):
    _error(422, 'invalid_json', 'JSON contains a non-finite number')


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _error(422, 'invalid_json', 'JSON contains duplicate object keys')
        result[key] = value
    return result


def _validate_shape(value):
    nodes = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            _error(422, 'invalid_answer', 'JSON has too many nodes')
        if depth > MAX_DEPTH:
            _error(422, 'invalid_answer', 'JSON nesting is too deep')
        if isinstance(current, dict):
            if len(current) > MAX_ITEMS:
                _error(422, 'invalid_answer', 'JSON object has too many keys')
            stack.extend((key, depth + 1) for key in current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if len(current) > MAX_ITEMS:
                _error(422, 'invalid_answer', 'JSON array has too many items')
            stack.extend((item, depth + 1) for item in current)


def _string(value, field, maximum, required=False):
    if not isinstance(value, str):
        _error(422, 'invalid_answer', f'{field} must be a string')
    if required and not value.strip():
        _error(422, 'invalid_answer', f'{field} must not be blank')
    if len(value) > maximum:
        _error(422, 'invalid_answer', f'{field} is too long')
    if any(ord(character) < 32 and character not in {'\n', '\t'} for character in value):
        _error(422, 'invalid_answer', f'{field} contains control characters')


def _keys(value, allowed):
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _error(422, 'invalid_answer', f'unknown answer fields: {", ".join(unknown)}')


def _year(value):
    if isinstance(value, bool) or not isinstance(value, int):
        _error(422, 'invalid_answer', 'year must be an integer')
    current = datetime.now(timezone.utc).year
    if not 1900 <= value <= current + 1:
        _error(422, 'invalid_answer', 'year is outside the allowed range')


def _project_theme(theme):
    if not isinstance(theme, dict):
        _error(422, 'invalid_answer', 'theme must be an object')
    _keys(theme, {'name', 'goal', 'object', 'method', 'expected_output', 'custom'})
    for field, maximum in (
        ('name', 500), ('goal', 2_000), ('object', 4_000),
        ('method', 4_000), ('expected_output', 4_000), ('custom', 2_000),
    ):
        if field in theme:
            _string(theme[field], f'theme.{field}', maximum)
    if not any(str(theme.get(field) or '').strip() for field in ('name', 'custom')):
        _error(422, 'invalid_answer', 'theme requires a name or custom text')


def validate_answer_value(card_id, value):
    if not isinstance(value, dict):
        _error(422, 'invalid_answer', 'answer value must be an object')
    _validate_shape(value)

    if card_id == 'direction':
        _keys(value, {'direction'})
        _string(value.get('direction'), 'direction', 2_000, required=True)
        return

    if card_id == 'mode':
        _keys(value, {
            'mode', 'c_route', 'c_info_route', 'c_material', 'user_results',
            'target_journal', 'team_context', 'project', 'policy_materials',
            'custom', 'theme',
        })
        _string(value.get('mode'), 'mode', 10, required=True)
        if value['mode'] not in {'A', 'B', 'C', 'D', 'E'}:
            _error(422, 'invalid_answer', 'unsupported mode')
        if 'c_route' in value and value['c_route'] not in {'C1', 'C2', 'C1+C2'}:
            _error(422, 'invalid_answer', 'unsupported C route')
        if 'c_info_route' in value:
            if value['mode'] != 'C':
                _error(422, 'invalid_answer', 'c_info_route is only valid for mode C')
            if value['c_info_route'] not in {'skip', 'upload', 'oral'}:
                _error(422, 'invalid_answer', 'unsupported C info route')
            if value['c_info_route'] in {'upload', 'oral'} and not str(value.get('c_material') or '').strip():
                _error(422, 'invalid_answer', 'c_material is required for upload or oral')
        for field, maximum in (
            ('user_results', 16_000), ('c_material', 16_000),
            ('target_journal', 500), ('team_context', 8_000),
            ('policy_materials', 16_000), ('custom', 2_000),
        ):
            if field in value:
                _string(value[field], field, maximum)
        if value['mode'] == 'E' and not str(value.get('custom') or '').strip():
            _error(422, 'invalid_answer', 'mode E requires a custom purpose')
        if 'theme' in value:
            _project_theme(value['theme'])
        if 'project' in value:
            project = value['project']
            if not isinstance(project, dict):
                _error(422, 'invalid_answer', 'project must be an object')
            _keys(project, {
                'name', 'goal', 'funding', 'research_contents', 'technical_route',
                'feasibility', 'expected_outcomes',
            })
            for field, maximum in (
                ('name', 500), ('funding', 500), ('goal', 2_000),
                ('research_contents', 8_000), ('technical_route', 8_000),
                ('feasibility', 8_000), ('expected_outcomes', 8_000),
            ):
                if field in project:
                    _string(project[field], f'project.{field}', maximum)
        return

    if card_id == 'terms':
        _keys(value, {'terms'})
        terms = value.get('terms')
        if not isinstance(terms, list) or not 1 <= len(terms) <= 30:
            _error(422, 'invalid_answer', 'terms must contain 1 to 30 items')
        for term in terms:
            _string(term, 'term', 300, required=True)
        return

    if card_id == 'years':
        _keys(value, {'choice', 'from_year', 'years'})
        if 'choice' in value:
            _string(value['choice'], 'choice', 1, required=True)
            if value['choice'] not in {'A', 'B', 'C', 'D'}:
                _error(422, 'invalid_answer', 'unsupported year choice')
        if 'from_year' in value:
            _year(value['from_year'])
        if 'years' in value and isinstance(value['years'], str):
            _string(value['years'], 'years', 1, required=True)
            if value['years'] not in {'A', 'B', 'C', 'D'}:
                _error(422, 'invalid_answer', 'unsupported year choice')
            return
        if 'years' in value:
            years = value['years']
            if not isinstance(years, list) or len(years) != 2:
                _error(422, 'invalid_answer', 'years must contain start and end years')
            for year in years:
                _year(year)
            if years[0] > years[1]:
                _error(422, 'invalid_answer', 'year range is reversed')
        if 'choice' not in value and 'years' not in value and 'from_year' not in value:
            _error(422, 'invalid_answer', 'year selection is required')
        return

    if card_id == 'adjustment':
        _keys(value, {'adjustment', 'continue'})
        selected = value.get('adjustment', [])
        if isinstance(selected, str):
            selected = [selected]
        if not isinstance(selected, list) or len(selected) > 4:
            _error(422, 'invalid_answer', 'invalid adjustment selection')
        allowed = {'terms', 'years', 'mode', 'continue'}
        for item in selected:
            _string(item, 'adjustment item', 20, required=True)
            if item not in allowed:
                _error(422, 'invalid_answer', 'unsupported adjustment item')
        if 'continue' in value and not isinstance(value['continue'], bool):
            _error(422, 'invalid_answer', 'continue must be boolean')
        explicit_continue = value.get('continue') is True or 'continue' in selected
        if not explicit_continue and (not selected or set(selected) - {'terms', 'years', 'mode'}):
            _error(422, 'invalid_answer', 'select an adjustment or continue')
        return

    if card_id == 'delivery':
        _keys(value, {'form', 'delivery'})
        field = 'form' if 'form' in value else 'delivery'
        if field not in value:
            _error(422, 'invalid_answer', 'delivery form is required')
        _string(value[field], field, 10, required=True)
        if value[field] not in {'A', 'B', 'C'}:
            _error(422, 'invalid_answer', 'unsupported delivery form')
        return

    _error(422, 'invalid_answer', 'unknown card')


async def read_answer_body(request, card_id):
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            _error(422, 'invalid_content_length', 'invalid Content-Length')
        if length > MAX_BODY_BYTES:
            _error(413, 'answer_body_too_large', 'answer body exceeds 64 KiB')

    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            _error(413, 'answer_body_too_large', 'answer body exceeds 64 KiB')
        chunks.append(chunk)
    try:
        text = b''.join(chunks).decode('utf-8')
    except UnicodeDecodeError:
        _error(422, 'invalid_encoding', 'request body must be UTF-8')
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except HTTPException:
        raise
    except (ValueError, TypeError, RecursionError):
        _error(422, 'invalid_json', 'request body is not valid JSON')
    if not isinstance(value, dict) or set(value) != {'value'}:
        _error(422, 'invalid_answer', 'request body must contain only the value field')
    value = value['value']
    validate_answer_value(card_id, value)
    return value
