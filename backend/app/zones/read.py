"""Zonings of a parcel read from broker entities (AgriManagementZone).

Grouping into runs and the zone geometry come from the SDK (`nkz_platform_sdk.gis.zones`); the
attributes the SDK does not expose (area, mean vegetation value, variable) are read here with the
same tolerance: a term arrives plain, as `nkz:name` or as a full IRI, and a value arrives plain
(keyValues) or wrapped in {"type", "value"} (normalized).
"""
from __future__ import annotations

import math
from datetime import date as _date
from dataclasses import dataclass
from typing import Any

from nkz_platform_sdk.gis.zones import group_zonings

_PREFIXES = ("", "nkz:", "https://nkz-os.org/ns/", "https://uri.etsi.org/ngsi-ld/default-context/")
LEVELS = ("high", "medium", "low", "critical")
_LINKS = ("hasAgriParcel", "refAgriParcel")


@dataclass(frozen=True)
class ZoneRead:
    id: str
    label: str | None
    rank: int | None
    geometry: dict
    area_ha: float | None          # None: the entity carries no usable area
    mean_value: float | None       # None: no usable vegetation value (manual zonings never have)
    problems: tuple[str, ...]      # data defects: "area_ha", "mean_value_invalid"
    level: str | None = None       # zoneLevel: one of LEVELS, else None


@dataclass(frozen=True)
class ZoningRead:
    run_id: str
    method: str | None
    variable: str | None
    date: str | None               # YYYY-MM-DD
    zones: tuple[ZoneRead, ...]
    image_date: str | None = None  # newest of sourceDates, else `date`


def _unwrap(attr: Any) -> Any:
    if isinstance(attr, dict):
        if "object" in attr:
            return attr["object"]
        if "value" in attr:
            attr = attr["value"]
    if isinstance(attr, dict) and "@value" in attr:
        return attr["@value"]
    return attr


def attr(entity: dict, name: str) -> Any:
    for prefix in _PREFIXES:
        if prefix + name in entity:
            return _unwrap(entity[prefix + name])
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _zone(entity: dict, label: str | None, rank: int | None, geometry: dict) -> ZoneRead:
    problems: list[str] = []
    area = _finite(attr(entity, "areaHa"))
    if area is None or area <= 0:
        area = None
        problems.append("area_ha")
    raw = attr(entity, "meanValue")
    mean = _finite(raw)
    if raw is not None and (mean is None or mean <= 0):
        mean = None
        problems.append("mean_value_invalid")
    level = attr(entity, "zoneLevel")
    level = level if isinstance(level, str) and level in LEVELS else None
    return ZoneRead(str(entity.get("id", "")), label, rank, geometry, area, mean, tuple(problems),
                    level)


def _source_dates(entity: dict) -> list[str]:
    """ISO dates of `sourceDates`; a one-item list may arrive compacted as a plain value."""
    raw = attr(entity, "sourceDates")
    items = raw if isinstance(raw, list) else [] if raw is None else [raw]
    out = []
    for item in items:
        item = _unwrap(item)
        if not isinstance(item, str):
            continue
        try:
            out.append(_date.fromisoformat(item[:10]).isoformat())
        except ValueError:
            continue
    return out


def _linked_elsewhere(entity: dict, parcel_urn: str) -> bool:
    for name in _LINKS:
        link = attr(entity, name)
        if isinstance(link, str) and link != parcel_urn:
            return True
    return False


def zonings_of(entities: list[dict], parcel_urn: str) -> list[ZoningRead]:
    """Every zoning of the parcel, most recent first (an entity linked to another parcel is
    ignored, whatever the broker returned)."""
    mine = [e for e in entities if not _linked_elsewhere(e, parcel_urn)]
    by_id = {str(e.get("id", "")): e for e in mine}
    out = []
    for z in group_zonings(mine):
        entity_list = [by_id[ref.id] for ref in z.zones if ref.id in by_id]
        variable = next((v for e in entity_list
                         if isinstance(v := attr(e, "variableAttribute"), str)), None)
        # The image is as old as the zoning: the oldest `dateZoned` of the run. The SDK's run date
        # falls back to `modifiedAt`, which a later re-save moves forward.
        zoned = sorted(str(d)[:10] for e in entity_list if (d := attr(e, "dateZoned")))
        date = zoned[0] if zoned else None
        sources = [d for e in entity_list for d in _source_dates(e)]
        out.append(ZoningRead(z.run_id, z.method, variable, date,
                              tuple(_zone(by_id[ref.id], ref.label, ref.rank, ref.geometry)
                                    for ref in z.zones if ref.id in by_id),
                              max(sources) if sources else date))
    return out


def select_zoning(entities: list[dict], parcel_urn: str, run_id: str) -> ZoningRead | None:
    """The zoning with that run id, or None; never a fallback to another zoning."""
    return next((z for z in zonings_of(entities, parcel_urn) if z.run_id == run_id), None)
