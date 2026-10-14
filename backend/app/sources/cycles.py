"""Crop cycles of a parcel: the platform rule (SDK ``crop_cycles``) over the broker (spec §4).

The SDK reads the parcel, its crops and the operations that set cycle boundaries and
resolves the cycles here, so no core service sits in between.
"""
from __future__ import annotations

import logging
from datetime import date

from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import CropDataUnavailable, ParcelNotFound, load_crop_data

from .errors import SourceUnavailable

logger = logging.getLogger(__name__)

SOURCE = "broker:crop-cycles"


async def fetch_timeline(orion, parcel_urn: str, at: date) -> dict | None:
    """The parcel's crop-cycle timeline at ``at``; None for a parcel the broker does not know."""
    try:
        _parcel, crops, ops = await load_crop_data(orion, parcel_urn)
    except ParcelNotFound:
        return None
    except CropDataUnavailable as exc:
        logger.warning("crop cycles unreadable parcel=%s: %s", parcel_urn, exc)
        raise SourceUnavailable(SOURCE, f"broker read failed ({type(exc).__name__})") from exc
    return resolve_crop_cycles(parcel_urn, crops, ops, at).to_dict()
