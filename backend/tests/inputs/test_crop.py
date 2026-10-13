import copy

import pytest

from app.inputs.crop import build_crop
from app.inputs.provenance import ENTERED, MissingInput, Notice, Override
from tests.conftest import load_contract

COEFF = load_contract("bioorch_coefficients_trzax.json")


def _o(param, value, reason="lab sheet"):
    return {param: Override(param, value, reason, "u1", "2026-10-13T10:00:00Z")}


def test_every_field_from_the_table_with_its_source():
    b = build_crop("TRZAX", COEFF, {})
    assert b.params is not None and not b.missing
    assert b.params.harvest_index_pct == pytest.approx(51.02)
    assert b.params.crop_type == "cereal" and b.params.n_fixing is False
    assert b.inputs["dm_product_pct"].provenance == "table:panagos_2022"
    assert b.inputs["n_product_pct"].source == "bioorch:crop-balance-coefficients@2026-10-11.1"
    assert b.dataset_version == "2026-10-11.1"


def test_n_minimum_falls_back_to_the_typical_n_and_says_so():
    b = build_crop("TRZAX", COEFF, {})
    assert b.params.n_min_product_pct == b.params.n_product_pct
    assert b.inputs["n_min_product_pct"].note == "n_min_fallback_typical"
    assert Notice("n_min_fallback_typical", {"eppo": "TRZAX"}) in b.notices


def test_an_entered_n_minimum_wins_and_drops_the_notice():
    b = build_crop("TRZAX", COEFF, _o("crop.n_min_product_pct", 1.9))
    assert b.params.n_min_product_pct == 1.9
    assert b.inputs["n_min_product_pct"].provenance == ENTERED
    assert not b.notices


def test_a_field_the_source_lacks_blocks_the_parameters():
    coeff = copy.deepcopy(COEFF)
    del coeff["values"]["balance_harvest_index_pct"]
    b = build_crop("TRZAX", coeff, {})
    assert b.params is None
    assert MissingInput("crop.harvest_index_pct", "bioorch", {"eppo": "TRZAX"}) in b.missing


def test_the_technician_fills_a_missing_field():
    coeff = copy.deepcopy(COEFF)
    del coeff["values"]["balance_harvest_index_pct"]
    b = build_crop("TRZAX", coeff, _o("crop.harvest_index_pct", 45.0))
    assert b.params.harvest_index_pct == 45.0
    assert b.inputs["harvest_index_pct"].provenance == ENTERED


def test_a_crop_bioorch_does_not_know():
    b = build_crop("ORYSA", None, {})
    assert b.params is None
    assert {"crop.dm_product_pct", "crop.crop_type", "crop.n_fixing"} <= {m.field for m in b.missing}


def test_no_crop_at_all():
    b = build_crop(None, None, {})
    assert b.params is None
    assert b.missing == (MissingInput("crop.eppo", "plan", {}),)


def test_an_out_of_range_table_value_is_reported_not_used():
    coeff = copy.deepcopy(COEFF)
    coeff["values"]["n_product_pct"]["value"] = 42.0
    b = build_crop("TRZAX", coeff, {})
    assert b.params is None
    assert any(m.field == "crop.coefficients" for m in b.missing)


def test_the_prefix_scopes_overrides():
    coeff = copy.deepcopy(COEFF)
    del coeff["values"]["balance_harvest_index_pct"]
    b = build_crop("TRZAX", coeff, _o("crop.harvest_index_pct", 45.0), prefix="previous_crop")
    assert b.params is None
    assert any(m.field == "previous_crop.harvest_index_pct" for m in b.missing)
