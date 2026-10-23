"""
engine/agi17/task_control/task_state_machine.py
AGI 1.7 OMEGA COMMAND — Enforced 14-State Task State Machine

Enforces valid transitions across:
CREATED, PLANNED, QUEUED, READY, RUNNING, WAITING_FOR_RESOURCE, WAITING_FOR_INPUT,
VERIFYING, SUCCEEDED, FAILED, TIMED_OUT, CANCELED, INTERRUPTED, BLOCKED.
Rejects impossible state transitions rather than silently accepting them.
"""

from enum import Enum
from typing import Dict, Set


class TaskState(str, Enum):
    CREATED = "CREATED"
    TASK_CREATED = "TASK_CREATED"
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    DISPATCHED = "DISPATCHED"
    QUEUED = "QUEUED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    VERIFYING = "VERIFYING"
    VALIDATING = "VALIDATING"
    SUCCEEDED = "SUCCEEDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELED = "CANCELED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    BLOCKED = "BLOCKED"


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid task state transition is attempted."""


TERMINAL_STATES: Set[TaskState] = {
    TaskState.SUCCEEDED,
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.TIMED_OUT,
    TaskState.CANCELED,
    TaskState.CANCELLED,
}

VALID_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.CREATED: {
        TaskState.PLANNED,
        TaskState.AUTHORIZED,
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.TASK_CREATED: {
        TaskState.PLANNED,
        TaskState.AUTHORIZED,
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.PLANNED: {
        TaskState.AUTHORIZED,
        TaskState.DISPATCHED,
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.AUTHORIZED: {
        TaskState.DISPATCHED,
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.DISPATCHED: {
        TaskState.RUNNING,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.WAITING_FOR_INPUT,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.QUEUED: {
        TaskState.READY,
        TaskState.DISPATCHED,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.WAITING_FOR_INPUT,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.READY: {
        TaskState.RUNNING,
        TaskState.DISPATCHED,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.WAITING_FOR_INPUT,
        TaskState.QUEUED,
        TaskState.BLOCKED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_FOR_RESOURCE: {
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.TIMED_OUT,
        TaskState.CANCELED,
        TaskState.CANCELLED,
        TaskState.BLOCKED,
    },
    TaskState.WAITING_FOR_INPUT: {
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.TIMED_OUT,
        TaskState.CANCELED,
        TaskState.CANCELLED,
        TaskState.BLOCKED,
    },
    TaskState.RUNNING: {
        TaskState.VALIDATING,
        TaskState.VERIFYING,
        TaskState.WAITING_FOR_RESOURCE,
        TaskState.WAITING_FOR_INPUT,
        TaskState.FAILED,
        TaskState.TIMED_OUT,
        TaskState.CANCELED,
        TaskState.CANCELLED,
        TaskState.INTERRUPTED,
        TaskState.BLOCKED,
    },
    TaskState.VERIFYING: {
        TaskState.SUCCEEDED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.RUNNING,
        TaskState.TIMED_OUT,
        TaskState.CANCELED,
        TaskState.CANCELLED,
        TaskState.INTERRUPTED,
    },
    TaskState.VALIDATING: {
        TaskState.SUCCEEDED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.RUNNING,
        TaskState.TIMED_OUT,
        TaskState.CANCELED,
        TaskState.CANCELLED,
        TaskState.INTERRUPTED,
    },
    TaskState.FAILED: {
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.PLANNED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.TIMED_OUT: {
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.INTERRUPTED: {
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.RUNNING,
        TaskState.VERIFYING,
        TaskState.VALIDATING,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.BLOCKED: {
        TaskState.PLANNED,
        TaskState.QUEUED,
        TaskState.READY,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.CANCELLED,
    },
    TaskState.SUCCEEDED: set(),
    TaskState.COMPLETED: set(),
    TaskState.CANCELED: set(),
    TaskState.CANCELLED: set(),
}

ALLOWED_TRANSITIONS = VALID_TRANSITIONS


class TaskStateMachine:
    """Validates and enforces legal task state transitions."""

    @staticmethod
    def normalize(state: str | TaskState) -> TaskState:
        if isinstance(state, TaskState):
            return state
        try:
            return TaskState(str(state).upper())
        except ValueError as e:
            raise InvalidStateTransitionError(f"Unknown task state: {state}") from e

    @classmethod
    def can_transition(cls, current_state: str | TaskState, next_state: str | TaskState) -> bool:
        curr = cls.normalize(current_state)
        nxt = cls.normalize(next_state)
        return nxt in VALID_TRANSITIONS.get(curr, set())

    @classmethod
    def validate_transition(cls, current_state: str | TaskState, next_state: str | TaskState) -> TaskState:
        curr = cls.normalize(current_state)
        nxt = cls.normalize(next_state)
        if nxt not in VALID_TRANSITIONS.get(curr, set()):
            raise InvalidStateTransitionError(
                f"Illegal task state transition: {curr.value} -> {nxt.value}"
            )
        return nxt

    @classmethod
    def is_terminal(cls, state: str | TaskState) -> bool:
        s = cls.normalize(state)
        return s in TERMINAL_STATES
