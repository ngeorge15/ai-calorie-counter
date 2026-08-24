"""Barcode lookup chain: cache -> USDA -> OFF -> miss."""
import pytest
import requests

from app import off_client, product_service, usda_client

COKE = "0049000042566"

USDA_FOOD = {
    "gtinUpc": "049000042566",          # note: FDC stores 12 digits, phone scans 13
    "description": "COCA-COLA CLASSIC",
    "brandName": "Coca-Cola",
    "servingSize": 360, "servingSizeUnit": "ml",
    "householdServingFullText": "12 fl oz",
    "foodNutrients": [
        {"nutrientNumber": "208", "value": 39},
        {"nutrientNumber": "205", "value": 10.6},
        {"nutrientNumber": "307", "value": 4},
    ],
}

OFF_PRODUCT = {
    "code": COKE, "product_name": "Coca-Cola", "brands": "Coca-Cola,Coke",
    "nutriments": {"energy-kcal_100g": 42, "carbohydrates_100g": 10.6,
                   "sodium_100g": 0.004},
}


@pytest.fixture
def no_network(monkeypatch):
    """Default both hops to misses; each test opts one back in."""
    monkeypatch.setattr(usda_client, "fetch_by_barcode", lambda b: None)
    monkeypatch.setattr(off_client, "fetch_by_barcode", lambda b: None)


def test_usda_is_tried_first_and_result_is_cached(app, no_network, monkeypatch, auth, client):
    calls = []
    monkeypatch.setattr(usda_client, "fetch_by_barcode",
                        lambda b: calls.append(b) or USDA_FOOD)

    first = client.get(f"/api/products/{COKE}", headers=auth).get_json()
    assert first["origin"] == "usda"
    assert first["product"]["name"] == "Coca-Cola Classic"
    assert first["product"]["per_100g"]["calories"] == 39

    # Second lookup must not reach USDA again.
    second = client.get(f"/api/products/{COKE}", headers=auth).get_json()
    assert second["origin"] == "cache"
    assert len(calls) == 1


def test_falls_back_to_off_when_usda_misses(app, no_network, monkeypatch, auth, client):
    monkeypatch.setattr(off_client, "fetch_by_barcode", lambda b: OFF_PRODUCT)

    result = client.get(f"/api/products/{COKE}", headers=auth).get_json()
    assert result["origin"] == "off"
    assert result["product"]["brand"] == "Coca-Cola"
    assert result["product"]["per_100g"]["sodium_mg"] == 4.0


def test_usda_transport_error_still_falls_through_to_off(app, no_network, monkeypatch, auth, client):
    """A USDA outage must degrade to OFF, not fail the scan."""
    def boom(barcode):
        raise requests.ConnectionError("USDA down")
    monkeypatch.setattr(usda_client, "fetch_by_barcode", boom)
    monkeypatch.setattr(off_client, "fetch_by_barcode", lambda b: OFF_PRODUCT)

    result = client.get(f"/api/products/{COKE}", headers=auth).get_json()
    assert result["origin"] == "off"


def test_total_miss_returns_actionable_404(app, no_network, auth, client):
    response = client.get(f"/api/products/{COKE}", headers=auth)
    assert response.status_code == 404
    # The client needs the barcode back to prefill manual entry.
    assert response.get_json()["barcode"] == COKE


def test_user_contribution_turns_a_miss_into_a_hit(app, no_network, auth, client):
    created = client.post(f"/api/products/{COKE}", headers=auth, json={
        "name": "Store brand cola", "per_100g": {"calories": 40},
    })
    assert created.status_code == 201

    result = client.get(f"/api/products/{COKE}", headers=auth).get_json()
    assert result["origin"] == "cache"
    assert result["product"]["source"] == "user"


def test_upc_padding_variants_match():
    """A 13-digit scan must match FDC's 12-digit record."""
    assert usda_client._upc_variants("0049000042566") & usda_client._upc_variants("049000042566")
    assert not usda_client._upc_variants("049000042566") & usda_client._upc_variants("049000042567")


def test_fuzzy_usda_result_with_wrong_upc_is_rejected(monkeypatch):
    """FDC search returns near-matches; trusting them logs the wrong food."""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"foods": [{"gtinUpc": "111111111111",
                                           "description": "Not your drink"}]}
    monkeypatch.setenv("USDA_API_KEY", "test-key")
    monkeypatch.setattr(usda_client.usda_session, "get", lambda *a, **k: FakeResponse())

    assert usda_client.fetch_by_barcode(COKE) is None
