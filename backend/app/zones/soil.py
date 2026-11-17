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
    date: str | None                   # newest of p_date / k_date
    n_samples: int                     # analyses averaged for the better-covered of P and K (max of both counts)
    p_date: str | None                 # sampling date of the analyses behind P
    k_date: str | None                 # sampling date of the analyses behind K
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


def _day(analysis: dict) -> str | None:
    """Sampling day as YYYY-MM-DD (a longer timestamp is cut), None if absent."""
    raw = analysis.get("samplingDate")
    return raw[:10] if isinstance(raw, str) and len(raw) >= 10 else None


def _newest_mean(analyses: list[dict], read) -> tuple[float | None, list[dict], str | None]:
    """Mean of `read` over the analyses of the newest date that have a value, and that date.

    ASSUMPTION: an analysis without a usable sampling date is dropped: without a date it cannot
    be ranked against the others, so it must not be averaged in silently.
    """
    valued = [(a, v) for a in analyses if (v := read(a)) is not None and _day(a)]
    if not valued:
        return None, [], None
    newest = max(_day(a) for a, _ in valued)
    used = [(a, v) for a, v in valued if _day(a) == newest]
    return fmean(v for _, v in used), [a for a, _ in used], newest


def _has_nmin(a: dict) -> bool:
    return any(h.get("nitrateN") is not None or h.get("ammoniumN") is not None
               for h in a.get("horizons") or [])


def zone_soil(zone_id: str, analyses: list[dict], *, nmin_date: str | None,
              class_bd: float | None) -> ZoneSoil:
    notices: list[dict] = []
    p, p_used, p_date = _newest_mean(analyses, analysis_p_olsen)
    k, k_used, k_date = _newest_mean(analyses, analysis_k)
    used: dict[str, dict] = {}
    for a in p_used + k_used:
        used.setdefault(str(a.get("id")), a)
    date = max((d for d in (p_date, k_date) if d), default=None)
    n_samples = max(len(p_used), len(k_used))
    if n_samples > 1:
        notices.append(_notice("zone_soil_aggregated", zone=zone_id, n=n_samples))
    if p_date and k_date and p_date != k_date:
        notices.append(_notice("zone_soil_mixed_dates", zone=zone_id, p_date=p_date, k_date=k_date))

    nmin_value: float | None = None
    used_nmin_date: str | None = None
    if nmin_date:
        on_date = [a for a in analyses if _day(a) == nmin_date[:10] and _has_nmin(a)]
        if on_date:
            values = [analysis_mineral_n(a, class_bd) for a in on_date]
            bad = [str(a.get("id")) for a, v in zip(on_date, values) if v is None]
            if bad:
                # Crediting a partial mean would understate N: leave it blank and say so.
                notices.append(_notice("zone_nmin_incomplete", zone=zone_id, analyses=bad))
            else:
                nmin_value, used_nmin_date = fmean(values), nmin_date[:10]
        else:
            other = sorted({_day(a) for a in analyses if _has_nmin(a) and _day(a)})
            if other:
                notices.append(_notice("zone_nmin_other_date", zone=zone_id, date=other[-1]))

    return ZoneSoil(zone_id, tuple(used), date, n_samples, p_date, k_date,
                    nmin_value, used_nmin_date, p, k, tuple(notices))
