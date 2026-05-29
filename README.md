# Restricted Web Tool

Restricted Web Tool is RepoHeal's deterministic library intelligence microservice.

## Environment

Create a `.env` file from `.env.example` with:

```env
MONGODB_URI=<MONGODB_URI>
MONGODB_DATABASE=repoheal
CACHE_EXPIRY_DAYS=7
PORT=8000
INTERNAL_API_KEY=<LONG_RANDOM_SECRET>
ALLOWED_DOMAINS=pypi.org,github.com,githubusercontent.com,readthedocs.io,readthedocs.com,docs.*
UPSTREAM_TIMEOUT_SECONDS=8
UPSTREAM_RETRY_COUNT=3
```

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Security

Every endpoint except `GET /health` requires:

```http
Authorization: Bearer <INTERNAL_API_KEY>
```

The service rate limits `POST /library-intelligence` and `POST /bulk-library-intelligence` to 100 requests per minute per API key.
Bulk requests are capped at 25 libraries per request.

## Render Deployment

Use a Render Web Service with these settings:

* Build Command: `pip install -r requirements.txt`
* Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
* Runtime: Python 3.11+

Required environment variables on Render:

* `MONGODB_URI`
* `MONGODB_DATABASE=repoheal`
* `CACHE_EXPIRY_DAYS=7`
* `INTERNAL_API_KEY`
* `ALLOWED_DOMAINS`

If you prefer blueprint deploys, use [render.yaml](render.yaml).

## Startup

On boot the service pings MongoDB, creates required collections and indexes, validates the internal API key, validates allowed domains, and writes a startup audit event.

## API

* `GET /health`
* `POST /library-intelligence`
* `POST /bulk-library-intelligence`
* `POST /symbol-intelligence`
