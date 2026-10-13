from datetime import UTC, date, datetime

from app.api import plans as api_plans
from app.plans import clock


def _fixed(instant: datetime):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant
    return Fixed


def test_the_legal_date_is_the_spanish_calendar_date(monkeypatch):
    new_year = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)      # already 1 January in Madrid
    monkeypatch.setattr(clock, "datetime", _fixed(new_year))
    assert clock.legal_today() == date(2027, 1, 1)
    summer = datetime(2027, 8, 31, 22, 30, tzinfo=UTC)         # CEST, UTC+2
    monkeypatch.setattr(clock, "datetime", _fixed(summer))
    assert clock.legal_today() == date(2027, 9, 1)


def test_the_api_dates_sign_close_and_calculate_with_the_legal_clock():
    assert api_plans.legal_today is clock.legal_today
    import inspect
    assert "date.today" not in inspect.getsource(api_plans)
