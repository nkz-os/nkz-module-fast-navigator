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


def _localised_doc():
    doc = document()
    doc["sheets"][0]["applications"][0]["method"] = "broadcast"
    doc["sheets"][0]["applications"][0]["stage"] = "pre_plant"
    return doc


def test_spanish_labels_and_no_raw_codes():
    html = plan_html(_localised_doc())
    for text in ("firmado", "a voleo", "medido", "fondo (presiembra)",
                 "Dosis y momento de aplicación ajustados"):
        assert text in html, text
    for raw in ("broadcast", "measured", "pre_plant"):
        assert raw not in html, raw


def test_english_labels():
    html = plan_html(_localised_doc(), "en")
    assert "signed" in html and "broadcast" in html and "measured" in html
    assert "dose and timing matched" in html


def test_label_fallbacks_and_tables():
    from app.report.i18n import label
    assert label("es", "provenance", "table:abc") == "tabla (abc)"
    assert label("es", "stage", "top dressing") == "top dressing"


def test_spanish_annex_v_has_the_same_keys():
    from app.plans.applications import ANNEX_V
    from app.report.i18n import ANNEX_V_ES
    assert set(ANNEX_V_ES) == set(ANNEX_V)


# ---- wave B: art. 6 completeness, no 500, page marks ----

def _organic_doc():
    doc = document()
    s = doc["sheets"][0]
    s["inputs"]["organic"] = [{"material": "cattle_manure", "rate_t_ha": 30, "n_pct": 0.6,
                               "p2o5_pct": 0.3, "k2o_pct": 0.7}]
    s["applications"].append({
        "stage": "pre_plant", "planned_date": "2026-10-01", "kind": "organic",
        "product_name": "Estiércol vacuno", "organic_index": 0, "product_rate_kg_ha": None,
        "n_pct": None, "p2o5_pct": None, "k2o_pct": None, "method": "incorporated",
        "machine": "esparcidor", "annex_v": ["A.i"], "other_measure": None})
    return doc


def test_organic_input_table_and_application_values():
    html = plan_html(_organic_doc())
    assert "cattle_manure" not in html and "estiércol vacuno" in html.lower()
    # kg/ha = 30 t/ha * 1000 * pct / 100
    for text in ("30 t/ha", "180", "90", "210"):
        assert text in html, text
    i = html.find("Estiércol vacuno")
    row = html[i:i + 600]
    assert "30 t/ha" in row and "180" in row and "210" in row


def test_water_nitrate_rain_and_soil_mineral_n():
    doc = _organic_doc()
    doc["rain"].update({"monthly_mm": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
                        "sources": ["aemet"], "notices": [{"code": "rain_normal_short_series",
                                                            "params": {"years": 7}}]})
    s = doc["sheets"][0]
    s["inputs"].update({"irrigated": True, "water_m3_ha": 4321, "no3_mg_l": 47})
    s["result"]["inputs"]["soil.mineral_n_kg_ha"] = {
        "value": 38.5, "provenance": "measured", "source": "soil:lab-analysis:nmin-77"}
    html = plan_html(doc)
    for text in ("4321", "47", "120", "38.5", "nmin-77", "medido", "serie corta"):
        assert text in html, text


def test_water_falls_back_to_result_inputs():
    doc = document()
    s = doc["sheets"][0]
    s["inputs"]["irrigated"] = True
    s["result"]["inputs"]["irrigation.water_m3_ha"] = {"value": 999, "provenance": "entered"}
    s["result"]["inputs"]["irrigation.no3_mg_l"] = {"value": 13, "provenance": "entered"}
    html = plan_html(doc)
    assert "999" in html and ">13<" in html.replace(" ", "")


def test_draft_with_nothing_calculated_renders():
    doc = {"plan": {"id": "x", "campaign": 2027, "farm": "f", "version": 1, "supersedes": None},
           "declarations": {}, "rain": None, "state": "draft", "live": True,
           "findings": [], "split_findings": [], "versions": None, "signature": None,
           "sheets": [{"key": "k", "inputs": {}, "parcels": [{"urn": "u", "sigpac": None}],
                       "applications": [], "result": None, "applications_summary": None,
                       "n_adjustment": None}]}
    assert plan_pdf(doc).startswith(b"%PDF")
    doc["sheets"] = []
    assert plan_pdf(doc, "en").startswith(b"%PDF")
    for k in ("rain", "declarations", "versions", "signature", "findings", "split_findings"):
        doc.pop(k)
    assert plan_pdf(doc).startswith(b"%PDF")


def test_null_n_and_organic_with_missing_input_render():
    doc = _organic_doc()
    doc["sheets"][0]["result"]["n"] = None
    doc["sheets"][0]["result"]["p2o5"] = None
    doc["sheets"][0]["inputs"]["organic"] = []      # application points at nothing
    assert plan_pdf(doc).startswith(b"%PDF")


def test_helpers_treat_undefined_as_missing():
    from jinja2 import Undefined

    from app.report.render import _kg, _num
    assert _num(Undefined()) == "—" and _num(None) == "—" and _num("x") == "—"
    assert _kg({"product_rate_kg_ha": Undefined(), "n_pct": 1}, "n_pct") is None


def test_draft_mark_on_every_page_margin_box():
    html = plan_html(document(state="calculated", live=True))
    assert "@top-center" in html and "BORRADOR" in html.split("</style>")[0]
    assert "@top-center" not in plan_html(document())
    assert "SUSTITUIDO" in plan_html(document(state="superseded")).split("</style>")[0]


def test_wrap_madrid_time_and_versions():
    doc = document()
    doc["signed_at"] = "2026-10-20T08:00:00+00:00"          # 10:00 in Madrid (CEST)
    doc["versions"]["coefficients"] = "coef-2026.1"
    doc["sheets"][0]["result"]["versions"] = {"coefficients": "coef-sheet-9",
                                              "previous_coefficients": None}
    html = plan_html(doc)
    assert "overflow-wrap: anywhere" in html
    assert "20/10/2026 10:00" in html
    assert "2026-10-20 10:00" in plan_html(doc, "en")
    assert "coef-2026.1" in html and "coef-sheet-9" in html


def test_long_strings_pdf_does_not_fail():
    doc = document()
    doc["sheets"][0]["parcels"][0]["urn"] = "urn:ngsi-ld:AgriParcel:" + "z" * 300
    assert plan_pdf(doc).startswith(b"%PDF")
