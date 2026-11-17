# Medical PACS (FastAPI)

A lightweight Medical PACS-style web application for uploading imaging studies, managing patient records and radiology reports, and sharing signed patient-facing access via QR codes. The system is built with **FastAPI + Jinja2 + SQLAlchemy** and is designed for deployable, test-verified operation on **SQLite (local/dev)** or **managed PostgreSQL (production)** with durable file storage.

**Status:** production-hardened baseline with **121 automated tests passing** (T01–T08 + storage/DB readiness), covering core workflows, security controls, and deployment contracts.

---

## 1. System Overview & Architecture

### What the application does
- **Role-based workflows:** authenticated access for **admin/doctor**, **secretary**, and **technician** users (session-backed login) to manage records, uploads, reporting, archiving, and downloads.
- **Study intake:** technicians upload imaging files (standard images and/or DICOM). DICOM inputs are processed with `pydicom`/`NumPy`/`Pillow` to produce web-viewable PNG previews while preserving a stable record of stored assets.
- **Reporting & sharing:** staff can create/save diagnostic reports; each record can be accessed via a **signed, non-enumerable patient URL/QR**. Patient views render study/report context with token-authorized asset access.
- **Retention & operations:** optional, gated retention purge; lightweight liveness probe at `/health`.

### Architecture (high level)
- **Web/API layer:** FastAPI app (`main.py`, app object `main:app`) with server-rendered Jinja2 templates (`templates/`) and form/route handlers for staff, patient, and operational endpoints.
- **Persistence:** SQLAlchemy ORM (`PatientRecord`) with `SessionLocal` request/session management and startup schema bootstrap via `Base.metadata.create_all(bind=engine)`.
- **Database portability:** `DATABASE_URL` seam with automatic scheme normalization (`postgres://` → `postgresql://`), SQLite-only `connect_args={"check_same_thread": False}`, and `pool_pre_ping=True` for non-SQLite engines.
- **File storage:** configurable filesystem roots for PHI-bearing assets (uploads and generated QR PNGs) with **stable public URL/DB contracts** (`/static/uploads/...`, `/static/qrs/...`).
- **Static/asset serving:**
  - Public, non-PHI branding assets: mounted from `static/image` (when present).
  - **PHI-bearing assets** (`/static/uploads/*`, `/static/qrs/*`): served only through guarded handlers (not public static mounts).

### “Dual-Engine” workflow (diagnostic + preview)
- **Diagnostic/source handling:** uploaded studies (including DICOM where provided) are ingested and processed server-side; pixel data is normalized/converted to image output suitable for clinical review workflows in the app.
- **Preview/delivery path:** web-friendly PNG previews (and related assets) are written to the configured uploads store and referenced by stable `/static/uploads/...` URLs in the record; patient/staff UIs render previews (gallery/lightbox) while access to underlying files remains authorization-gated. QR artifacts for patient access are generated into the configured QR store and served via guarded `/static/qrs/...` endpoints.

> Note: this application provides web preview/report distribution workflows and does **not** replace a certified diagnostic workstation or full DICOM network stack.

---

## 2. Security & Hardening Highlights

Implemented and test-verified controls include:

- **Authentication hardening:** PBKDF2 password hashing and verification for configured users; session secret sourced from `SESSION_SECRET` (insecure published fallback is warned at startup if unset). Role-gated access for staff routes/actions.
- **Signed patient access (anti-enumeration):** patient links/QR payloads use **signed tokens** (itsdangerous) minted per record; legacy numeric `/patient/{id}` compatibility is available behind `LEGACY_PATIENT_URLS` (redirect + logged) for migration.
- **PHI asset access control:** uploads and QR images are **not anonymously retrievable**. Access requires an authenticated staff session **or** a valid, record-scoped `?patient_token=` credential; path resolution is constrained to the configured base directories (traversal-safe checks).
- **XSS protections:** Jinja2 autoescaping for template rendering and explicit escaping for inline HTML builders/f-string contexts in hardened paths to prevent stored/reflected script injection in reviewed surfaces.
- **Report/write-path integrity:** unified, authorized report-save flow with safe redirect handling and single-commit behavior.
- **Operational safeguards:** optional retention purge is **opt-in** (`PURGE_ENABLED`) and logged; `/health` returns a minimal, non-sensitive liveness response (no secrets/PHI). Proxy headers middleware enabled for deployment behind reverse proxies.

