import itertools

import pytest

from app.plans.states import (
    HOLDER,
    TECHNICIAN,
    TRANSITIONS,
    Action,
    Guard,
    State,
    TransitionError,
    next_state,
)

FIELD_WORKER = "Farmer"      # read-only since the 2026-10-31 role matrix
ALL = frozenset({HOLDER, TECHNICIAN})
READY = Guard(calc_fresh=True, blocking_findings=0, close_allowed=True)

ALLOWED = {
    (State.DRAFT, Action.EDIT): (State.DRAFT, ALL),
    (State.CALCULATED, Action.EDIT): (State.DRAFT, ALL),
    (State.IN_REVIEW, Action.EDIT): (State.IN_REVIEW, {TECHNICIAN}),
    (State.DRAFT, Action.CALCULATE): (State.CALCULATED, ALL),
    (State.CALCULATED, Action.CALCULATE): (State.CALCULATED, ALL),
    (State.IN_REVIEW, Action.CALCULATE): (State.IN_REVIEW, {TECHNICIAN}),
    (State.CALCULATED, Action.SUBMIT): (State.IN_REVIEW, ALL),
    (State.IN_REVIEW, Action.RETURN): (State.DRAFT, {TECHNICIAN}),
    (State.IN_REVIEW, Action.SIGN): (State.SIGNED, {TECHNICIAN}),
    (State.CALCULATED, Action.CLOSE): (State.SIGNED, {HOLDER}),
    (State.SIGNED, Action.REVISE): (State.SIGNED, ALL),
}


def test_the_table_is_exactly_the_spec():
    assert {k: (v[0], set(v[1])) for k, v in TRANSITIONS.items()} == {
        k: (v[0], set(v[1])) for k, v in ALLOWED.items()}


@pytest.mark.parametrize("key", list(ALLOWED))
def test_every_allowed_transition(key):
    state, action = key
    target, roles = ALLOWED[key]
    for role in roles:
        assert next_state(state, action, {role}, READY) == target


@pytest.mark.parametrize("key", [k for k in itertools.product(State, Action) if k not in ALLOWED])
def test_every_other_pair_is_refused(key):
    with pytest.raises(TransitionError) as err:
        next_state(key[0], key[1], ALL, READY)
    assert err.value.code == "not_allowed"


@pytest.mark.parametrize("key", list(ALLOWED))
def test_the_wrong_role_is_refused(key):
    state, action = key
    _, roles = ALLOWED[key]
    for role in ({HOLDER, TECHNICIAN, FIELD_WORKER} - set(roles)):
        with pytest.raises(TransitionError) as err:
            next_state(state, action, {role}, READY)
        assert err.value.code == "forbidden"


@pytest.mark.parametrize("state,action,role", [
    (State.CALCULATED, Action.SUBMIT, HOLDER),
    (State.IN_REVIEW, Action.SIGN, TECHNICIAN),
    (State.CALCULATED, Action.CLOSE, HOLDER),
])
def test_a_stale_calculation_blocks_submit_sign_and_close(state, action, role):
    with pytest.raises(TransitionError) as err:
        next_state(state, action, {role}, Guard(calc_fresh=False, close_allowed=True))
    assert err.value.code == "stale_calculation"


@pytest.mark.parametrize("state,action,role", [
    (State.IN_REVIEW, Action.SIGN, TECHNICIAN),
    (State.CALCULATED, Action.CLOSE, HOLDER),
])
def test_blocking_findings_prevent_signing_and_closing(state, action, role):
    with pytest.raises(TransitionError) as err:
        next_state(state, action, {role}, Guard(calc_fresh=True, blocking_findings=2,
                                                close_allowed=True))
    assert err.value.code == "blocking_findings"


def test_closing_needs_the_advice_rule_to_allow_it():
    with pytest.raises(TransitionError) as err:
        next_state(State.CALCULATED, Action.CLOSE, {HOLDER}, Guard(calc_fresh=True))
    assert err.value.code == "advice_required"


def test_submit_does_not_care_about_findings():
    guard = Guard(calc_fresh=True, blocking_findings=3)
    assert next_state(State.CALCULATED, Action.SUBMIT, {HOLDER}, guard) == State.IN_REVIEW


def test_strings_are_accepted():
    assert next_state("draft", "calculate", {HOLDER}, READY) == State.CALCULATED
