"""Plan PDF (spec §10.7): every art. 6 item, the signature and the seal, from the plan
document (the signed copy, or the current state marked as a draft)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.plans.applications import ANNEX_V
from app.report.i18n import LANGS, TEXTS

_ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]),
                   finalize=lambda x: "—" if x is None else x)


def _value(sheet: dict, name: str):
    return (((sheet.get("result") or {}).get("inputs") or {}).get(name) or {}).get("value")


def _item(sheet: dict, name: str) -> dict:
    return ((sheet.get("result") or {}).get("inputs") or {}).get(name) or {}


def _num(x) -> str:
    """Whole number for display; a dash for a missing value (never a silent 0)."""
    return "—" if x is None else str(round(x))


def _kg(app: dict, pct_key: str) -> float | None:
    rate, pct = app.get("product_rate_kg_ha"), app.get(pct_key)
    return None if rate is None or pct is None else round(rate * pct / 100, 1)


def plan_html(document: dict, lang: str = "es") -> str:
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}")
    return _ENV.get_template("plan.html").render(
        d=document, t=TEXTS[lang], lang=lang, value=_value, item=_item, kg=_kg, num=_num,
        annex_v=ANNEX_V)


def plan_pdf(document: dict, lang: str = "es") -> bytes:
    # imported lazily: needs the system pango libraries
    from weasyprint import HTML

    return HTML(string=plan_html(document, lang)).write_pdf()
