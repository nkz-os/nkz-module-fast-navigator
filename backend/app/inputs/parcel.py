"""Parcel facts read from the broker: area, identifier, location, farm (spec §3, §4)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .provenance import MEASURED, MissingInput, Notice, Sourced, missing

# Older parcels keep the area under the SAREF IRI, which the platform context does not compact.
SAREF_AREA = "https://saref.etsi.org/saref4agri/Area"
_SIGPAC = re.compile(r"^\d{1,2}:\d{1,3}:\d{1,3}:\d{1,3}:\d{1,3}:\d{1,5}:\d{1,4}$")
_CADASTRAL = re.compile(r"^[0-9A-Z]{14}([0-9A-Z]{6})?$")
_INE = re.compile(r"^\d{5}$")
# The cadastral module writes the enclosures under this name; until the platform context carries
# it, the broker returns the default-context IRI (or the platform one) instead.
ENCLOSURES_KEYS = ("sigpacEnclosures", "https://nkz-os.org/ns/sigpacEnclosures",
                   "https://uri.etsi.org/ngsi-ld/default-context/sigpacEnclosures")


def is_parcel_identifier(value: str) -> bool:
    """A SIGPAC recinto code or a Spanish cadastral reference (art. 6.1)."""
    v = value.strip().upper() if isinstance(value, str) else ""
    return bool(v) and bool(_SIGPAC.match(v) or _CADASTRAL.match(v))


def parse_enclosures(entity: dict) -> tuple[dict, ...]:
    """SIGPAC enclosures stored on the parcel: valid references only, as {reference, overlap_pct,
    overlap_ha}. Absent, malformed or empty gives ()."""
    raw = None
    for key in ENCLOSURES_KEYS:
        if isinstance(entity.get(key), list):
            raw = entity[key]
            break
    out = []
    for item in raw or ():
        ref = item.get("reference") if isinstance(item, dict) else None
        if not isinstance(ref, str) or not _SIGPAC.match(ref.strip()):
            continue
        out.append({"reference": ref.strip(), "overlap_pct": item.get("overlapPct"),
                    "overlap_ha": item.get("overlapAreaHa")})
    return tuple(out)


@dataclass(frozen=True)
class ParcelInfo:
    urn: str
    name: str | None
    area_ha: Sourced
    identifier: Sourced                   # SIGPAC or cadastral reference (art. 6.1)
    enclosures: tuple[dict, ...]          # every SIGPAC enclosure the parcel overlaps, largest first
    municipality_code: str | None         # INE code, only when the parcel carries one
    point: tuple[float, float] | None     # (lat, lon): mean of the outer ring's vertices
    farm: str | None
    irrigation_regime: str | None
    notices: tuple[Notice, ...]
    missing: tuple[MissingInput, ...]


def _rel(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("object") or value.get("value")
    return value if isinstance(value, str) and value else None


def _point(geometry) -> tuple[float, float] | None:
    if not isinstance(geometry, dict):
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    try:
        if kind == "Point":
            return float(coords[1]), float(coords[0])
        if kind == "Polygon":
            ring = coords[0]
        elif kind == "MultiPolygon":
            ring = coords[0][0]
        else:
            return None
        points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
        if not points:
            return None
        lat = sum(float(p[1]) for p in points) / len(points)
        lon = sum(float(p[0]) for p in points) / len(points)
        return lat, lon
    except (TypeError, ValueError, IndexError):
        return None


def parcel_info(entity: dict) -> ParcelInfo:
    """`entity` as read with options=keyValues and the platform @context."""
    urn = entity["id"]
    notices: list[Notice] = []
    absent: list[MissingInput] = []
    raw = entity.get("area", entity.get(SAREF_AREA))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        area = Sourced(float(raw), MEASURED, f"broker:{urn}")
    else:
        area = missing(f"broker:{urn}")
        absent.append(MissingInput("parcel.area_ha", "broker", {"parcel": urn}))
    enclosures = parse_enclosures(entity)
    ref = entity.get("cadastralReference")
    ref = ref.strip().upper() if isinstance(ref, str) and ref.strip() else None
    if enclosures:
        # The enclosures come first; the cadastral reference stays the fallback.
        identifier = Sourced(", ".join(e["reference"] for e in enclosures), MEASURED,
                             f"broker:{urn}:sigpacEnclosures", "sigpac")
    elif ref and is_parcel_identifier(ref):
        identifier = Sourced(ref, MEASURED, f"broker:{urn}", "sigpac" if ":" in ref else "cadastral")
    else:
        identifier = missing(f"broker:{urn}")
        if ref:
            notices.append(Notice("parcel_identifier_unrecognized", {"parcel": urn, "value": ref}))
    muni = entity.get("municipality")
    regime = entity.get("irrigationRegime")
    name = entity.get("name")
    return ParcelInfo(
        urn=urn,
        name=name if isinstance(name, str) else None,
        area_ha=area,
        identifier=identifier,
        enclosures=enclosures,
        municipality_code=muni if isinstance(muni, str) and _INE.match(muni) else None,
        point=_point(entity.get("location")),
        farm=_rel(entity.get("hasAgriFarm")) or _rel(entity.get("refAgriFarm")),
        irrigation_regime=regime if isinstance(regime, str) else None,
        notices=tuple(notices),
        missing=tuple(absent),
    )
