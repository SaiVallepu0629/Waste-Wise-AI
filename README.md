# WasteWise-AI

WasteWise-AI is a food-inventory management dashboard for tracking manually
managed stock, reviewing historical inventory snapshots, and surfacing clearly
labeled expiry and discount guidance.

## Features

- React dashboard with inventory search, pagination, responsive charts, and
  loading, empty, and error states.
- FastAPI authentication with Argon2id password hashing, expiring JWT access
  tokens, logout revocation, and SQLite-backed login throttling.
- User-owned inventory CRUD. Imported CSV snapshots remain shared,
  unowned, and read-only.
- Rule-based live expiry-risk and discount estimates. An estimate is marked
  unknown when user-entered daily demand is needed but unavailable.
- A saved Random Forest demand model with chronological held-out evaluation.
  Future demand is not forecast when the available data does not support it.
- SQLite migration, integrity-checked backup, and non-overwriting restore
  utilities.

## Technology

| Area | Technology |
| --- | --- |
| Frontend | React, Vite |
| API | FastAPI, Pydantic |
| Database | SQLite, SQLAlchemy |
| Authentication | JWT, Argon2id (`pwdlib`) |
| Analytics | pandas, NumPy, scikit-learn |

Python runtime dependencies are pinned in `requirements.txt`; the development
test dependency is in `requirements-dev.txt`. The frontend dependency tree is
locked by `frontend/package-lock.json`.

## Project layout

```text
Backend/
  routes/                 Authentication and inventory APIs
  services/               Forecast and inventory guidance
  tests/                  API, authorization, migration, and backup tests
  database.py             SQLite engine and initialization
  migrations.py           Additive schema migrations
  database_maintenance.py Verified backup and restore commands
frontend/
  src/                    React dashboard and API client
ml/
  artifacts/              Saved demand model
  data/raw/               Source datasets
  data/processed/         Derived analytics and simulations
  notebooks/              Model and data exploration
data/                     Local SQLite database (ignored by Git)
```

The application loads its existing model artifact and CSV datasets from `ml/`.
They are not generated or retrained at startup.

## Run locally (Windows PowerShell)

Prerequisites: Python 3.12 and Node.js 24 (or a compatible supported Node.js
release for the locked Vite version).

From the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Set-Location .\frontend
npm.cmd ci
Set-Location ..
```

Set a local JWT secret in the current PowerShell session. It is intentionally
not written to a file:

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
[byte[]]$secretBytes = New-Object byte[] 48
$rng.GetBytes($secretBytes)
$env:WASTEWISE_JWT_SECRET = [Convert]::ToBase64String($secretBytes)
$rng.Dispose()
$env:WASTEWISE_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

In the first PowerShell window, from the project directory, start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn Backend.main:app --reload
```

In a second window, start the frontend:

```powershell
Set-Location .\frontend
npm.cmd run dev
```

Open `http://localhost:5173`. Register an account to begin. Access tokens are
kept in memory, expire after 30 minutes by default, and are revoked when you
sign out. A page refresh requires signing in again.

The SQLite database is created at `data/inventory.sqlite3`. To add the shared,
read-only CSV snapshot records to a new local database, run this once:

```powershell
Set-Location 'C:\path\to\WasteWise-AI'
.\.venv\Scripts\python.exe -m Backend.import_inventory
```

The importer is additive and repeat-safe; it does not delete or replace
existing rows.

## API

Interactive API documentation is available at `http://localhost:8000/docs` in
development. In production, the documentation and OpenAPI endpoints are
disabled by default.

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| GET | `/` | Public | Health/status response |
| POST | `/auth/register` | Public | Register and receive an access token |
| POST | `/auth/login` | Public, rate-limited | Sign in and receive an access token |
| POST | `/auth/logout` | Bearer token | Revoke the current access token |
| GET | `/auth/me` | Bearer token | Get the current user profile |
| GET | `/inventory/items` | Bearer token | List visible records; accepts `limit`, `offset`, `search` |
| POST | `/inventory/items` | Bearer token | Create a user-owned inventory item |
| GET | `/inventory/items/{item_id}` | Bearer token | Read an inventory item |
| PUT | `/inventory/items/{item_id}` | Bearer token | Update an owned manual item |
| DELETE | `/inventory/items/{item_id}` | Bearer token | Delete an owned manual item |
| GET | `/inventory/recommendations` | Bearer token | Rule-based live inventory guidance |
| GET | `/inventory` | Bearer token | Dated inventory dataset snapshots |
| GET | `/expiry-risk` | Bearer token | Source labels and rule-based snapshot estimates |
| GET | `/discount-recommendations` | Bearer token | Labeled, simulated discount scenarios |
| GET | `/forecast/summary` | Bearer token | Model evaluation and data coverage |
| GET | `/forecast/products` | Bearer token | Products with supported model history |
| GET | `/forecast/product/{product_id}` | Bearer token | Historical and held-out product results |

Protected endpoints require `Authorization: Bearer <access_token>`. Missing,
invalid, expired, or revoked tokens are rejected. Users cannot read or change
another user's manual inventory. Historical CSV snapshots are shared but
read-only.

## Data and model interpretation

- The trained artifact is a Random Forest demand regressor. Evaluation metrics
  use a chronological held-out split and are not a guarantee of current
  performance.
- There is no trained expiry-risk classifier. Live risk and discount
  recommendations are rules-based estimates, not model predictions or observed
  waste.
- Historical expiry data and discount-scenario outcomes come from dated source
  data. Simulation results are not confirmed sales or margins.
