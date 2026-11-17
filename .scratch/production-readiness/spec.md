# Spec: Production readiness & final integration verification

## Context

Tickets 01–07 addressed data integrity, signed QR access, report loop restoration, credential and
session hardening, template and inline XSS mitigation, and PHI asset access control. 111 tests pass
across T01–T07. This ticket confirms the application is configurable, observable at startup, and
verifiable as an integrated whole before operational sign-off.

## Configuration inventory (current behavior)

| Variable | Current behavior | Production intent |
|---|---|---|
| `SESSION_SECRET` | Read at import; falls back to a published insecure default and logs `auth: SESSION_SECRET is unset…` warning | Must be set to a strong, private value in production |
| `QR_SIGNING_SECRET` | Read per call; falls back to `SESSION_SECRET` and logs `qr: QR_SIGNING_SECRET is unset…` warning at startup when unset | Should be set explicitly in production to decouple QR credential rotation from session rotation |
| `DATABASE_URL` | Defaults to `sqlite:///./medical_pacs.db`; SQLite uses `check_same_thread=False` | Must point to the intended durable database in production |
| `PURGE_ENABLED` | Opt-in (`1/true/yes`), default off; when enabled purge is gated/logged | Set deliberately per retention policy; never rely on default for compliance |
| `LEGACY_PATIENT_URLS` | Default on (`true`) for backward compatibility with numeric `/patient/<id>` | Disable only after printed-label migration evidence; keep enabled during transition |

## Readiness goals

| Concern | Decision |
|---|---|
| Health/readiness signal | Provide a lightweight `GET /health` endpoint returning 200 with a minimal, non-sensitive JSON body suitable for platform probes (no PHI, no secrets, no DB record contents). |
| Startup observability | Keep/verify existing startup warnings for insecure secret fallbacks; configuration must be diagnosable from logs without exposing secret values. |
| Integration integrity | Full suite (`pytest tests/ -q`) passes in isolation with zero regressions across T01–T07. |
| Deployment contract | `Procfile` and dependency manifests remain consistent with running `uvicorn main:app`; required env vars are documented in this spec/ticket and verification tests. |

## Scope

- `main.py`: add `/health` endpoint (and any minimal wiring required) if not present.
- `tests/test_production_readiness.py`: integration/config/readiness verification tests.
- `.scratch/production-readiness/*`: spec, ticket, baseline, review artifacts.

## Out of scope

- Introducing new infrastructure (Docker/Kubernetes manifests, CI pipelines, external monitoring)
  beyond a simple in-app health endpoint and documented config.
- Migrating from SQLite, changing purge policy semantics, or rotating/removing hardcoded fallbacks
  (tracked as earlier follow-ups).
- CSRF, CSP, public-static restructuring beyond T07, or feature work unrelated to readiness.

## Acceptance criteria

- [ ] `GET /health` returns 200 with a minimal JSON payload indicating service health (no secrets/PHI).
- [ ] Full test suite passes: 100% pass rate across T01–T07 plus T08 verification tests.
- [ ] With `SESSION_SECRET` unset at import (isolated), startup emits the insecure-fallback warning; with it set, fallback warning is not emitted and the value is respected (as per T04 contract).
- [ ] With `QR_SIGNING_SECRET` unset, startup emits the configured warning; `DATABASE_URL` and `PURGE_ENABLED` defaults/overrides behave as documented.
- [ ] `Procfile` invokes the application (`uvicorn main:app`).
- [ ] No secrets or PHI are exposed by the health endpoint or readiness checks.

## Risks

- **Health endpoint information leakage.** Keep response minimal and static/operational only.
- **Import-time side effects in tests.** Config/warning checks must use isolated subprocesses (existing
  `run_in_isolated_cwd` pattern) to avoid coupling to the in-process app.
- **False sense of security.** Readiness verification confirms configuration hooks and test health,
  not that production secrets have actually been provisioned in the deployment environment.
