"""Soil analyses of a parcel assigned to the zones of one zoning, and aggregated per zone.

Pure: no I/O. An analysis belongs to a zone by its explicit link (`hasAgriManagementZone`, when it
names a zone of THIS zoning), else by where it was sampled, else it is outside every zone.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from nkz_platform_sdk.gis.zones import zone_of

from app.inputs.soil import (
    analysis_k,
    analysis_mineral_n,
    analysis_n_depth,
    analysis_p_olsen,
    has_n_values,
)

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
    p_ids: tuple[str, ...] = ()        # analyses averaged into P
    k_ids: tuple[str, ...] = ()        # analyses averaged into K
    nmin_ids: tuple[str, ...] = ()     # analyses averaged into the mineral N


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


def sampling_day(analysis: dict) -> str | None:
    """Sampling day as YYYY-MM-DD (a longer timestamp is cut), None if absent."""
    raw = analysis.get("samplingDate")
    return raw[:10] if isinstance(raw, str) and len(raw) >= 10 else None


def _newest_mean(analyses: list[dict], read) -> tuple[float | None, list[dict], str | None]:
    """Mean of `read` over the analyses of the newest date that have a value, and that date.

    ASSUMPTION: an analysis without a usable sampling date is dropped: without a date it cannot
    be ranked against the others, so it must not be averaged in silently.
    """
    valued = [(a, v) for a in analyses if (v := read(a)) is not None and sampling_day(a)]
    if not valued:
        return None, [], None
    newest = max(sampling_day(a) for a, _ in valued)
    used = [(a, v) for a, v in valued if sampling_day(a) == newest]
    return fmean(v for _, v in used), [a for a, _ in used], newest


def zone_soil(zone_id: str, analyses: list[dict], *, nmin_date: str | None,
              class_bd: float | None, nmin_depth: tuple[float, float] | None = None,
              nmin_considered: bool = True) -> ZoneSoil:
    """`nmin_depth`: the depth range of the parcel's mineral-N analysis. A zone's mineral N is
    only credited over that same range (a 0-90 cm N is not comparable with a 0-30 cm one);
    None = not checked. `nmin_considered` False: the mineral N was not evaluated at all (the
    plan has no usable Nmin analysis), so an N-only analysis is not an unusable one."""
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
    nmin_used: list[dict] = []
    if nmin_date:
        on_date = [a for a in analyses if sampling_day(a) == nmin_date[:10] and has_n_values(a)]
        if on_date:
            same_depth = [a for a in on_date
                          if nmin_depth is None or analysis_n_depth(a) == nmin_depth]
            if len(same_depth) < len(on_date):
                notices.append(_notice("zone_nmin_depth_differs", zone=zone_id))
            values = [analysis_mineral_n(a, class_bd) for a in same_depth]
            bad = [str(a.get("id")) for a, v in zip(same_depth, values) if v is None]
            if bad:
                # Crediting a partial mean would understate N: leave it blank and say so.
                notices.append(_notice("zone_nmin_incomplete", zone=zone_id, analyses=bad))
            elif same_depth:
                nmin_value, used_nmin_date = fmean(values), nmin_date[:10]
                nmin_used = same_depth
        else:
            other = sorted({sampling_day(a) for a in analyses
                            if has_n_values(a) and sampling_day(a)})
            if other:
                notices.append(_notice("zone_nmin_other_date", zone=zone_id, date=other[-1]))

    specific = {"zone_nmin_depth_differs", "zone_nmin_incomplete", "zone_nmin_other_date"}
    judged = analyses if nmin_considered else [
        a for a in analyses if any(h.get("phosphorusAvailable") is not None
                                   or h.get("potassiumExchangeable") is not None
                                   for h in a.get("horizons") or [])]
    if (judged and p is None and k is None and nmin_value is None
            and not any(n["code"] in specific for n in notices)):
        notices.append(_notice("zone_soil_unusable", zone=zone_id,
                               analyses=[str(a.get("id")) for a in judged]))
    return ZoneSoil(zone_id, tuple(used), date, n_samples, p_date, k_date,
                    nmin_value, used_nmin_date, p, k, tuple(notices),
                    tuple(str(a.get("id")) for a in p_used),
                    tuple(str(a.get("id")) for a in k_used),
                    tuple(str(a.get("id")) for a in nmin_used))
