"""
API tests for the demo orders API.

These are the checks from the talk's live exploratory session, turned into
automated regression tests. test_total_keeps_cents fails until the API is
started with FIX_TOTAL=1.

Run the API first, then:
    pytest -v
Point at another server with:
    BASE_URL=https://staging.example.com pytest -v
"""

import os

import jsonschema
import pytest
import requests

BASE = os.getenv("BASE_URL", "http://localhost:8000")
ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}

ORDER_SCHEMA = {
    "type": "object",
    "required": ["id", "items", "total", "status"],
    "properties": {
        "id": {"type": "string"},
        "items": {"type": "array"},
        "total": {"type": "number", "minimum": 0},
        "status": {"enum": ["pending", "paid", "cancelled"]},
    },
    "additionalProperties": False,  # no unexpected fields in the response
}


def create_order(headers, items=None):
    if items is None:
        items = [{"sku": "MUG", "qty": 2, "price": 10}]
    return requests.post(f"{BASE}/orders", headers=headers, json={"items": items})


# ------------------------------------------------ checks from the session

def test_create_order():
    r = create_order(ALICE)
    assert r.status_code == 201
    jsonschema.validate(r.json(), ORDER_SCHEMA)
    assert r.json()["total"] == 20
    assert r.elapsed.total_seconds() < 0.5


def test_total_keeps_cents():
    """The bug found in the demo: round prices hid it."""
    r = create_order(ALICE, items=[{"sku": "MUG", "qty": 1, "price": 19.99}])
    assert r.status_code == 201
    assert r.json()["total"] == 19.99


def test_rejects_negative_quantity():
    r = create_order(ALICE, items=[{"sku": "MUG", "qty": -1, "price": 10}])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_wrong_method_is_405():
    order_id = create_order(ALICE).json()["id"]
    r = requests.delete(f"{BASE}/orders/{order_id}", headers=ALICE)
    assert r.status_code == 405
    assert r.json()["error"] == "method_not_allowed"


def test_max_quantity_boundary():
    assert create_order(ALICE, items=[{"sku": "MUG", "qty": 1000, "price": 1}]).status_code == 201
    assert create_order(ALICE, items=[{"sku": "MUG", "qty": 1001, "price": 1}]).status_code == 400


# -------------------------------------------------------------------- extras

def test_content_type_is_json():
    r = create_order(ALICE)
    assert r.headers["Content-Type"].startswith("application/json")


def test_created_order_can_be_read_back():
    created = create_order(ALICE).json()
    r = requests.get(f"{BASE}/orders/{created['id']}", headers=ALICE)
    assert r.status_code == 200
    assert r.json() == created


def test_unknown_order_is_404():
    r = requests.get(f"{BASE}/orders/does-not-exist", headers=ALICE)
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "items",
    [
        [],                                          # empty order
        [{"sku": "", "qty": 1, "price": 10}],        # empty SKU
        [{"sku": None, "qty": 1, "price": 10}],      # null SKU
        [{"sku": "MUG", "qty": 0, "price": 10}],     # zero quantity
        [{"sku": "MUG", "qty": "two", "price": 10}], # wrong type
        [{"sku": "MUG", "qty": 1, "price": -5}],     # negative price
        [{"qty": 1, "price": 10}],                   # missing field
    ],
)
def test_invalid_inputs_rejected(items):
    r = create_order(ALICE, items=items)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


# ------------------------------------------------------------ error bodies

ERROR_SCHEMA = {
    "type": "object",
    "required": ["error", "message"],
    "properties": {
        "error": {"type": "string"},
        "message": {"type": "string"},
        "fields": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "method, path, headers, body",
    [
        ("post", "/orders", ALICE, {"items": []}),  # 400
        ("get", "/orders", {}, None),               # 401
        ("get", "/orders/does-not-exist", ALICE, None),  # 404
        ("get", "/no-such-route", ALICE, None),     # 404 from the framework
        ("delete", "/orders/x", ALICE, None),       # 405 from the framework
    ],
)
def test_every_error_has_the_same_shape(method, path, headers, body):
    r = requests.request(method, f"{BASE}{path}", headers=headers, json=body)
    assert r.status_code >= 400
    jsonschema.validate(r.json(), ERROR_SCHEMA)


# ------------------------------------------------------------ auth and access

@pytest.mark.parametrize(
    "headers",
    [
        {},                                         # no token
        {"Authorization": "alice-token"},           # missing "Bearer "
        {"Authorization": "Bearer not-a-token"},    # unknown token
    ],
)
def test_bad_token_is_401(headers):
    r = requests.get(f"{BASE}/orders", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_cannot_read_another_users_order():
    """Bob gets the same 404 as for a missing order, not Alice's data."""
    order_id = create_order(ALICE).json()["id"]
    r = requests.get(f"{BASE}/orders/{order_id}", headers=BOB)
    assert r.status_code == 404
    # Byte for byte the same as a missing order, so nothing leaks.
    missing = requests.get(f"{BASE}/orders/does-not-exist", headers=BOB)
    assert r.json() == missing.json()


def test_list_shows_only_own_orders():
    order_id = create_order(ALICE).json()["id"]
    r = requests.get(f"{BASE}/orders", headers=BOB)
    assert r.status_code == 200
    assert order_id not in [o["id"] for o in r.json()]
