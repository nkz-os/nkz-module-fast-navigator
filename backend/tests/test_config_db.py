import pytest

from app.config import get_settings, require_postgres_url


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for name in ("POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_postgres_url_is_read(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "postgresql://u:p@db:5432/x")
    assert get_settings().postgres_url == "postgresql://u:p@db:5432/x"


def test_kubernetes_database_url_is_accepted(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/y")
    assert get_settings().postgres_url == "postgresql://u:p@db:5432/y"


def test_without_a_url_startup_fails():
    with pytest.raises(RuntimeError):
        require_postgres_url()
