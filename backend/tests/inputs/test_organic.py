import pytest

from app.engine import constants as C
from app.inputs.organic import OrganicApplication, organic_credit
from app.inputs.provenance import ENTERED, MissingInput, Override


def _o(param, value):
    return {param: Override(param, value, "own analysis", "u1", "2026-10-13T10:00:00Z")}


def test_cattle_manure_uses_the_mapa_default_and_says_where_it_comes_from():
    credit = organic_credit([OrganicApplication("cattle_manure", 20.0, 0.5, 0.2, 0.6)], {})
    assert credit.n_available_kg_ha == pytest.approx(100.0 * 0.25)
    a = credit.availability[0]
    assert a.provenance == "table:mapa_guia_2010" and "0.2-0.3" in a.note
    assert not credit.missing


def test_other_manures():
    credit = organic_credit([OrganicApplication("other_manure", 10.0, 1.4, 1.6, 0.9)], {})
    assert credit.n_available_kg_ha == pytest.approx(140.0 * 0.45)


def test_slurry_has_no_default_and_is_not_credited():
    credit = organic_credit([OrganicApplication("slurry", 30.0, 0.5, 0.2, 0.6)], {})
    assert credit.n_available_kg_ha == 0.0
    assert credit.missing == (MissingInput("organic.0.availability", "plan", {"material": "slurry"}),)


def test_the_user_sets_the_availability():
    credit = organic_credit([OrganicApplication("slurry", 30.0, 0.5, 0.2, 0.6)],
                            _o("organic.0.availability", 0.6))
    assert credit.n_available_kg_ha == pytest.approx(150.0 * 0.6)
    assert credit.availability[0].provenance == ENTERED and not credit.missing


def test_p_and_k_are_credited_in_full():
    credit = organic_credit([OrganicApplication("cattle_manure", 20.0, 0.5, 0.2, 0.6)], {})
    assert credit.p_kg_ha == pytest.approx(40.0 / C.P_TO_P2O5)
    assert credit.k_kg_ha == pytest.approx(120.0 / C.K_TO_K2O)


@pytest.mark.parametrize("args", [("guano", 1.0, 1.0, 1.0, 1.0), ("slurry", 0.0, 1.0, 1.0, 1.0),
                                  ("slurry", 1.0, 60.0, 30.0, 20.0),
                                  ("slurry", 1.0, -1.0, 0.0, 0.0)])
def test_invalid_applications(args):
    with pytest.raises(ValueError):
        OrganicApplication(*args)
