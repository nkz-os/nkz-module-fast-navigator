"""Plan lifecycle (spec §8) as an explicit state machine: who may do what, from which state."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class State(StrEnum):
    DRAFT = "draft"
    CALCULATED = "calculated"
    IN_REVIEW = "in_review"
    SIGNED = "signed"
    SUPERSEDED = "superseded"


class Action(StrEnum):
    EDIT = "edit"
    CALCULATE = "calculate"
    SUBMIT = "submit"
    RETURN = "return"
    SIGN = "sign"
    CLOSE = "close"
    REVISE = "revise"


# Role matrix (owner, 2026-10-31). "Farmer" is the platform's field-worker role: read-only here.
# TenantAdmin stands for the farm holder.
HOLDER = "TenantAdmin"
TECHNICIAN = "TechnicalConsultant"
_EDITORS = frozenset({HOLDER, TECHNICIAN})      # create / edit / calculate / submit / revise

# (state, action) -> (next state, roles that may do it)
TRANSITIONS = MappingProxyType({
    (State.DRAFT, Action.EDIT): (State.DRAFT, _EDITORS),
    (State.CALCULATED, Action.EDIT): (State.DRAFT, _EDITORS),
    (State.IN_REVIEW, Action.EDIT): (State.IN_REVIEW, frozenset({TECHNICIAN})),
    (State.DRAFT, Action.CALCULATE): (State.CALCULATED, _EDITORS),
    (State.CALCULATED, Action.CALCULATE): (State.CALCULATED, _EDITORS),
    (State.IN_REVIEW, Action.CALCULATE): (State.IN_REVIEW, frozenset({TECHNICIAN})),
    (State.CALCULATED, Action.SUBMIT): (State.IN_REVIEW, _EDITORS),
    (State.IN_REVIEW, Action.RETURN): (State.DRAFT, frozenset({TECHNICIAN})),
    (State.IN_REVIEW, Action.SIGN): (State.SIGNED, frozenset({TECHNICIAN})),
    (State.CALCULATED, Action.CLOSE): (State.SIGNED, frozenset({HOLDER})),
    (State.SIGNED, Action.REVISE): (State.SIGNED, _EDITORS),
})


@dataclass(frozen=True)
class Guard:
    calc_fresh: bool = False       # results computed after the last change of the inputs
    blocking_findings: int = 0     # findings with severity "block"
    close_allowed: bool = False    # rule 6.6 lets the holder close without an advisor (D1)


class TransitionError(Exception):
    def __init__(self, code: str, detail: str, rules: list[str] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.rules = rules          # ids of the rules behind a "blocking_findings" refusal


def next_state(state: State | str, action: Action | str, roles: Iterable[str],
               guard: Guard) -> State:
    state, action = State(state), Action(action)
    if (state, action) not in TRANSITIONS:
        raise TransitionError("not_allowed", f"{action} is not possible in state {state}")
    target, allowed = TRANSITIONS[(state, action)]
    if not allowed & set(roles):
        raise TransitionError("forbidden",
                              f"{action} in state {state} needs one of {sorted(allowed)}")
    if action in (Action.SUBMIT, Action.SIGN, Action.CLOSE) and not guard.calc_fresh:
        raise TransitionError("stale_calculation", "recalculate after the last change first")
    if action in (Action.SIGN, Action.CLOSE) and guard.blocking_findings:
        raise TransitionError("blocking_findings",
                              f"{guard.blocking_findings} blocking findings must be solved first")
    if action == Action.CLOSE and not guard.close_allowed:
        raise TransitionError("advice_required", "an advisor must sign this plan (art. 6.6)")
    return target
