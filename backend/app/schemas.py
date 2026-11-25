from typing import Optional

from pydantic import BaseModel

try:
    from enum import StrEnum
except ImportError:  # Python 3.9 compatibility for the project's declared runtime.
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self):
            return self.value


class TaskState(StrEnum):
    COLLECTING_MODE = 'collecting_mode'
    COLLECTING_TERMS = 'collecting_terms'
    COLLECTING_YEARS = 'collecting_years'
    SEARCHING = 'searching'
    DASHBOARD_READY = 'dashboard_ready'
    ADJUSTING = 'adjusting'
    DELIVERY_CONFIRMED = 'delivery_confirmed'
    GENERATING = 'generating'
    VERIFYING = 'verifying'
    DONE = 'done'
    ERROR = 'error'


class CardId(StrEnum):
    DIRECTION = 'direction'
    MODE = 'mode'
    TERMS = 'terms'
    YEARS = 'years'
    ADJUSTMENT = 'adjustment'
    DELIVERY = 'delivery'


class AnswerResult(BaseModel):
    state: TaskState
    next_card: Optional[CardId]
    job_id: Optional[str]
