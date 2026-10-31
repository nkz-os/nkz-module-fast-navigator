from app.inputs.crops import FALLOW, crops_for_campaign
from app.inputs.provenance import DECLARED, MEASURED, MissingInput, Notice


def cycle(species, label, start, end, role="main_crop"):
    return {"crop_id": f"urn:ngsi-ld:AgriCrop:{species}{label}{start}", "role": role,
            "species": species, "start": {"date": start}, "end": {"date": end},
            "campaign_label": label}


CYCLES = [cycle("HELAN", 2026, "2026-04-10", "2026-09-20"),
          cycle("TRZAX", 2027, "2026-10-25", "2027-07-10"),
          cycle("PHSVX", 2026, "2026-06-01", "2026-08-01", role="cover_crop")]


def test_crop_and_preceding_crop_from_the_cycles():
    c = crops_for_campaign(CYCLES, 2027)
    assert c.crop.value == "TRZAX" and c.crop.provenance == MEASURED
    assert c.previous.value == "HELAN" and c.previous_campaign == 2026
    assert not c.missing and not c.notices


def test_double_crop_second_cycle_follows_the_first():
    cycles = CYCLES + [cycle("ZEAMX", 2027, "2027-07-20", "2027-10-30")]
    c = crops_for_campaign(cycles, 2027, cycle_index=1)
    assert c.crop.value == "ZEAMX" and c.previous.value == "TRZAX"
    assert Notice("double_crop_campaign", {"campaign": 2027, "count": 2}) in c.notices


def test_a_declared_crop_wins_and_a_difference_is_flagged():
    c = crops_for_campaign(CYCLES, 2027, declared_crop="HORVX")
    assert c.crop.value == "HORVX" and c.crop.provenance == DECLARED
    assert Notice("crop_differs_from_cycle", {"declared": "HORVX", "cycle": "TRZAX"}) in c.notices


def test_declared_fallow():
    c = crops_for_campaign(CYCLES, 2027, declared_previous=FALLOW)
    assert c.previous.value == FALLOW and c.previous.provenance == DECLARED


def test_no_cycles_and_nothing_declared():
    c = crops_for_campaign([], 2027)
    assert MissingInput("crop", "plan", {"campaign": 2027}) in c.missing
    assert MissingInput("previous_crop", "plan", {"campaign": 2027}) in c.missing


def test_declared_crop_without_a_cycle_takes_the_last_earlier_campaign():
    c = crops_for_campaign(CYCLES[:1], 2027, declared_crop="TRZAX")
    assert c.previous.value == "HELAN" and c.previous_campaign == 2026


def test_declared_previous_crop_is_from_the_campaign_before():
    c = crops_for_campaign([], 2027, declared_crop="TRZAX", declared_previous="HELAN")
    assert c.previous.value == "HELAN" and c.previous_campaign == 2026


def _sdk_cycles(parcel="urn:ngsi-ld:AgriParcel:p1"):
    from datetime import date

    from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
    crops = [
        {"id": "urn:ngsi-ld:AgriCrop:w", "hasAgriParcel": parcel, "species": "TRZAX",
         "status": "harvested", "plantingDate": "2025-10-25", "harvestDate": "2026-07-10"},
        {"id": "urn:ngsi-ld:AgriCrop:b", "hasAgriParcel": parcel, "species": "HORVX",
         "status": "harvested", "plantingDate": "2026-10-25", "harvestDate": "2027-07-10"},
        {"id": "urn:ngsi-ld:AgriCrop:cc", "hasAgriParcel": parcel, "species": "PHSVX",
         "cropRole": "cover_crop", "status": "harvested", "plantingDate": "2026-08-20",
         "harvestDate": "2026-10-15"},
    ]
    operations = [
        {"id": "urn:ngsi-ld:AgriParcelOperation:s1", "hasAgriParcel": parcel,
         "operationType": "sowing", "status": "completed", "startedAt": "2025-10-25T08:00:00Z"},
        {"id": "urn:ngsi-ld:AgriParcelOperation:h1", "hasAgriParcel": parcel,
         "operationType": "harvesting", "status": "completed", "startedAt": "2026-07-10T08:00:00Z",
         "endedAt": "2026-07-10T12:00:00Z"},
    ]
    return resolve_crop_cycles(parcel, crops, operations, date(2027, 9, 1)).to_dict()["cycles"]


def test_reads_the_cycles_the_platform_sdk_emits():
    cycles = _sdk_cycles()
    assert {c["role"] for c in cycles} == {"main_crop", "cover_crop"}
    c = crops_for_campaign(cycles, 2027)
    assert c.crop.value == "HORVX" and c.crop.provenance == MEASURED
    assert c.previous.value == "TRZAX" and c.previous_campaign == 2026


def test_a_cycle_without_role_is_a_main_crop_and_a_cover_crop_is_not():
    from app.inputs.crops import is_main
    assert is_main({}) and is_main({"role": None}) and is_main({"role": "main_crop"})
    assert not is_main({"role": "cover_crop"})


def test_second_crop_declared_but_not_recorded_follows_the_first_of_the_campaign():
    cycles = [cycle("TRZAX", 2026, "2025-10-25", "2026-07-10"),
              cycle("HORVX", 2027, "2026-10-25", "2027-06-20")]
    c = crops_for_campaign(cycles, 2027, cycle_index=1, declared_crop="ZEAMX")
    assert c.crop.value == "ZEAMX"
    assert c.previous.value == "HORVX" and c.previous_campaign == 2027
    assert not any(m.field == "previous_crop" for m in c.missing)


