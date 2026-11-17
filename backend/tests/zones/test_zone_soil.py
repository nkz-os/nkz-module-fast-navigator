from app.zones.read import ZoneRead, ZoningRead
from app.zones.soil import ZoneSoil, assign_analyses, zone_soil

RUN = "run-a"
ZA = "urn:ngsi-ld:AgriManagementZone:parcel-1:Z0"
ZB = "urn:ngsi-ld:AgriManagementZone:parcel-1:Z1"


def sq(x0, x1):
    return {"type": "Polygon", "coordinates": [[[x0, 0], [x1, 0], [x1, 1], [x0, 1], [x0, 0]]]}


def zoning():
    zones = (ZoneRead(ZA, "A", 0, sq(0, 1), 1.0, 0.5, ()),
             ZoneRead(ZB, "B", 1, sq(1, 2), 1.0, 0.4, ()))
    return ZoningRead(RUN, "vegetationIndex", "NDVI", "2026-10-01", zones)


def an(i, date="2026-03-01", lon=None, lat=0.5, link=None, **hz):
    a = {"id": f"urn:lab:{i}", "samplingDate": date, "linkedBy": "parcel",
         "location": {"lat": lat, "lon": lon} if lon is not None else None,
         "horizons": [dict({"depthFrom": 0, "depthTo": 30}, **hz)]}
    if link is not None:
        a["hasAgriManagementZone"] = link
    return a


def test_assign_explicit_link_wins_over_location():
    a = an(1, lon=0.5, link=ZB)
    by, out = assign_analyses([a], zoning())
    assert by == {ZB: [a]} and out == []


def test_assign_link_wrapped_object():
    a = an(1, link={"object": ZB})
    assert assign_analyses([a], zoning())[0] == {ZB: [a]}


def test_assign_link_of_other_zoning_ignored_falls_back_to_location():
    a = an(1, lon=0.5, link="urn:ngsi-ld:AgriManagementZone:parcel-1:other")
    assert assign_analyses([a], zoning())[0] == {ZA: [a]}


def test_assign_link_of_other_zoning_without_location_is_outside():
    a = an(1, link="urn:ngsi-ld:AgriManagementZone:parcel-1:other")
    assert assign_analyses([a], zoning()) == ({}, [a])


def test_assign_by_location():
    a, b = an(1, lon=0.5), an(2, lon=1.5)
    by, out = assign_analyses([a, b], zoning())
    assert by == {ZA: [a], ZB: [b]} and out == []


def test_assign_border_lowest_rank_wins():
    a = an(1, lon=1.0)
    assert assign_analyses([a], zoning())[0] == {ZA: [a]}


def test_assign_outside_and_no_location():
    far, none = an(1, lon=5.0), an(2)
    assert assign_analyses([far, none], zoning()) == ({}, [far, none])


def p_k(**kw):
    return dict({"phosphorusAvailable": 10.0, "phosphorusMethod": "olsen",
                 "potassiumExchangeable": 100.0, "potassiumMethod": "ammonium_acetate"}, **kw)


def codes(z):
    return [n["code"] for n in z.notices]


def test_same_date_mean_and_aggregated_notice():
    a = an(1, **p_k())
    b = an(2, **p_k(phosphorusAvailable=20.0, potassiumExchangeable=200.0))
    z = zone_soil(ZA, [a, b], nmin_date=None, class_bd=None)
    assert isinstance(z, ZoneSoil) and z.zone_id == ZA
    assert z.p_olsen_mg_kg == 15.0 and z.k_mg_kg == 150.0
    assert z.n_samples == 2 and set(z.analysis_ids) == {"urn:lab:1", "urn:lab:2"}
    assert z.date == "2026-03-01"
    assert {"code": "zone_soil_aggregated", "params": {"zone": ZA, "n": 2}} in z.notices


def test_newest_date_wins():
    old = an(1, date="2025-03-01", **p_k(phosphorusAvailable=50.0))
    new = an(2, date="2026-03-01", **p_k(phosphorusAvailable=12.0))
    z = zone_soil(ZA, [old, new], nmin_date=None, class_bd=None)
    assert z.p_olsen_mg_kg == 12.0 and z.analysis_ids == ("urn:lab:2",) and z.date == "2026-03-01"
    assert "zone_soil_aggregated" not in codes(z)


