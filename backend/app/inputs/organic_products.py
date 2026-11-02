"""Organic product suggestions: composition from the MAPA (2010) guide, versioned in a data file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "organic_products_mapa2010.yaml"

ATTRIBUTION = {
    "source_id": "mapa_guia_2010",
    "text": ("Ministerio de Agricultura, Pesca y Alimentación (2010), Guía práctica de la "
             "fertilización racional de los cultivos en España. Reutilización de información del "
             "sector público (Ley 37/2007)."),
    "url": None,
    "licence_url": None,
}


@lru_cache(maxsize=1)
def _load() -> tuple[str, tuple[dict, ...]]:
    with DATA_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["version"], tuple(data["products"])


def load_products() -> list[dict]:
    return [dict(p) for p in _load()[1]]


def products_version() -> str:
    return _load()[0]
