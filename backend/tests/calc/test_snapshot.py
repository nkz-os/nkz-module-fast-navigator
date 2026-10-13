import json
from dataclasses import replace
from datetime import date

import pytest

from app.calc.assemble import SheetRequest, assemble
from app.calc.sheet import AssembledInputs, calculate
from app.calc.snapshot import (
    assembled_from_dict,
    assembled_to_dict,
    canonical_json,
    from_jsonable,
    sha256_of,
    to_jsonable,
)
from app.inputs.provenance import Notice, Sourced
from tests.calc.builders import assembled
from tests.fakes import URN, FakeSources, complete_data


def _round_trip(a: AssembledInputs) -> AssembledInputs:
    # Through real JSON, as the database stores it.
    return assembled_from_dict(json.loads(json.dumps(assembled_to_dict(a))))


def test_the_builders_sheet_round_trips_exactly():
    a = assembled()
    assert _round_trip(a) == a


def test_recalculating_from_the_copy_gives_the_same_figures():
    a = assembled()
    assert calculate(_round_trip(a)).to_dict() == calculate(a).to_dict()


async def test_a_sheet_assembled_from_the_sources_round_trips():
    req = SheetRequest(campaign=2027, parcel_ids=(URN,), tillage=True, irrigated=False,
                       rotation_years=4)
    a = await assemble(req, FakeSources(**complete_data()), date(2026, 10, 13))
    assert _round_trip(a) == a
    assert calculate(_round_trip(a)).to_dict() == calculate(a).to_dict()


def test_fallow_and_missing_preceding_crop_round_trip():
    a = assembled(previous_crop=None, previous_yield=None)
    assert _round_trip(a) == a


def test_generic_shapes():
    assert from_jsonable(tuple[int, ...], [1, 2]) == (1, 2)
    assert from_jsonable(tuple[float, float] | None, [42.0, -1.5]) == (42.0, -1.5)
    assert from_jsonable(tuple[float, float] | None, None) is None
    assert from_jsonable(dict[str, Sourced], {"a": {"value": 1, "provenance": "measured",
                                                    "source": None, "note": None}}) == {
        "a": Sourced(1, "measured")}
    assert to_jsonable((Notice("x", {"k": (1, 2)}),)) == [{"code": "x", "params": {"k": [1, 2]}}]


def test_canonical_json_and_seal_are_stable_through_json():
    snapshot = {"b": [1.5, 0.1 + 0.2, 1e-07], "a": {"z": "ñ", "y": None}}
    again = json.loads(json.dumps(snapshot))
    assert canonical_json(snapshot) == canonical_json(again)
    assert sha256_of(snapshot) == sha256_of(again) and len(sha256_of(snapshot)) == 64
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_a_changed_value_changes_the_seal():
    a = assembled()
    b = replace(a, rotation_years=a.rotation_years + 1)
    assert sha256_of(assembled_to_dict(a)) != sha256_of(assembled_to_dict(b))