def nmin(i, date, **kw):
    return an(i, date=date, **dict({"nitrateN": 10.0, "ammoniumN": 2.0, "bulkDensity": 1.3}, **kw))


def test_nmin_only_from_nmin_date():
    a, b = nmin(1, "2026-02-01"), nmin(2, "2026-03-01", nitrateN=30.0)
    z = zone_soil(ZA, [a, b], nmin_date="2026-02-01", class_bd=None)
    # 12 mg/kg x 1.3 x 30 cm x 0.1 x 0.9 (engine efficiency) = 42.12
    assert abs(z.nmin_kg_ha - 42.12) < 0.01 and z.nmin_date == "2026-02-01"


def test_nmin_mean_of_same_date():
    a, b = nmin(1, "2026-02-01"), nmin(2, "2026-02-01", nitrateN=20.0)
    z = zone_soil(ZA, [a, b], nmin_date="2026-02-01", class_bd=None)
    assert abs(z.nmin_kg_ha - (42.12 + 77.22) / 2) < 0.01


def test_no_nmin_date_gives_none():
    z = zone_soil(ZA, [nmin(1, "2026-02-01")], nmin_date=None, class_bd=None)
    assert z.nmin_kg_ha is None and z.nmin_date is None
    assert "zone_nmin_incomplete" not in codes(z)


def test_nmin_other_date_notice():
    z = zone_soil(ZA, [nmin(1, "2026-03-01")], nmin_date="2026-02-01", class_bd=None)
    assert z.nmin_kg_ha is None
    assert {"code": "zone_nmin_other_date", "params": {"zone": ZA, "date": "2026-03-01"}} in z.notices


def test_nmin_without_bulk_density_is_none_and_incomplete():
    a = nmin(1, "2026-02-01")
    del a["horizons"][0]["bulkDensity"]
    z = zone_soil(ZA, [a], nmin_date="2026-02-01", class_bd=None)
    assert z.nmin_kg_ha is None
    assert {"code": "zone_nmin_incomplete", "params": {"zone": ZA, "analyses": ["urn:lab:1"]}} in z.notices


def test_nmin_class_bd_fallback():
    a = nmin(1, "2026-02-01")
    del a["horizons"][0]["bulkDensity"]
    z = zone_soil(ZA, [a], nmin_date="2026-02-01", class_bd=1.3)
    assert abs(z.nmin_kg_ha - 42.12) < 0.01


def test_p_bray_converted_to_olsen():
    from app.engine.texture import olsen_equivalent
    z = zone_soil(ZA, [an(1, **p_k(phosphorusAvailable=20.0, phosphorusMethod="bray1"))],
                  nmin_date=None, class_bd=None)
    assert z.p_olsen_mg_kg == olsen_equivalent(20.0, "bray1")


def test_k_unsupported_method_is_none():
    z = zone_soil(ZA, [an(1, **p_k(potassiumMethod="mehlich3"))], nmin_date=None, class_bd=None)
    assert z.k_mg_kg is None and z.p_olsen_mg_kg == 10.0


def test_mixed_pk_dates_are_traced():
    p_only = an(1, date="2025-03-01", phosphorusAvailable=12.0, phosphorusMethod="olsen")
    k_only = an(2, date="2026-03-01", potassiumExchangeable=150.0, potassiumMethod="ammonium_acetate")
    z = zone_soil(ZA, [p_only, k_only], nmin_date=None, class_bd=None)
    assert (z.p_date, z.k_date, z.date) == ("2025-03-01", "2026-03-01", "2026-03-01")
    assert {"code": "zone_soil_mixed_dates",
            "params": {"zone": ZA, "p_date": "2025-03-01", "k_date": "2026-03-01"}} in z.notices


def test_same_dates_no_mixed_notice():
    z = zone_soil(ZA, [an(1, **p_k())], nmin_date=None, class_bd=None)
    assert (z.p_date, z.k_date) == ("2026-03-01", "2026-03-01")
    assert "zone_soil_mixed_dates" not in codes(z)


