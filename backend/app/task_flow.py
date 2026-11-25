from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.adjustments import apply_adjustment
from app.answer_validation import validate_answer_value
from app.db import SessionLocal
from app.models import InviteSession, Task, TaskAnswer, TaskEvent, TaskJob
from app.schemas import AnswerResult, CardId, TaskState
from app.security import require_owner


CARD_TRANSITIONS = {
    TaskState.COLLECTING_MODE: {
        CardId.DIRECTION: (TaskState.COLLECTING_MODE, CardId.MODE),
        CardId.MODE: (TaskState.COLLECTING_TERMS, CardId.TERMS),
    },
    TaskState.COLLECTING_TERMS: {
        CardId.TERMS: (TaskState.COLLECTING_YEARS, CardId.YEARS),
    },
    TaskState.COLLECTING_YEARS: {
        CardId.YEARS: (TaskState.SEARCHING, None),
    },
    TaskState.DASHBOARD_READY: {
        CardId.ADJUSTMENT: (TaskState.ADJUSTING, CardId.DELIVERY),
    },
    TaskState.ADJUSTING: {
        CardId.DELIVERY: (TaskState.GENERATING, None),
    },
}

JOB_KINDS = {
    CardId.YEARS: 'search',
    CardId.DELIVERY: 'generate',
}

ADJUSTMENT_ORDER = ('mode', 'terms', 'years')
ADJUSTMENT_CARDS = {
    'mode': CardId.MODE,
    'terms': CardId.TERMS,
    'years': CardId.YEARS,
}
COLLECTION_STATES = {
    CardId.MODE: TaskState.COLLECTING_MODE,
    CardId.TERMS: TaskState.COLLECTING_TERMS,
    CardId.YEARS: TaskState.COLLECTING_YEARS,
}


@dataclass(frozen=True)
class AnswerDecision:
    result: AnswerResult
    changed: bool


class ConcurrentTransition(Exception):
    pass


def _selection(value):
    selected = value.get('adjustment', [])
    if isinstance(selected, str):
        selected = [selected]
    if not isinstance(selected, (list, tuple)):
        return []
    if 'continue' in selected or value.get('continue'):
        return []
    return [item for item in ADJUSTMENT_ORDER if item in selected]


def _adjustment_transition(value):
    selected = _selection(value)
    if not selected:
        return TaskState.ADJUSTING, CardId.DELIVERY
    card = ADJUSTMENT_CARDS[selected[0]]
    return COLLECTION_STATES[card], card


def _pending_revision(db, task, card):
    if COLLECTION_STATES.get(card) != TaskState(task.state) or task.next_card != card.value:
        return None
    adjustment = db.query(TaskAnswer).filter_by(
        task_id=task.id,
        card_id=CardId.ADJUSTMENT.value,
    ).one_or_none()
    if adjustment is None or card.value not in _selection(adjustment.value):
        return None
    return _selection(adjustment.value)


def _revision_task(db, task, value):
    mode_answer = db.query(TaskAnswer).filter_by(
        task_id=task.id,
        card_id=CardId.MODE.value,
    ).one_or_none()
    previous = mode_answer.value if mode_answer is not None else {}
    user_results = value.get('user_results', previous.get('user_results', ''))
    return SimpleNamespace(state=task.state, user_results=user_results)


def _claim_transition(db, task, result_state, next_card):
    expected_state = task.state
    expected_next = task.next_card
    statement = update(Task).where(Task.id == task.id, Task.state == expected_state)
    if expected_next is None:
        statement = statement.where(Task.next_card.is_(None))
    else:
        statement = statement.where(Task.next_card == expected_next)
    statement = statement.values(
        state=result_state.value,
        next_card=next_card.value if next_card is not None else None,
        updated_at=datetime.now(timezone.utc),
    )
    result = db.execute(statement)
    if result.rowcount != 1:
        raise ConcurrentTransition


def _answer_result(answer):
    return AnswerResult(
        state=TaskState(answer.result_state),
        next_card=CardId(answer.next_card) if answer.next_card is not None else None,
        job_id=answer.job_id,
    )


def _conflict():
    return HTTPException(
        status_code=409,
        detail={
            'code': 'answer_conflict',
            'message': '该卡片已提交，不能覆盖原答案。',
        },
    )


def _race_result(db, task_id, card, value):
    db.rollback()
    existing = db.query(TaskAnswer).filter_by(task_id=task_id, card_id=card.value).one_or_none()
    if existing is not None and existing.value == value:
        return AnswerDecision(result=_answer_result(existing), changed=False)
    raise _conflict()


