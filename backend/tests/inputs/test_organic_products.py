import pytest

from app.inputs.organic import MATERIALS, OrganicApplication
from app.inputs.organic_products import ATTRIBUTION, load_products

LOCALES = {"es", "en", "eu", "fr", "ca", "pt"}


def test_there_are_eight_products_and_no_compost():
    products = load_products()
    assert len(products) == 8
    assert all(p["material"] != "compost" for p in products)
    assert len({p["id"] for p in products}) == 8


def test_every_product_is_complete():
    for p in load_products():
        assert p["material"] in MATERIALS
        assert set(p["names"]) == LOCALES and all(p["names"].values())
        assert p["source_ref"].startswith("MAPA 2010")
        assert p["basis"] in ("fresh", "not_stated")
        for k in ("n_pct", "p2o5_pct", "k2o_pct"):
            n = p[k]
            assert n["min"] <= n["value"] <= n["max"]
        # the suggestion must be accepted by the sheet as it stands
        OrganicApplication(p["material"], 1.0, p["n_pct"]["value"], p["p2o5_pct"]["value"],
                           p["k2o_pct"]["value"])


def test_ranges_keep_min_max_and_fill_the_midpoint():
    cattle = next(p for p in load_products() if p["id"] == "cattle_manure_table")
    assert cattle["n_pct"] == {"value": 0.45, "min": 0.3, "max": 0.6}
    assert cattle["source_ref"] == "MAPA 2010, ch. 6, p. 47, table 6.7"
    hen = next(p for p in load_products() if p["id"] == "hen_manure")
    assert hen["n_pct"] == {"value": 1.4, "min": 1.4, "max": 1.4} and hen["basis"] == "not_stated"
    lissier = next(p for p in load_products() if p["id"] == "lissier")
    assert lissier["material"] == "slurry"


def test_attribution_cites_the_guide_and_the_reuse_law():
    assert ATTRIBUTION["source_id"] == "mapa_guia_2010"
    assert "Ministerio de Agricultura" in ATTRIBUTION["text"] and "37/2007" in ATTRIBUTION["text"]


def test_composition_source_defaults_to_declared_and_rejects_unknown():
    assert OrganicApplication("slurry", 1, 0.5, 0.2, 0.6).composition_source == "declared"
    OrganicApplication("slurry", 1, 0.5, 0.2, 0.6, "table:mapa_guia_2010")
    with pytest.raises(ValueError):
        OrganicApplication("slurry", 1, 0.5, 0.2, 0.6, "made-up")
