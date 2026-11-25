from dataclasses import dataclass, field
from typing import Optional

from app.schemas import CardId, TaskState


class AdjustmentError(ValueError):
    pass


@dataclass(frozen=True)
class AdjustmentResult:
    state: TaskState
    next_card: Optional[CardId]
    rebuild: set = field(default_factory=set)
    reuse: set = field(default_factory=set)
    follow_up: Optional[str] = None
    mode_template: Optional[str] = None


def _continue_requested(value):
    selection = value.get('adjustment')
    if isinstance(selection, str):
        selection = [selection]
    return bool(value.get('continue')) or bool(
        isinstance(selection, (list, tuple)) and 'continue' in selection
    )


def _mode(value):
    selected = value.get('mode')
    if isinstance(selected, dict):
        selected = selected.get('mode')
    return str(selected).upper() if selected is not None else None


def apply_adjustment(task, value):
    if TaskState(task.state) in {
        TaskState.DELIVERY_CONFIRMED,
        TaskState.GENERATING,
        TaskState.VERIFYING,
        TaskState.DONE,
    }:
        raise AdjustmentError('delivery has already been confirmed')

    if _continue_requested(value):
        return AdjustmentResult(state=TaskState.ADJUSTING, next_card=CardId.DELIVERY)

    rebuild = set()
    reuse = set()
    state = TaskState.DASHBOARD_READY
    next_card = CardId.ADJUSTMENT
    follow_up = None
    mode_template = None

    if value.get('terms') is not None:
        rebuild.update({
            'unlimited_search',
            'limited_search',
            'trend',
            'compare',
            'unlimited_topics',
            'limited_topics',
            'unlimited_pool_charts',
            'limited_pool_charts',
            'writing_pool',
            'reading_pool',
        })
        state = TaskState.SEARCHING
        next_card = None

    if value.get('years') is not None:
        rebuild.update({'limited_search', 'limited_topics', 'limited_pool_charts'})
        if not rebuild - {'limited_search', 'limited_topics', 'limited_pool_charts'}:
            reuse.update({
                'unlimited_search',
                'trend',
                'compare',
                'unlimited_pool_charts',
            })
        state = TaskState.SEARCHING
        next_card = None

    selected_mode = _mode(value)
    if selected_mode is not None:
        rebuild.update({'writing_pool', 'reading_pool', 'outline', 'body'})
        reuse.update({
            'unlimited_search',
            'limited_search',
            'trend',
            'compare',
            'unlimited_pool_charts',
            'limited_pool_charts',
        })
        mode_template = selected_mode
        if selected_mode == 'C' and not str(getattr(task, 'user_results', '') or '').strip():
            follow_up = 'user_results'
        if 'terms' not in value and 'years' not in value:
            state = TaskState.DASHBOARD_READY
            next_card = CardId.ADJUSTMENT

    return AdjustmentResult(
        state=state,
        next_card=next_card,
        rebuild=rebuild,
        reuse=reuse - rebuild,
        follow_up=follow_up,
        mode_template=mode_template,
    )
