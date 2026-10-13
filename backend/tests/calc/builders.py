"""A complete sheet (wheat after wheat, rainfed, strategy 2) built from the real input builders."""
from dataclasses import replace
from datetime import date

from app.calc.sheet import AssembledInputs
from app.engine.types import Management
from app.inputs.crop import build_crop
from app.inputs.crops import crops_for_campaign
from app.inputs.irrigation import irrigation_credit
from app.inputs.organic import organic_credit
from app.inputs.parcel import parcel_info
from app.inputs.provenance import DECLARED, Sourced, missing
from app.inputs.soil import build_soil
from app.inputs.yield_target import resolve_yield
from tests.conftest import load_contract

COEFF = load_contract("bioorch_coefficients_trzax.json")
H = {"depthFrom": 0, "depthTo": 30, "sand": 40.0, "clay": 25.0, "ph": 7.8,
     "organicMatter": 1.9, "phosphorusAvailable": 14.0, "phosphorusMethod": "olsen",
     "potassiumExchangeable": 220.0, "potassiumMethod": "ammonium_acetate"}
CYCLES = [{"crop_id": "c1", "role": "main_crop", "species": "TRZAX", "start": {"date": "2025-10-25"},
           "end": {"date": "2026-07-10"}, "campaign_label": 2026},
          {"crop_id": "c2", "role": "main_crop", "species": "TRZAX", "start": {"date": "2026-10-25"},
           "end": {"date": "2027-07-10"}, "campaign_label": 2027}]
DECLARED_YIELDS = {2022: 5200.0, 2023: 6100.0, 2024: 5600.0, 2025: 5900.0, 2026: 5400.0}


def assembled(**changes) -> AssembledInputs:
    today = date(2026, 10, 13)
    base = AssembledInputs(
        campaign=2027,
        management=Management(strategy=2, tillage=True, irrigated=False),
        previous_residues_burned=False,
        rotation_years=4,
        choice=crops_for_campaign(CYCLES, 2027),
        crop=build_crop("TRZAX", COEFF, {}),
        previous_crop=build_crop("TRZAX", COEFF, {}, prefix="previous_crop"),
        yield_target=resolve_yield(2027, {}, DECLARED_YIELDS, None, {}, today),
        previous_yield=resolve_yield(2026, {}, DECLARED_YIELDS, None, {}, today,
                                     prefix="previous_yield"),
        soil=build_soil([{"id": "a1", "samplingDate": "2026-09-01", "horizons": [H]}], [],
                        None, None, {}),
        organic=organic_credit([], {}),
        irrigation=irrigation_credit(False, None, missing(), {}),
        region=Sourced("ES22", DECLARED, "plan"),
        parcels=(parcel_info({"id": "urn:ngsi-ld:AgriParcel:p1", "area": 10.0}),),
    )
    return replace(base, **changes)
