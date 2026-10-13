import pytest

from app.report.render import plan_html, plan_pdf

P1 = "urn:ngsi-ld:AgriParcel:p1"


def document(state="signed", live=False):
    return {
        "plan": {"id": "11111111-1111-1111-1111-111111111111", "campaign": 2027,
                 "farm": "tenant", "version": 2, "supersedes": None},
        "state": state, "live": live, "signed_at": "2026-10-20T08:00:00+00:00",
        "snapshot_sha256": "ab" * 32, "judged_at": "2026-10-20",
        "declarations": {"vulnerable_zone": True, "vulnerable_zone_source": None,
                         "voluntary_digital_notebook": False, "irrigated_spring_2026": None},
        "rain": {"annual_mm": 612.4, "years": [2016, 2025]},
        "signature": {"kind": "advisor", "name": "Ana Example", "registration_number": "XX-1",
                      "signed_at": "2026-10-20T08:00:00+00:00"},
        "versions": {"engine": "1.0.0", "calc": "1.0.0", "rules": "es-2026.10.4",
                     "organic_table": "mapa-2010-ch6-p47"},
        "findings": [{"rule_id": "ES-NA-not-checked", "severity": "info",
                      "citation": "Navarra: …", "params": {}, "sheet_key": None}],
        "sheets": [{
            "key": "wheat", "inputs": {"irrigated": False, "strategy": 2, "organic": []},
            "parcels": [{"urn": P1, "sigpac": "31:201:0:0:1:123:1"}],
            "applications": [{"stage": "pre_plant", "planned_date": "2026-10-25",
                              "kind": "mineral", "product_name": "NPK 8-15-15", "n_pct": 8,
                              "p2o5_pct": 15, "k2o_pct": 15, "product_rate_kg_ha": 300,
                              "method": "broadcast", "machine": "spreader",
                              "annex_v": ["B.a"], "other_measure": None}],
            "result": {"status": "complete",
                       "n": {"min_kg_ha": 100.0, "avg_kg_ha": 130.0, "max_kg_ha": 160.0},
                       "p2o5": {"rate_kg_ha": 45.0}, "k2o": {"rate_kg_ha": 30.0},
                       "inputs": {"crop.eppo": {"value": "TRZAX", "provenance": "declared"},
                                  "previous_crop.eppo": {"value": "HORVX",
                                                         "provenance": "measured"},
                                  "yield.kg_ha": {"value": 5600.0, "provenance": "declared"},
                                  f"parcel.{P1}.area_ha": {"value": 12.5},
                                  "soil.analysis_id": {"value": "a1",
                                                       "sampling_date": "2026-09-01"},
                                  "soil.ph": {"value": 7.8, "provenance": "measured"},
                                  "soil.organic_matter_pct": {"value": 1.9,
                                                              "provenance": "measured"},
                                  "soil.p_olsen_mg_kg": {"value": 14.0, "provenance": "measured"},
                                  "soil.k_mg_kg": {"value": 180.0, "provenance": "measured"}}},
            "applications_summary": {"mineral_n_kg_ha": 24.0, "p2o5_kg_ha": 45.0,
                                     "k2o_kg_ha": 45.0},
            "n_adjustment": None}],
    }


def test_html_has_the_article_6_content():
    html = plan_html(document())
    for text in ("31:201:0:0:1:123:1", "12.5", "TRZAX", "HORVX", "5600", "7.8", "1.9",
                 "612", "NPK 8-15-15", "300", "B.a", "130", "45", "Ana Example", "XX-1",
                 "ab" * 32, "es-2026.10.4", "ES-NA-not-checked", "2026-10-25"):
        assert text in html, text
    assert "BORRADOR" not in html


def test_drafts_and_superseded_are_marked():
    assert "BORRADOR" in plan_html(document(state="calculated", live=True))
    assert "SUSTITUIDO" in plan_html(document(state="superseded"))


def test_english_and_escaping():
    doc = document()
    doc["sheets"][0]["applications"][0]["product_name"] = "<script>x</script>"
    html = plan_html(doc, "en")
    assert "Fertilisation plan" in html and "<script>x</script>" not in html


def test_unknown_language_is_refused():
    with pytest.raises(ValueError):
        plan_html(document(), "fr")


def test_pdf_bytes():
    pdf = plan_pdf(document())
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