- Future forecasts remain unavailable when data freshness or evaluation
  conditions do not support them.

## Configuration and security

The API reads configuration from its process environment:

| Variable | Required | Purpose |
| --- | --- | --- |
| `WASTEWISE_JWT_SECRET` | Yes | Random signing key; at least 32 bytes |
| `WASTEWISE_ENVIRONMENT` | No | `development` by default; `production` enforces HTTPS CORS and disables API docs |
| `WASTEWISE_CORS_ORIGINS` | Production | Comma-separated exact frontend origins; HTTPS required in production |
| `WASTEWISE_ACCESS_TOKEN_MINUTES` | No | Token lifetime from 1 to 60 minutes; defaults to 30 |
| `WASTEWISE_DATABASE_URL` | No | SQLite URL; defaults to `data/inventory.sqlite3` |
| `VITE_API_BASE_URL` | No | Frontend build-time API base URL; production defaults to same-origin |

Never commit secrets, `.env` files, live databases, or backups. Use the hosting
provider's secret manager/environment settings. Keep the signing secret stable
across service restarts; rotating it invalidates existing tokens.

The login throttle uses SQLite and the request client address. If deploying
behind a reverse proxy, trust forwarded addresses only from the proxy IPs.
These controls do not replace edge-level request limits, TLS, or monitoring.

## Backups and recovery

Before deploying schema changes and on a regular schedule, create a verified
SQLite online backup outside the application directory:

```powershell
.\.venv\Scripts\python.exe -m Backend.database_maintenance backup
```

To restore, stop the API and restore to a new, unused path; the command refuses
to overwrite files:

```powershell
.\.venv\Scripts\python.exe -m Backend.database_maintenance restore `
  "C:\path\to\inventory-backup.sqlite3" `
  --target "C:\path\to\inventory-recovered.sqlite3"
```

The utility verifies SQLite integrity and foreign-key consistency. Keep an
encrypted off-host copy and test recovery before relying on backups. Never use
the application repository or ephemeral container storage as the only copy of
production data.

## Deployment architecture

No cloud resources or deployment are configured by this repository. For a
small, single-instance deployment without changing the current database layer,
the recommended first option is a **Render Static Site for the frontend plus a
paid Render Web Service with a persistent disk for the API and SQLite file**.
This keeps the existing stack and avoids a PostgreSQL migration. Render
documents that static sites are free, while persistent disks attach to paid
services; free web services use ephemeral filesystems, spin down, and must not
hold SQLite data ([persistent disk documentation](https://render.com/docs/disks),
[static site documentation](https://render.com/docs/static-sites),
[free instance limitations](https://render.com/docs/free)).

Configure the services manually after approving a deployment:

1. Connect the approved GitHub repository to a static site. Set the frontend
   root directory to `frontend`, build command to `npm ci && npm run build`,
   and publish directory to `dist`.
2. Set the static site's build-time `VITE_API_BASE_URL` to the backend's HTTPS
   URL, for example `https://your-api.onrender.com`.
3. Create one backend web service from the repository root. Install with
   `pip install -r requirements.txt`; use a production Uvicorn command that
   binds `0.0.0.0` and the platform-provided port.
4. Attach a persistent disk mounted at `/var/data` and set
   `WASTEWISE_DATABASE_URL=sqlite:////var/data/inventory.sqlite3`. The model
   artifact and required CSV files must be included in the deployed source
   release.
5. Set `WASTEWISE_ENVIRONMENT=production`, a stable random
   `WASTEWISE_JWT_SECRET`, and `WASTEWISE_CORS_ORIGINS` to the exact HTTPS
   frontend origin. Keep one API worker.
6. Confirm the provider's forwarded-client-IP behavior before configuring
   trusted proxy headers; do not trust arbitrary forwarded headers. Schedule
   encrypted off-host backups and test recovery to a new database file.

This option is relatively simple for low traffic, but the backend service and
durable disk are not a free production setup. SQLite on a persistent disk
couples storage to one host/worker, limits horizontal scaling, and still needs
independent backups. Do not deploy the database to ephemeral storage or run
multiple app instances against one SQLite file. For multi-instance deployment,
migrate the application and tests to managed PostgreSQL and move login
throttling to a shared store before scaling; the current backend explicitly
supports SQLite only. Check current provider pricing, storage durability,
backup/restore options, region, and data-processing terms. The local SQLite
file is ignored by Git and is not automatically uploaded during deployment.
Plan a separate secure data transfer and verify counts and integrity on the
target before switching traffic.

## Screenshots

No screenshots are currently included. Add reviewed screenshots under
`docs/screenshots/` and link them here before publishing. Use synthetic
accounts and inventory; do not capture real email addresses or production data.

## Tests and checks

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s Backend\tests -t . -v
.\.venv\Scripts\python.exe -m compileall -q Backend
.\.venv\Scripts\python.exe -m pip check
Set-Location .\frontend
npm.cmd ci
npm.cmd run build
npm.cmd run lint
npm.cmd audit
```

GitHub Actions runs the automated backend and frontend checks on pushes and
pull requests.

## Before publishing

- Review source-data, notebook, and model-artifact redistribution rights.
- Inspect the staged file list and confirm the SQLite database, backups,
  virtual environments, secrets, and generated build/dependency folders are
  excluded.
- Choose and add a license only if you have the right to publish the code and
  data under its terms.
- Configure production secrets, HTTPS, durable storage, monitoring, and
  off-host backups before accepting real users.
- Do not publish a cloud endpoint, repository, or secrets without explicit
  owner approval.
