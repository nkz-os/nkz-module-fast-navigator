from fastapi.testclient import TestClient

from app.main import app

URL = "/api/fast/sources/organic-products"
H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}


def test_every_plan_role_reads_the_products():
    for role in ("Farmer", "TechnicalConsultant", "TenantAdmin"):
        r = TestClient(app).get(URL, headers={**H, "X-User-Roles": role})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["products"]) == 8
        assert body["attribution"]["source_id"] == "mapa_guia_2010"


def test_other_roles_and_anonymous_are_refused():
    assert TestClient(app).get(URL, headers={**H, "X-User-Roles": "Visitor"}).status_code in (401, 403)
    assert TestClient(app).get(URL).status_code in (401, 403)
