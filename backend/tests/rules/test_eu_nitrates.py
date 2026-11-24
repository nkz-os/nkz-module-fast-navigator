"""Tests for EU Nitrates Directive 91/676/EEC (170 kg organic N / ha·year in NVZ)."""
from datetime import date

from app.rules import BLOCK, WARN, evaluate
from app.rules.context import PlanContext, SheetContext
from app.rules.eu import RULES


def _ctx(vulnerable_zone, organic_n_kg_ha):
    sheet = SheetContext(
        key="trigo-secano",
        inputs={},
        parcels=(),
        applications=(),
        result={},
        summary={"organic_n_total_kg_ha": organic_n_kg_ha},
    )
    return PlanContext(
        campaign=2027,
        sheets=(sheet,),
        rain=None,
        vulnerable_zone=vulnerable_zone,
        voluntary_digital_notebook=False,
        at=date(2026, 11, 24),
    )


def test_nvz_true_above_170_blocks():
    findings = evaluate(RULES, _ctx(True, 185.0))
    assert len(findings) == 1
    assert findings[0].rule_id == "EU-91-676-NVZ-170-N"
    assert findings[0].severity == BLOCK
    assert findings[0].sheet_key == "trigo-secano"


def test_nvz_true_at_170_passes():
    assert evaluate(RULES, _ctx(True, 170.0)) == []


def test_nvz_false_above_170_passes():
    assert evaluate(RULES, _ctx(False, 220.0)) == []


def test_nvz_undeclared_above_170_warns():
    findings = evaluate(RULES, _ctx(None, 190.0))
    assert len(findings) == 1
    assert findings[0].rule_id == "EU-91-676-NVZ-170-N-undeclared"
    assert findings[0].severity == WARN


def test_nvz_catches_organic_inputs_even_without_summary():
    sheet = SheetContext(
        key="trigo-secano",
        inputs={"organic": [{"material": "slurry", "rate_t_ha": 40.0, "n_pct": 0.5}]},
        parcels=(),
        applications=(),
        result={},
        summary=None,
    )
    ctx = PlanContext(
        campaign=2027,
        sheets=(sheet,),
        rain=None,
        vulnerable_zone=True,
        voluntary_digital_notebook=False,
        at=date(2026, 11, 24),
    )
    findings = evaluate(RULES, ctx)
    assert len(findings) == 1
    assert findings[0].rule_id == "EU-91-676-NVZ-170-N"
    assert findings[0].severity == BLOCK