def test_undated_analysis_is_dropped():
    a = an(1, **p_k())
    a["samplingDate"] = None
    z = zone_soil(ZA, [a], nmin_date=None, class_bd=None)
    assert z.p_olsen_mg_kg is None and z.analysis_ids == () and z.date is None


def test_timestamp_date_matches_nmin_date():
    z = zone_soil(ZA, [nmin(1, "2026-02-01T00:00:00Z")], nmin_date="2026-02-01", class_bd=None)
    assert abs(z.nmin_kg_ha - 42.12) < 0.01


def test_incomplete_names_the_analysis():
    a = nmin(1, "2026-02-01")
    del a["horizons"][0]["bulkDensity"]
    z = zone_soil(ZA, [a], nmin_date="2026-02-01", class_bd=None)
    assert {"code": "zone_nmin_incomplete",
            "params": {"zone": ZA, "analyses": ["urn:lab:1"]}} in z.notices


def test_assign_link_bare_string_and_object_agree():
    a, b = an(1, link=ZB), an(2, link={"object": ZB})
    assert assign_analyses([a, b], zoning())[0] == {ZB: [a, b]}


def n_an(i, bottoms, date="2026-03-01", **kw):
    top, hzs = 0, []
    for b in bottoms:
        hzs.append({"depthFrom": top, "depthTo": b, "nitrateN": 5.0, "ammoniumN": 5.0,
                    "bulkDensity": 1.0})
        top = b
    return {"id": f"urn:lab:{i}", "samplingDate": date, "horizons": hzs, **kw}


def test_nmin_is_only_averaged_over_the_parcels_depth():
    shallow, deep = n_an(1, [30]), n_an(2, [30, 90])
    zs = zone_soil(ZA, [shallow, deep], nmin_date="2026-03-01", class_bd=1.3,
                   nmin_depth=(0, 30))
    assert zs.nmin_kg_ha == 27.0 and zs.nmin_ids == ("urn:lab:1",)
    assert {"code": "zone_nmin_depth_differs", "params": {"zone": ZA}} in zs.notices
    none = zone_soil(ZA, [deep], nmin_date="2026-03-01", class_bd=1.3, nmin_depth=(0, 30))
    assert none.nmin_kg_ha is None


def test_negative_nitrate_is_incomplete_not_an_error():
    bad = n_an(1, [30])
    bad["horizons"][0]["nitrateN"] = -1.0
    zs = zone_soil(ZA, [bad], nmin_date="2026-03-01", class_bd=1.3, nmin_depth=(0, 30))
    assert zs.nmin_kg_ha is None and zs.notices[0]["code"] == "zone_nmin_incomplete"


def test_analysis_depth_of_non_contiguous_layers_is_none():
    from app.inputs.soil import analysis_n_depth
    a = n_an(1, [30])
    a["horizons"].append({"depthFrom": 60, "depthTo": 90, "nitrateN": 1.0})
    assert analysis_n_depth(a) is None and analysis_n_depth(n_an(2, [30, 90])) == (0, 90)


def test_an_n_only_sample_is_not_unusable_when_nmin_was_not_evaluated():
    a = n_an(1, [30])
    zs = zone_soil(ZA, [a], nmin_date=None, class_bd=1.3, nmin_considered=False)
    assert not any(n["code"] == "zone_soil_unusable" for n in zs.notices)
    p_only = an(2, lon=0.5, phosphorusAvailable=5.0, phosphorusMethod="unknown")
    zs = zone_soil(ZA, [a, p_only], nmin_date=None, class_bd=1.3, nmin_considered=False)
    assert [n for n in zs.notices if n["code"] == "zone_soil_unusable"] == [
        {"code": "zone_soil_unusable", "params": {"zone": ZA, "analyses": ["urn:lab:2"]}}]


def test_unusable_is_not_added_to_a_specific_nmin_notice():
    zs = zone_soil(ZA, [n_an(1, [30, 90])], nmin_date="2026-03-01", class_bd=1.3,
                   nmin_depth=(0, 30))
    assert [n["code"] for n in zs.notices] == ["zone_nmin_depth_differs"]
