# FaST Navigator

Nekazari platform module that builds, checks and documents the **fertiliser
(nutrient) plan** required of Spanish farm holdings by the *Real Decreto
1051/2022, de 27 de diciembre, por el que se establecen normas para la
nutricion sostenible en los suelos agrarios* (the "FaST" plan, "plan de
abonado"). For each parcel and campaign it computes crop nutrient needs from
soil, crop, weather and operation data read from the platform, checks the
plan against the legal limits, and produces the plan document as a PDF with an
audit trail and an advisor signature flow.

Status: the backend is functional; the frontend in this repository is still the
module scaffold.

License: AGPL-3.0 (see `LICENSE`).

## Architecture

- `backend/` - FastAPI service (port 8000). Plans are stored in PostgreSQL
  (own `fast` schema, migrated on start). Authentication relies on the
  headers injected by the platform API gateway (`X-Tenant-ID`, `X-User-ID`,
  `X-User-Roles`) plus its HMAC signature; `/internal/*` uses a shared secret.
- `src/` - Module Federation frontend scaffold.
- `k8s/backend-deployment.yaml` - reference Kubernetes template with
  placeholders; real manifests belong to each installation's GitOps repo.

## API (under `API_PREFIX`, default `/api/fast`)

| Route | Purpose |
|---|---|
| `POST /calc/preview` | Stateless calculation preview |
| `GET /sources/parcels/{parcel_id}` | Inputs gathered for a parcel |
| `GET, POST /plans` | List / create plans |
| `GET /plans/{id}`, `GET /plans/{id}/audit` | Read a plan, its audit trail |
| `PUT /plans/{id}/sheets`, `.../sheets/{key}/overrides/{param}`, `.../sheets/{key}/n-adjustment` | Edit sheets, overrides, N adjustment |
| `POST /plans/{id}/calculate`, `GET /plans/{id}/compliance` | Calculate, check compliance |
| `GET /plans/{id}/pdf` | Plan document (PDF) |
| `POST /plans/{id}/rain-normal` | Rainfall normal for the plan |
| `POST /plans/{id}/submit`, `/return`, `/sign`, `/close`, `/revise` | Review and signing workflow |
| `PUT /plans/{id}/declarations` | Declarations |
| `GET, PUT /advisors/me` | Advisor profile |
| `GET, PUT /holder-qualification` | Holder qualification |
| `GET /internal/plans/summary` | Signed plan summary for in-cluster callers (shared secret) |
| `GET /health` | Probe (outside the prefix) |

OpenAPI docs are served at `{API_PREFIX}/docs`.

## Configuration (environment variables)

| Variable | Meaning |
|---|---|
| `POSTGRES_URL` (or `DATABASE_URL`) | PostgreSQL DSN. Mandatory: the service refuses to start without it. |
| `API_PREFIX` | Route prefix, default `/api/fast`. |
| `CORS_ORIGINS` | JSON list of allowed origins; empty denies all cross-origin requests. |
| `HMAC_SECRET` | Secret used to verify the gateway signature and to sign calls to other modules. |
| `REQUIRE_HMAC_SIGNATURE` | `true` to reject requests without a valid gateway signature. |
| `INTERNAL_SERVICE_SECRET` | Secret for `/internal/*`; unset means those routes always answer 401. |
| `BIOORCH_URL`, `SOIL_URL`, `WEATHER_API_URL`, `ENTITY_MANAGER_URL` | Base URLs of the platform services read for inputs. |
| `APP_NAME`, `APP_VERSION`, `DEBUG`, `LOG_LEVEL` | Application metadata and logging. |

See `env.example` for a local template.

## Tests

The backend suite needs Docker (PostgreSQL via testcontainers) and the pango
libraries for the PDF renderer (WeasyPrint):

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
ruff check app tests
```

The image builds with `docker build -t fast-navigator-backend backend/`.
