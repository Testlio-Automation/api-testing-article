"""
Tiny orders API for the "Manual API Testing: Explore, Probe, Report" live demo.

It ships with a DELIBERATE data bug: the order total drops the cents
(an order of one item at 19.99 comes back with a total of 19). It hides
behind round numbers, so it only shows up when a tester tries a price like
19.99. Fix it by starting the server with FIX_TOTAL=1.

Run:
    uvicorn demo_api:app --port 8000             # buggy version
    FIX_TOTAL=1 uvicorn demo_api:app --port 8000 # fixed version

OpenAPI spec (for Schemathesis): http://localhost:8000/openapi.json
"""

import os
import uuid
from http import HTTPStatus
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(title="Demo Orders API", version="1.0.0")

# Two seeded demo users; the token just tells the API who is calling.
TOKENS = {"alice-token": "alice", "bob-token": "bob"}

# In-memory store: order_id -> {"owner": ..., "order": {...}}
ORDERS: dict[str, dict] = {}

FIX_TOTAL = os.getenv("FIX_TOTAL") == "1"


class Item(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0, le=1000)
    price: float = Field(ge=0, le=100_000)


class OrderIn(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=100)


class OrderOut(BaseModel):
    id: str
    items: list[Item]
    total: float
    status: Literal["pending", "paid", "cancelled"]


# Every error uses the same body: {"error": <code>, "message": <text>},
# plus "fields" for bad input.


# Bad input gets 400 (FastAPI's default is 422 with a detailed dump).
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_request",
            "message": "the request body is invalid",
            "fields": fields,
        },
    )


# 401, 404, 405 and any other HTTP error, including unknown routes and
# wrong methods raised by the framework itself (FastAPI's default is
# {"detail": ...}). Headers such as Allow on a 405 are kept.
@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": code, "message": str(exc.detail).lower()},
        headers=exc.headers,
    )


# Declared as a Bearer security scheme so /docs shows an Authorize button.
# auto_error=False lets current_user send its own 401 messages.
bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing or malformed token")
    user = TOKENS.get(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return user


def order_total(items: list[Item]) -> float:
    subtotal = sum(i.qty * i.price for i in items)
    if FIX_TOTAL:
        return round(subtotal, 2)
    # --- THE BUG -------------------------------------------------------------
    # int() truncates, so 19.99 becomes 19. Round numbers hide it completely.
    return float(int(subtotal))
    # -------------------------------------------------------------------------


@app.post("/orders", status_code=201, response_model=OrderOut)
def create_order(body: OrderIn, user: str = Depends(current_user)):
    order = {
        "id": str(uuid.uuid4()),
        "items": [i.model_dump() for i in body.items],
        "total": order_total(body.items),
        "status": "pending",
    }
    ORDERS[order["id"]] = {"owner": user, "order": order}
    return order


@app.get("/orders", response_model=list[OrderOut])
def list_orders(user: str = Depends(current_user)):
    return [r["order"] for r in ORDERS.values() if r["owner"] == user]


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str, user: str = Depends(current_user)):
    record = ORDERS.get(order_id)
    if record is None:
        raise HTTPException(status_code=404, detail="order not found")

    # Someone else's order gets the same 404 as a missing one, so callers
    # cannot learn which order IDs exist (a 403 would confirm it).
    if record["owner"] != user:
        raise HTTPException(status_code=404, detail="order not found")

    return record["order"]
