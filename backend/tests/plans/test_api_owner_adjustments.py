from tests.plans.test_api_signing import BASE, FARMER, TECH, _calculated, client  # noqa: F401


def test_n_adjustment_routes(client, pg_url):  # noqa: F811
    pid, plan = _calculated(client, pg_url)
    body = {"row_version": plan["row_version"], "basis": "foliar_analysis", "date": "2026-10-01",
            "reference": "LAB-77", "description": "N deficiency", "justified_n_kg_ha": 200}
    url = f"{BASE}/plans/{pid}/sheets/wheat/n-adjustment"
    assert client.put(url, json=body, headers=FARMER).status_code == 403
    assert client.put(url, json={**body, "basis": "hunch"}, headers=TECH).status_code == 422
    r = client.put(url, json=body, headers=TECH)
    assert r.status_code == 200 and r.json()["sheets"][0]["n_adjustment"]["reference"] == "LAB-77"
    r = client.delete(url, params={"row_version": r.json()["row_version"]}, headers=TECH)
    assert r.status_code == 200 and r.json()["sheets"][0]["n_adjustment"] is None


def test_holder_qualification_routes(client):  # noqa: F811
    url = f"{BASE}/holder-qualification"
    assert client.get(url, headers=FARMER).status_code == 404
    body = {"holder_name": "Juan", "qualification": "Ingeniero Agrónomo", "reference": "COIA 1"}
    assert client.put(url, json=body, headers=FARMER).status_code == 403
    assert client.put(url, json={**body, "reference": ""}, headers=TECH).status_code == 422
    assert client.put(url, json=body, headers=TECH).status_code == 200
    got = client.get(url, headers=FARMER).json()
    assert got["reference"] == "COIA 1" and got["updated_by"] == "u-tech" and got["updated_at"]


def test_declarations_route_takes_irrigated_spring_2026(client):  # noqa: F811
    r = client.post(f"{BASE}/plans", json={"campaign": 2027}, headers=FARMER)
    plan = r.json()
    url = f"{BASE}/plans/{plan['id']}/declarations"
    body = {"row_version": plan["row_version"], "vulnerable_zone": True}
    bad = client.put(url, json={**body, "irrigated_spring_2026": "maybe"}, headers=FARMER)
    assert bad.status_code == 422
    r = client.put(url, json={**body, "irrigated_spring_2026": False}, headers=FARMER)
    assert r.status_code == 200 and r.json()["declarations"]["irrigated_spring_2026"] is False
