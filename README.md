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

The service rate limits normal intelligence endpoints to 100 requests per minute per API key.
Bulk requests are limited to 10 requests per minute per API key and have a 60-second overall deadline.
Bulk requests are capped at 25 libraries per request.

Responses use a shared envelope with `request_id`, `status`, and endpoint data.
The status is one of `success`, `cached`, `degraded`, `rate_limited`,
`provider_unavailable`, or `timeout`. Bulk responses retain the `results` array,
and each item uses the same status and request ID fields.

RepoHeal should use `POST /bulk-library-intelligence` and configure the same
`INTERNAL_API_KEY` value in both Render services.

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
* `GET /health/providers`
* `GET /library-intelligence/{library}`
* `POST /bulk-library-intelligence`
* `POST /symbol-intelligence`

`GET /library-intelligence/{library}` returns library metadata with `library`, `latest_version`,
`intelligence_status`, `intelligence_reason`, `official_docs`, and `github_repo`.
`POST /bulk-library-intelligence` accepts `{"libraries": [{"library": "pandas", "symbols": ["pandas.DataFrame"]}]}`
and returns `{"request_id": "...", "status": "success", "results": [...]}`. Each result contains
the library metadata, status, and symbol relationship results. `/health/providers` reports
provider state only; it never returns API keys or other secrets. Upstream responses are
restricted by content type and size, and redirects are revalidated against `ALLOWED_DOMAINS`.
