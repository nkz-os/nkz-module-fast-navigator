import json

import pytest

from app.inputs.provenance import (
    ENTERED,
    MEASURED,
    MissingInput,
    Notice,
    Override,
    Sourced,
    missing,
    table,
)


def test_override_needs_a_reason():
    with pytest.raises(ValueError):
        Override("crop.n_product_pct", 2.0, "  ", "u1", "2026-10-13T10:00:00Z")


def test_override_rejects_non_finite_values():
    with pytest.raises(ValueError):
        Override("soil.ph", float("nan"), "lab sheet", "u1", "2026-10-13T10:00:00Z")


def test_override_is_entered_with_its_reason_and_author():
    s = Override("soil.ph", 7.9, " lab sheet ", "u1", "2026-10-13T10:00:00Z").as_sourced()
    assert s.provenance == ENTERED
    assert s.note == "lab sheet"
    assert s.source == "user:u1@2026-10-13T10:00:00Z"


def test_missing_is_never_known_but_a_zero_is():
    assert not missing().known
    assert Sourced(0.0, MEASURED).known


def test_table_provenance():
    assert table("panagos_2022") == "table:panagos_2022"


def test_everything_serialises_to_json():
    json.dumps([Sourced(1.5, MEASURED, "s", "n").to_dict(), Notice("x", {"a": 1}).to_dict(),
                MissingInput("soil.ph", "soil").to_dict()])