def test_second_crop_with_no_first_cycle_recorded_is_flagged():
    cycles = [cycle("TRZAX", 2026, "2025-10-25", "2026-07-10")]
    c = crops_for_campaign(cycles, 2027, cycle_index=1, declared_crop="ZEAMX")
    assert not c.previous.known
    assert MissingInput("previous_crop", "plan", {"campaign": 2027}) in c.missing
    assert Notice("double_crop_first_cycle_unknown", {"campaign": 2027}) in c.notices


def test_a_cycle_species_that_is_not_an_eppo_code_is_flagged():
    cycles = [cycle("wheat", 2026, "2025-10-25", "2026-07-10"),
              cycle("barley", 2027, "2026-10-25", "2027-07-10")]
    c = crops_for_campaign(cycles, 2027)
    assert not c.crop.known and not c.previous.known
    assert Notice("cycle_species_not_eppo", {"species": "barley",
                                             "crop_id": cycles[1]["crop_id"]}) in c.notices
    assert Notice("cycle_species_not_eppo", {"species": "wheat",
                                             "crop_id": cycles[0]["crop_id"]}) in c.notices


def test_a_declared_crop_does_not_flag_the_cycle_species():
    cycles = [cycle("barley", 2027, "2026-10-25", "2027-07-10")]
    c = crops_for_campaign(cycles, 2027, declared_crop="HORVX", declared_previous="fallow")
    assert not any(n.code == "cycle_species_not_eppo" for n in c.notices)


def _pending(c):
    return {**c, "pending": True}


def test_a_pending_immediately_preceding_cycle_is_no_previous_crop_even_with_an_older_confirmed_one():
    older = cycle("HELAN", 2025, "2025-04-10", "2025-09-20")
    pending_prev = _pending(cycle("TRZAX", 2026, "2026-04-10", "2026-09-20"))
    cycles = [older, pending_prev, cycle("ZEAMX", 2027, "2026-10-25", "2027-07-10")]
    c = crops_for_campaign(cycles, 2027)
    assert not c.previous.known and c.previous_campaign is None
    assert MissingInput("previous_crop", "plan", {"campaign": 2027}) in c.missing
    assert Notice("previous_cycle_pending",
                  {"crop_id": pending_prev["crop_id"], "campaign": 2026}) in c.notices


def test_a_pending_cycle_that_is_not_the_immediately_preceding_one_is_irrelevant():
    older_pending = _pending(cycle("TRZAX", 2024, "2024-04-10", "2024-09-20"))
    confirmed_prev = cycle("HELAN", 2026, "2026-04-10", "2026-09-20")
    cycles = [older_pending, confirmed_prev, cycle("ZEAMX", 2027, "2026-10-25", "2027-07-10")]
    c = crops_for_campaign(cycles, 2027)
    assert c.previous.value == "HELAN" and c.previous_campaign == 2026
    assert not c.missing and not c.notices


def test_second_crop_after_a_pending_first_cycle_has_no_previous_crop():
    pending_first = _pending(cycle("TRZAX", 2027, "2026-10-25", "2027-06-20"))
    cycles = [pending_first, cycle("HORVX", 2027, "2027-07-01", "2027-10-30")]
    c = crops_for_campaign(cycles, 2027, cycle_index=1)
    assert not c.previous.known
    assert MissingInput("previous_crop", "plan", {"campaign": 2027}) in c.missing
    assert Notice("previous_cycle_pending",
                  {"crop_id": pending_first["crop_id"], "campaign": 2027}) in c.notices


def test_the_plan_campaigns_own_pending_cycles_are_still_the_plan_crops():
    previous = cycle("HELAN", 2026, "2026-04-10", "2026-09-20")
    own = _pending(cycle("TRZAX", 2027, "2026-10-25", "2027-07-10"))
    c = crops_for_campaign([previous, own], 2027)
    assert c.crop.value == "TRZAX" and c.crop.provenance == MEASURED
    assert c.previous.value == "HELAN" and c.previous_campaign == 2026
    assert not c.missing and not c.notices

    first = cycle("TRZAX", 2027, "2026-10-25", "2027-06-20")
    second = _pending(cycle("HORVX", 2027, "2027-07-01", "2027-10-30"))
    c = crops_for_campaign([first, second], 2027, cycle_index=1)
    assert c.crop.value == "HORVX" and c.previous.value == "TRZAX"
    assert not c.missing and not any(n.code == "previous_cycle_pending" for n in c.notices)


def test_cycle_view_of_a_planned_cycle():
    from datetime import date

    from nkz_platform_sdk.crop_cycles import resolve_crop_cycles

    from app.inputs.crops import campaign_main_cycles, cycle_view
    parcel = "urn:ngsi-ld:AgriParcel:p1"
    crops = [{"id": "urn:ngsi-ld:AgriCrop:x", "hasAgriParcel": parcel, "species": "TRZAX",
              "status": "planned", "plantingDate": "2026-10-25"}]
    cycles = resolve_crop_cycles(parcel, crops, [], date(2026, 10, 1)).to_dict()["cycles"]
    assert cycle_view(campaign_main_cycles(cycles, 2027)[0]) == {
        "crop_id": "urn:ngsi-ld:AgriCrop:x",
        "start": {"date": "2026-10-25", "provenance": "planned"},
        "pending": False, "status": "planned"}


def test_cycle_view_of_none_is_none():
    from app.inputs.crops import cycle_view
    assert cycle_view(None) is None
