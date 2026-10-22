"""Plan PDF (spec §10.7): every art. 6 item, the signature and the seal, from the plan
document (the signed copy, or the current state marked as a draft)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, Undefined, select_autoescape

from app.plans.applications import ANNEX_V
from app.plans.clock import MADRID
from app.report.i18n import ANNEX_V_ES, LANGS, TEXTS, label

_ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]),
                   undefined=ChainableUndefined,
                   finalize=lambda x: "—" if x is None or isinstance(x, Undefined) else x)


def _value(sheet: dict, name: str):
    return (((sheet.get("result") or {}).get("inputs") or {}).get(name) or {}).get("value")


def _item(sheet: dict, name: str) -> dict:
    return ((sheet.get("result") or {}).get("inputs") or {}).get(name) or {}


def _missing(x) -> bool:
    return x is None or isinstance(x, Undefined)


def _number(x) -> float | None:
    if _missing(x) or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _num(x) -> str:
    """Whole number for display; a dash for a missing value (never a silent 0)."""
    v = _number(x)
    return "—" if v is None else str(round(v))


def _dec(x) -> str:
    """Up to two decimals, no trailing zeros; a dash for a missing value."""
    v = _number(x)
    return "—" if v is None else f"{round(v, 2):g}"


def _kg(app: dict, pct_key: str) -> float | None:
    rate, pct = _number(app.get("product_rate_kg_ha")), _number(app.get(pct_key))
    return None if rate is None or pct is None else round(rate * pct / 100, 1)


def _organic_kg(org: dict, pct_key: str) -> float | None:
    """kg/ha of a nutrient in an organic input: t/ha x 1000 x % / 100."""
    rate, pct = _number(org.get("rate_t_ha")), _number(org.get(pct_key))
    return None if rate is None or pct is None else round(rate * 1000 * pct / 100, 1)


def _organic_of(sheet: dict, app: dict) -> dict | None:
    """The organic input an application of kind organic points at, when it exists."""
    index = app.get("organic_index")
    organics = (sheet.get("inputs") or {}).get("organic") or []
    if app.get("kind") != "organic" or not isinstance(index, int) or isinstance(index, bool) \
            or not 0 <= index < len(organics):
        return None
    return organics[index]


def _local_dt(iso, lang: str) -> str:
    """Europe/Madrid local date-time of an ISO instant; the raw text when it cannot be read."""
    if _missing(iso):
        return "—"
    try:
        moment = datetime.fromisoformat(str(iso)).astimezone(MADRID)
    except ValueError:
        return str(iso)
    return moment.strftime("%d/%m/%Y %H:%M" if lang == "es" else "%Y-%m-%d %H:%M")


def plan_html(document: dict, lang: str = "es") -> str:
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}")
    return _ENV.get_template("plan.html").render(
        d=document, t=TEXTS[lang], lang=lang, value=_value, item=_item, kg=_kg, num=_num, fmt=_dec, organic_kg=_organic_kg,
        organic_of=_organic_of, local_dt=lambda x: _local_dt(x, lang),
        annex_v=ANNEX_V_ES if lang == "es" else ANNEX_V, label=lambda g, v: label(lang, g, v))


def plan_pdf(document: dict, lang: str = "es") -> bytes:
    # imported lazily: needs the system pango libraries
    from weasyprint import HTML

    return HTML(string=plan_html(document, lang)).write_pdf()