**Production note:** provision strong secrets, durable DB/storage, and review residual hardening items (e.g. CSRF/CSP, rate limiting/lockout, credential lifecycle, least-privilege scoping, token transport tradeoffs) per your threat model and compliance requirements.

---

## 3. Environment Variables (Configuration Reference)

| Variable | Default | Purpose / Behavior |
|---|---|---|
| `SESSION_SECRET` | *published insecure fallback if unset* | Secret key for session middleware. **Must be set to a strong, private value in production.** If unset, app logs: `auth: SESSION_SECRET is unset…` and uses a built-in fallback. |
| `QR_SIGNING_SECRET` | falls back to `SESSION_SECRET` | Secret used to sign patient QR tokens (read per use). **Set explicitly in production** to decouple rotation from sessions. If unset, app logs: `qr: QR_SIGNING_SECRET is unset…`. Rotating invalidates previously issued QR/patient tokens. |
| `DATABASE_URL` | `sqlite:///./medical_pacs.db` | SQLAlchemy database URL. Supports SQLite and PostgreSQL; `postgres://` is normalized to `postgresql://`. SQLite uses `check_same_thread=False`; non-SQLite engines enable `pool_pre_ping=True`. For durable Render SQLite use an absolute disk path (e.g. `sqlite:////var/data/medical_pacs.db`). |
| `STORAGE_DIR` | *(unset)* | Base directory for persistent assets. When set (and explicit overrides not provided), resolves to `UPLOADS_DIR=$STORAGE_DIR/uploads`, `QRS_DIR=$STORAGE_DIR/qrs`. Recommended for Render Disk mounts (e.g. `/var/data`). |
| `UPLOADS_DIR` | `static/uploads` (or `$STORAGE_DIR/uploads`) | Filesystem path for uploaded/converted scan files. **URL/DB values remain** `/static/uploads/...`. Takes precedence over `STORAGE_DIR` derivation. |
| `QRS_DIR` | `static/qrs` (or `$STORAGE_DIR/qrs`) | Filesystem path for generated QR PNGs. **URL/DB values remain** `/static/qrs/...`. Takes precedence over `STORAGE_DIR` derivation. |
| `PURGE_ENABLED` | off | Opt-in retention purge (records older than 30 days). Truthy: `1`, `true`, `yes` (case-insensitive). Destructive; enable deliberately per retention policy. |
| `LEGACY_PATIENT_URLS` | on (`true`) | When enabled, numeric `/patient/<id>` requests are logged and redirected (303) to the signed patient URL for backward compatibility with previously printed labels. Disable only after migration evidence. |
| `PORT` | *(platform-provided)* | Bind port for Uvicorn/Procfile on Render (`0.0.0.0:$PORT`). Do not hardcode in production platforms that inject it. |

**Do not commit secrets.** Generate strong values, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

---

## 4. Local Development & Testing

### Prerequisites
- Python **3.11.x** (project runtime pinned via `runtime.txt`: `python-3.11.9`)
- Windows PowerShell examples below use the repo’s `.venv` layout (adapt for macOS/Linux shells as needed)

### Setup
```powershell
# from repository root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

(Optional) configure local env vars (PowerShell):
```powershell
$env:SESSION_SECRET = "dev-session-secret"
$env:QR_SIGNING_SECRET = "dev-qr-secret"
# $env:DATABASE_URL = "sqlite:///./medical_pacs.db"        # default
# $env:STORAGE_DIR = "$PWD\.data"                           # optional durable local paths
# $env:PURGE_ENABLED = "false"
# $env:LEGACY_PATIENT_URLS = "true"
```

### Run tests
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```
Expected: **121 passed** (2 non-fatal dependency deprecation warnings may appear).

### Run locally (Uvicorn)
```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
- App: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health` → `{"status":"ok","service":"medical-pacs"}`
- Default DB/storage (when unset): local `medical_pacs.db`, `static/uploads/`, `static/qrs/`.

