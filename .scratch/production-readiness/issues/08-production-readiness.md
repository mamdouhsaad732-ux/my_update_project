# 08 — Production readiness & final integration verification

- **Status**: resolved
- **Type**: task
- **Depends on**: 01–07 (resolved) — final verification over the hardened, feature-complete baseline.
- **Spec**: `.scratch/production-readiness/spec.md`

## Objective

Confirm end-to-end readiness: configuration/env behavior is explicit and verifiable, startup
diagnostics remain intact, a lightweight health probe exists for deployments, and the full suite
passes with zero regressions.

## Architecture impact

| Component | Change |
|---|---|
| `main.py` | Add `GET /health` (minimal, non-sensitive JSON 200) if missing |
| `tests/test_production_readiness.py` | New integration/config/readiness verification tests |
| `.scratch/production-readiness/*` | Spec, ticket, baseline, diff, review artifacts |

## Plan

1. Baseline snapshot (`main.py`, `Procfile`, `requirements*.txt`, `tests/conftest.py`) + `MANIFEST.sha256`. Done.
2. Run full suite and record 100% pass baseline (T01–T07). Done.
3. Write `tests/test_production_readiness.py` (verification; health-endpoint assertion may be red until implemented).
4. Implement `/health` if required and ensure readiness tests pass.
5. Green, including all prior suites.
6. Two-axis review; fix; re-run.

## Risk assessment

**Low.** Changes are additive/observational (health endpoint, tests, docs). Guards: isolated
subprocess checks for import-time config, no secrets/PHI in responses, full-suite regression run.
Rollback: restore baseline files.

## Test plan

| Test | Pins |
|---|---|
| `test_health_endpoint_returns_ok` | `GET /health` → 200, minimal JSON, no secrets/PHI keys |
| `test_app_imports_and_core_routes_registered` | app boots, critical routes present |
| `test_session_secret_unset_warns_and_set_is_respected` | isolated import warnings/values |
| `test_qr_signing_secret_unset_warns` | isolated startup warning |
| `test_database_url_default_and_override` | default fallback and env override respected |
| `test_purge_enabled_default_off_and_opt_in` | default false, truthy enables |
| `test_procfile_runs_uvicorn_app` | deployment contract present |
| `test_full_integration_smoke` | login + key flows still coherent (optional lightweight) |

## Deviations

- None. `/health` path and minimal JSON body align with spec; no config behaviour corrected, only
  verified and surfaced. **Review-driven test hardening (not a deviation):** `test_full_integration_smoke`
  now asserts guarded static asset access (matching its stated scope), and
  `test_purge_enabled_default_off_and_opt_in` strengthened with isolated checks for unset and
  `1/true/yes` / `0/false/no`.

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (5 files) verified intact; diff in
`.scratch/production-readiness/changes.diff`, review in `.scratch/production-readiness/review.md`.
Suite: **119 passed** (111 T01–T07 + 8 T08), 2 warnings. Red→green: 2 failed / 117 passed (missing
`/health`) → 119 passed.

Shipped:

- **Health probe:** `GET /health` (`main.py`) returns 200 `{"status":"ok","service":"medical-pacs"}`
  — minimal, unauthenticated, no secrets/PHI.
- **Readiness verification tests:** `tests/test_production_readiness.py` covering health payload,
  core route registration, integration smoke (dashboard + signed patient page + guarded assets),
  isolated config contracts (`SESSION_SECRET` warning/respect, `QR_SIGNING_SECRET` warning,
  `DATABASE_URL` default/override, `PURGE_ENABLED` default/opt-in), and `Procfile` contract.

**Production checklist (provision in deployment):** set `SESSION_SECRET` and `QR_SIGNING_SECRET`
(fallbacks warn and are insecure), set `DATABASE_URL` to durable storage, set `PURGE_ENABLED`
per retention policy, keep `LEGACY_PATIENT_URLS=true` until printed-label migration evidence.
Readiness checks verify hooks/warnings/tests, not that prod env is provisioned.

