"""Soil analyses of a parcel assigned to the zones of one zoning, and aggregated per zone.

Pure: no I/O. An analysis belongs to a zone by its explicit link (`hasAgriManagementZone`, when it
names a zone of THIS zoning), else by where it was sampled, else it is outside every zone.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from nkz_platform_sdk.gis.zones import zone_of

from app.inputs.provenance import Notice
from app.inputs.soil import (
    analysis_k,
    analysis_mineral_n,
    analysis_n_depth,
    analysis_p_olsen,
    has_n_values,
    topsoil_mean,
    unusable_readings,
    zone_mean_id,
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


def post_zoning_analyses(analyses: list[dict], zoning: ZoningRead) -> list[dict]:
    """The analyses that may be zone samples of this zoning: taken on or after its date (owner
    decision: older ones describe the parcel, not these zones). None when the zoning has no date."""
    zoned = zoning.date or zoning.image_date
    if zoned is None:
        return []
    return [a for a in analyses if sampling_day(a) and (sampling_day(a) or "") >= zoned[:10]]


def located_without_zoning_date(analyses: list[dict], zoning: ZoningRead) -> bool:
    """The zoning has no date, so no analysis can be told to be a zone sample, and some analysis
    is located inside (or linked to) a zone of it: the zones' own soil is being left out."""
    if (zoning.date or zoning.image_date) is not None:
        return False
    return bool(assign_analyses(analyses, zoning)[0])


@dataclass(frozen=True)
class ZoneMean:
    """The parcel soil of a zone campaign: a synthetic analysis (the area-weighted mean of the
    zones) and how much of the parcel the sampled zones cover."""
    analysis: dict
    zones_sampled: int
    zones_total: int                       # zones with a usable area (the ones that can be weighted)
    area_pct: float
    sample_ids: frozenset = frozenset()    # the zone samples (assigned to a zone of the zoning)
    notices: tuple[Notice, ...] = ()       # unusable P/K readings of the zones' newest samples


def _horizon_reader(key: str, partner: str | None = None):
    """Reads `key` of the topsoil; with `partner`, only from analyses that carry both (sand and
    clay are one reading: a texture must not mix two sources)."""
    def read(a: dict) -> float | None:
        hz = a.get("horizons") or []
        if partner is not None and topsoil_mean(hz, partner) is None:
            return None
        return topsoil_mean(hz, key)
    return read


# Synthetic-analysis key -> how one analysis yields it (the same readers the zone soil uses).
_MEAN_FIELDS = {
    "sand": _horizon_reader("sand", "clay"),
    "clay": _horizon_reader("clay", "sand"),
    "ph": _horizon_reader("ph"),
    "organicMatter": _horizon_reader("organicMatter"),
    "phosphorusAvailable": analysis_p_olsen,       # Olsen-equivalent mg/kg
    "potassiumExchangeable": analysis_k,           # ammonium-acetate mg/kg
}


def parcel_zone_mean(analyses: list[dict], zoning: ZoningRead) -> ZoneMean | None:
    """Area-weighted mean over the zones of `zoning` that have their own samples, or None when
    there is no zone campaign: at least two DIFFERENT zones must have samples of the SAME
    sampling day (owner decision; one located analysis is not a campaign).

    Each zone contributes, per field, what `_newest_mean` gives (newest sampling date, mean of
    that date), weighted by the zone entity's `area_ha` (not the outer ring: zones nest). A field
    present in only some zones is the mean over those. ASSUMPTION: a zone without a usable
    area cannot be weighted and is left out of the mean, of the coverage and of the campaign test.
    """
    by_zone, _ = assign_analyses(post_zoning_analyses(analyses, zoning), zoning)
    weighted = [(z, z.area_ha) for z in zoning.zones if z.area_ha]
    # Only analyses that give an averaged field count: an N-only sample is not a soil campaign.
    days_by_zone = {z.id: {sampling_day(a) for a in by_zone.get(z.id) or []
                           if any(read(a) is not None for read in _MEAN_FIELDS.values())}
                    for z, _ in weighted}
    if not any(sum(1 for days in days_by_zone.values() if day in days) >= 2
               for day in set().union(*days_by_zone.values())):
        return None
    total_area = sum(a for _, a in weighted)
    sums: dict[str, list[float]] = {k: [0.0, 0.0] for k in _MEAN_FIELDS}   # sum(v*a), sum(a)
    dates: list[str] = []
    covered = 0.0
    sampled = 0
    for zone, area in weighted:
        rows = by_zone.get(zone.id) or []
        got = False
        for key, read in _MEAN_FIELDS.items():
            value, _, day = _newest_mean(rows, read)
            if value is None:
                continue
            sums[key][0] += value * area
            sums[key][1] += area
            dates.append(day)
            got = True
        if got:
            sampled += 1
            covered += area
    if not sampled:
        return None
    horizon: dict = {"depthFrom": 0, "depthTo": 30}
    for key, (acc, weight) in sums.items():
        if weight > 0:
            horizon[key] = acc / weight
    if "phosphorusAvailable" in horizon:
        horizon["phosphorusMethod"] = "olsen"
    if "potassiumExchangeable" in horizon:
        horizon["potassiumMethod"] = "ammonium_acetate"
    notices: list[Notice] = []
    for rows in by_zone.values():
        dated = [a for a in rows if sampling_day(a)]
        newest = max((sampling_day(a) for a in dated), default=None)
        for a in dated:
            if sampling_day(a) == newest:
                notices.extend(n for n in unusable_readings(a)[1] if n not in notices)
    sample_ids = frozenset(a.get("id") for rows in by_zone.values() for a in rows)
    synthetic = {"id": zone_mean_id(zoning.run_id), "samplingDate": max(dates),
                 "horizons": [horizon]}
    return ZoneMean(synthetic, sampled, len(weighted), round(100 * covered / total_area, 1),
                    sample_ids, tuple(notices))