---

## 5. Render Production Deployment Guide

### 5.1 Service configuration
1. **Create** a Render **Web Service** from this repository/branch.
2. **Runtime:** Python (honors `runtime.txt`, `python-3.11.9`).
3. **Build command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start command:** use the `Procfile` or set explicitly:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
   (`Procfile`: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`)
5. **Health check path:** `/health` (expects HTTP 200 with minimal JSON).
6. **Instance sizing:** for SQLite-on-disk and local file storage, run a **single instance** sharing the same persistent disk.

### 5.2 Persistent Disk (uploads/QRs and optional SQLite)
Attach a **Render Persistent Disk** (example mount: `/var/data`) sized for imaging assets and QR files.

- **Assets (required for persistence):** set `STORAGE_DIR=/var/data` so uploads/QRs are stored under `/var/data/uploads` and `/var/data/qrs` while URLs/DB values remain `/static/uploads/...` and `/static/qrs/...`.
  - (Alternative: set `UPLOADS_DIR=/var/data/uploads` and `QRS_DIR=/var/data/qrs` explicitly.)
- **SQLite on disk (simple durable option):** `DATABASE_URL=sqlite:////var/data/medical_pacs.db`
- **Important:** without a persistent disk (and correct env paths), the container filesystem is ephemeral and uploads/QRs/SQLite data will be lost on redeploy/restart.

### 5.3 Managed PostgreSQL (Render Postgres)
1. Provision a **Render PostgreSQL** instance and copy its **Internal Database URL**.
2. Set `DATABASE_URL` to that value. The app accepts `postgres://` and normalizes to `postgresql://`; `psycopg2-binary` is included in `requirements.txt`.
3. On a **fresh** database, startup `create_all` will create required tables.
4. Keep assets on a **persistent disk/object storage strategy** appropriate for your deployment (`STORAGE_DIR` covers disk-backed assets).

> **Migration note:** `create_all` does not perform schema migrations on existing databases and does not migrate data from SQLite. For live schema evolution or data moves, use an explicit migration/ETL process (e.g. Alembic + verified export/import) and back up before changes.

### 5.4 Environment variables (production checklist)
Set in Render → **Environment** (minimum recommended):

```text
SESSION_SECRET=<strong-random-secret>
QR_SIGNING_SECRET=<separate-strong-random-secret>
DATABASE_URL=sqlite:////var/data/medical_pacs.db   # or Render Postgres URL
STORAGE_DIR=/var/data                              # with attached persistent disk
PURGE_ENABLED=false                                # enable deliberately per policy
LEGACY_PATIENT_URLS=true                           # until printed-label migration complete
```

### 5.5 Deploy, verify, and monitor
1. **Deploy** and confirm startup logs do **not** show secret-fallback warnings in production configuration.
2. **Liveness:** `GET https://<service>.onrender.com/health` → `200 {"status":"ok","service":"medical-pacs"}`.
3. **Smoke test:** authenticate, upload a study, generate/save report, open signed patient page/QR, and verify guarded asset access works.
4. **Persistence check:** redeploy/restart and confirm DB records and scan/QR files persist on the disk (and in Postgres if used).
5. **Observability:** monitor application logs for retention actions (when enabled) and legacy numeric patient URL usage during migration.

### 5.6 Operational caveats
- Rotate `QR_SIGNING_SECRET`/session secrets with awareness that issued tokens/labels may be invalidated.
- Enforce backups/snapshots for disk and database per PHI/compliance policy.
- Review and complete residual hardening (CSRF/CSP, rate limiting, credential management, least-privilege access, and token transport) before broad PHI exposure.

---

## Repository pointers
- **App entrypoint:** `main.py` (`app = FastAPI()`, `main:app`)
- **Templates:** `templates/`
- **Tests:** `tests/` (pytest; shared fixtures in `tests/conftest.py`)
- **Deploy manifests:** `Procfile`, `runtime.txt`, `requirements.txt`, `requirements-dev.txt`
- **Ops artifacts/history:** `.scratch/` (tickets/specs/reviews/baselines, when present)
