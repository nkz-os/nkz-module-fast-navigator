from app.inputs.crops import FALLOW, crops_for_campaign
from app.inputs.provenance import DECLARED, MEASURED, MissingInput, Notice


def cycle(species, label, start, end, role="main"):
    return {"crop_id": f"urn:ngsi-ld:AgriCrop:{species}{label}{start}", "role": role,
            "species": species, "start": {"date": start}, "end": {"date": end},
            "campaign_label": label}


CYCLES = [cycle("HELAN", 2026, "2026-04-10", "2026-09-20"),
          cycle("TRZAX", 2027, "2026-10-25", "2027-07-10"),
          cycle("PHSVX", 2026, "2026-06-01", "2026-08-01", role="cover")]


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