def _revise_answer(db, task, answer, value, selected):
    card = CardId(answer.card_id)
    result = apply_adjustment(_revision_task(db, task, value), {card.value: value})
    current_index = selected.index(card.value)
    remaining = selected[current_index + 1:]
    if remaining:
        next_card = ADJUSTMENT_CARDS[remaining[0]]
        result_state = COLLECTION_STATES[next_card]
    else:
        result_state = result.state
        next_card = result.next_card

    _claim_transition(db, task, result_state, next_card)
    previous = answer.value
    answer.value = value
    answer.result_state = result_state.value
    answer.next_card = next_card.value if next_card is not None else None
    answer.job_id = None

    if result_state == TaskState.SEARCHING:
        job = db.query(TaskJob).filter_by(task_id=task.id, kind='search').one_or_none()
        if job is not None:
            job.status = 'pending'
            answer.job_id = job.id

    db.add(TaskEvent(
        task_id=task.id,
        event_type='answer_revised',
        payload={
            'card_id': card.value,
            'previous_value': previous,
            'new_value': value,
            'rebuild': sorted(result.rebuild),
            'reuse': sorted(result.reuse),
            'follow_up': result.follow_up,
            'mode_template': result.mode_template,
        },
    ))
    db.commit()
    db.refresh(answer)
    return AnswerDecision(result=_answer_result(answer), changed=True)


def _record_adjustment(db, task, answer, value):
    selected = _selection(value)
    raw_selection = value.get('adjustment', [])
    if isinstance(raw_selection, str):
        raw_selection = [raw_selection]
    explicit_continue = bool(value.get('continue')) or (
        isinstance(raw_selection, (list, tuple)) and 'continue' in raw_selection
    )
    if not selected and not explicit_continue:
        raise HTTPException(status_code=422, detail='Select an adjustment or continue with the original plan')

    result_state, next_card = _adjustment_transition(value)
    _claim_transition(db, task, result_state, next_card)
    previous = answer.value if answer is not None else None
    if answer is None:
        answer = TaskAnswer(
            task_id=task.id,
            card_id=CardId.ADJUSTMENT.value,
            value=value,
            result_state=result_state.value,
            next_card=next_card.value if next_card is not None else None,
        )
        db.add(answer)
    else:
        answer.value = value
        answer.result_state = result_state.value
        answer.next_card = next_card.value if next_card is not None else None
        answer.job_id = None
    db.add(TaskEvent(
        task_id=task.id,
        event_type='adjustment_requested',
        payload={
            'previous_value': previous,
            'selected': _selection(value),
            'continue': not _selection(value),
        },
    ))
    db.commit()
    db.refresh(answer)
    return AnswerDecision(result=_answer_result(answer), changed=True)


def _record_c_requirements(db, task_id, value):
    """Write the two C card choices and the supplied material to the requirement ledger."""
    if value.get('mode') != 'C' or 'c_info_route' not in value:
        return
    db.add(TaskEvent(
        task_id=task_id,
        event_type='user_requirements_recorded',
        payload={
            'card_id': 'mode',
            'c_route': value.get('c_route', ''),
            'c_info_route': value['c_info_route'],
            'c_material': value.get('c_material', '') or value.get('user_results', ''),
            'target_journal': value.get('target_journal', ''),
        },
    ))


def _first_answer(db, task, card, value, transition):
    result_state, next_card = transition
    _claim_transition(db, task, result_state, next_card)
    if card == CardId.MODE:
        _record_c_requirements(db, task.id, value)
    answer = TaskAnswer(
        task_id=task.id,
        card_id=card.value,
        value=value,
        result_state=result_state.value,
        next_card=next_card.value if next_card is not None else None,
    )
    db.add(answer)
    try:
        db.flush()
    except IntegrityError:
        raise ConcurrentTransition from None

    job_kind = JOB_KINDS.get(card)
    if job_kind is not None:
        job = TaskJob(
            id=str(uuid4()),
            task_id=task.id,
            answer_id=answer.id,
            kind=job_kind,
        )
        db.add(job)
        db.flush()
        answer.job_id = job.id

    db.commit()
    db.refresh(answer)
    return AnswerDecision(result=_answer_result(answer), changed=True)


def answer_card_with_decision(task_id, card_id, value, session):
    card = CardId(card_id)
    validate_answer_value(card.value, value)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail='Task not found')
        require_owner(task, session)

        existing = db.query(TaskAnswer).filter_by(task_id=task_id, card_id=card.value).one_or_none()
        state = TaskState(task.state)
        try:
            if card == CardId.ADJUSTMENT and state == TaskState.DASHBOARD_READY and task.next_card == card.value:
                return _record_adjustment(db, task, existing, value)

            if existing is not None:
                selected = _pending_revision(db, task, card)
                if selected is not None:
                    return _revise_answer(db, task, existing, value, selected)
                if existing.value == value:
                    return AnswerDecision(result=_answer_result(existing), changed=False)
                raise _conflict()

            transition = CARD_TRANSITIONS.get(state, {}).get(card)
            if transition is None or task.next_card != card.value:
                raise HTTPException(
                    status_code=409,
                    detail={
                        'code': 'card_not_allowed',
                        'message': '当前卡片不可提交，请按页面顺序继续。',
                    },
                )
            return _first_answer(db, task, card, value, transition)
        except ConcurrentTransition:
            return _race_result(db, task_id, card, value)


def answer_card(task_id, card_id, value, session):
    return answer_card_with_decision(task_id, card_id, value, session).result
