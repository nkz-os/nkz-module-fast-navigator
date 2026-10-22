"""Spanish national rules."""
from . import advice, annex3, rd1051

RULES = [*rd1051.RULES, *annex3.RULES, *advice.RULES]
