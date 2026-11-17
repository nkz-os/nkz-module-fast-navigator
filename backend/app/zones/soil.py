"""Soil analyses of a parcel assigned to the zones of one zoning, and aggregated per zone.

Pure: no I/O. An analysis belongs to a zone by its explicit link (`hasAgriManagementZone`, when it
names a zone of THIS zoning), else by where it was sampled, else it is outside every zone.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from nkz_platform_sdk.gis.zones import zone_of

from app.inputs.soil import analysis_k, analysis_mineral_n, analysis_p_olsen

from .read import ZoningRead, attr


@dataclass(frozen=True)
class ZoneSoil:
    zone_id: str
    analysis_ids: tuple[str, ...]      # analyses behind P/K
    date: str | None                   # sampling date of the P/K analyses (newest used)
    n_samples: int                     # analyses averaged for P/K
    nmin_kg_ha: float | None
    nmin_date: str | None
    p_olsen_mg_kg: float | None
    k_mg_kg: float | None
    notices: tuple[dict, ...]


def _notice(code: str, **params) -> dict:
    return {"code": code, "params": params}


def _linked_zone(analysis: dict, zone_ids: set[str]) -> str | None:
    link = attr(analysis, "hasAgriManagementZone")
    return link if isinstance(link, str) and link in zone_ids else None


def assign_analyses(analyses: list[dict], zoning: ZoningRead
                    ) -> tuple[dict[str, list[dict]], list[dict]]:
    """(analyses by zone id, analyses outside every zone). Link > sampling location > outside."""
    zone_ids = {z.id for z in zoning.zones}
    by_zone: dict[str, list[dict]] = {}
    outside: list[dict] = []
    for a in analyses:
        zone_id = _linked_zone(a, zone_ids)
        if zone_id is None:
            loc = a.get("location") or {}
            lon, lat = loc.get("lon"), loc.get("lat")
            # ASSUMPTION: ZoningRead has the same .zones/.id/.rank/.geometry as the SDK Zoning
            # that zone_of expects (it only reads those), so it is passed as is.
            hit = zone_of(lon, lat, zoning) if _is_num(lon) and _is_num(lat) else None
            zone_id = hit.id if hit is not None else None
        if zone_id is None:
            outside.append(a)
        else:
            by_zone.setdefault(zone_id, []).append(a)
    return by_zone, outside


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _newest_mean(analyses: list[dict], read) -> tuple[float | None, list[dict]]:
    """Mean of `read` over the analyses of the newest date that have a value."""
    valued = [(a, v) for a in analyses if (v := read(a)) is not None and a.get("samplingDate")]
    if not valued:
        return None, []
    newest = max(a["samplingDate"] for a, _ in valued)
    used = [(a, v) for a, v in valued if a["samplingDate"] == newest]
    return fmean(v for _, v in used), [a for a, _ in used]


def _has_nmin(a: dict) -> bool:
    return any(h.get("nitrateN") is not None or h.get("ammoniumN") is not None
               for h in a.get("horizons") or [])


def zone_soil(zone_id: str, analyses: list[dict], *, nmin_date: str | None,
              class_bd: float | None) -> ZoneSoil:
    notices: list[dict] = []
    p, p_used = _newest_mean(analyses, analysis_p_olsen)
    k, k_used = _newest_mean(analyses, analysis_k)
    used: list[dict] = []
    for a in p_used + k_used:
        if a not in used:
            used.append(a)
    # P and K may come from different dates if the newest analysis lacks one of them.
    dates = {a["samplingDate"] for a in used}
    date = max(dates) if dates else None
    n_samples = max(len(p_used), len(k_used))
    if n_samples > 1:
        notices.append(_notice("zone_soil_aggregated", zone=zone_id, n=n_samples))

    nmin_value: float | None = None
    used_nmin_date: str | None = None
    if nmin_date:
        on_date = [a for a in analyses if a.get("samplingDate") == nmin_date and _has_nmin(a)]
        if on_date:
            values = [analysis_mineral_n(a, class_bd) for a in on_date]
            if any(v is None for v in values):
                # Crediting a partial mean would understate N: leave it blank and say so.
                notices.append(_notice("zone_nmin_incomplete", zone=zone_id))
            else:
                nmin_value, used_nmin_date = fmean(values), nmin_date
        else:
            other = sorted({a["samplingDate"] for a in analyses
                            if _has_nmin(a) and a.get("samplingDate")})
            if other:
                notices.append(_notice("zone_nmin_other_date", zone=zone_id, date=other[-1]))

    return ZoneSoil(zone_id, tuple(str(a.get("id")) for a in used), date, n_samples,
                    nmin_value, used_nmin_date, p, k, tuple(notices))
