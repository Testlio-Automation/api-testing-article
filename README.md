# Manual API Testing demo

Companion code for the talk "Manual API Testing: Explore, Probe, Report".

- `demo_api.py` is a tiny orders API to explore by hand. It has a deliberate
  data bug: order totals drop the cents (19.99 comes back as 19).
- `test_orders.py` turns the checks from the live session into automated
  regression tests.

## Setup

Needs Python 3.10 or newer.

    pip install -r requirements.txt

## Explore it by hand

    uvicorn demo_api:app --port 8000

Then send requests with curl, Postman or Bruno. Use the header
`Authorization: Bearer alice-token` on every request. Example:

    curl -s -X POST localhost:8000/orders \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"items":[{"sku":"MUG","qty":1,"price":19.99}]}'

The interactive docs are at http://localhost:8000/docs. Click **Authorize**
and paste `alice-token` (without `Bearer `) to send it on every request.

## Run the regression tests

    pytest -v

Expected with the buggy server: `test_total_keeps_cents` fails, the rest pass.
Restart with `FIX_TOTAL=1 uvicorn demo_api:app --port 8000` and all pass.
