# Ticket 08 — review record

Two-axis review of `.scratch/production-readiness/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. Spec axis re-ran the suite once (119 passed).

Baseline integrity at review time: all 5 files in `.scratch/production-readiness/baseline/` match
`MANIFEST.sha256`. `Procfile`, `requirements*.txt`, and `tests/conftest.py` are unchanged.

---

## Production checklist verification

| Check | Result | Evidence |
|---|---|---|
| **Health probe** | `GET /health` → 200, minimal JSON `{"status":"ok","service":"medical-pacs"}`; no secrets/PHI | `main.py` `/health`; `test_health_endpoint_returns_ok` (forbidden keys: secret/password/token/patient/record/qr_signing) |
| **Session secret** | Unset at import → `auth: SESSION_SECRET is unset…` warning and published fallback in use; set via env → value respected, no fallback warning | `test_session_secret_unset_warns_and_set_is_respected` (isolated subprocess). **Action:** provision `SESSION_SECRET` in production. |
| **QR signing secret** | Unset at import → `QR_SIGNING_SECRET is unset…` warning; runtime fallback follows `SESSION_SECRET` | `test_qr_signing_secret_unset_warns` (isolated). **Action:** set `QR_SIGNING_SECRET` explicitly in production. |
| **Database URL** | Default `sqlite:///./medical_pacs.db`; env override (`DATABASE_URL`) respected | `test_database_url_default_and_override` (isolated). **Action:** point to durable production DB. |
| **Purge / retention** | Default off; opt-in via `PURGE_ENABLED` in `{1,true,yes}` (off for `{0,false,no}`), gated/logged | `test_purge_enabled_default_off_and_opt_in` (isolated). **Action:** set deliberately per retention policy. |
| **Legacy patient URLs** | Default on for printed-label compatibility; disable only after migration evidence | documented (T02 contract). **Action:** keep `LEGACY_PATIENT_URLS=true` during transition. |
| **Deployment contract** | `Procfile` runs `uvicorn main:app --host 0.0.0.0 --port $PORT` | `test_procfile_runs_uvicorn_app` |
| **End-to-end integration** | Authenticated dashboard, signed patient page, and guarded static assets reachable and coherent | `test_full_integration_smoke` |

> Readiness verification confirms configuration hooks, warnings, routes, and tests — not that
> production secrets/DB have been provisioned in the target environment.

---

## Standards

**Documented standards:** none (`AGENTS.md`/`docs/agents/*` process-only; no `CODING_STANDARDS.md`/
`CONTRIBUTING.md`). Only the smell baseline binds.

| Finding | Axis | Disposition |
|---|---|---|
| Health payload exposes service name (low-value fingerprint, no secret/PHI leak) | Standards (judgement) | Accepted — minimal and intentional for probe identification; not worth changing |
| `test_full_integration_smoke` claimed guarded static access reachable but did not assert it | Standards | **Fixed** — added authenticated `GET` assertions for upload and QR assets |
| Minor test noise/duplication (`record_id` placeholder, repeated isolated scaffolds, literal fallback constant in assertions) | Standards (judgement) | **Fixed** placeholder; duplication/literal coupling accepted (explicit contract, clear isolated tests) |

---

## Spec

**Acceptance criteria** (`.scratch/production-readiness/spec.md`):

| Criterion | Verdict | Evidence |
|---|---|---|
| `GET /health` returns 200 with minimal JSON indicating service health (no secrets/PHI) | checked | `main.py` `/health`; `test_health_endpoint_returns_ok` (discriminating forbidden-key scan) |
| Full test suite passes: 100% across T01–T07 plus T08 verification tests | checked | **119 passed**, 2 warnings |
| `SESSION_SECRET` unset → fallback warning at import; set → respected, no fallback warning (T04 contract) | checked | `test_session_secret_unset_warns_and_set_is_respected` (isolated) |
| `QR_SIGNING_SECRET` unset → startup warning; `DATABASE_URL` and `PURGE_ENABLED` defaults/overrides behave as documented | checked (hardened) | QR/DB isolated tests; **Spec axis noted `PURGE_ENABLED` coverage was weak** — strengthened with isolated assertions for unset and `1/true/yes` / `0/false/no` in `test_purge_enabled_default_off_and_opt_in` |
| `Procfile` invokes the application (`uvicorn main:app`) | checked | `test_procfile_runs_uvicorn_app` |
| No secrets or PHI exposed by the health endpoint or readiness checks | checked | `test_health_endpoint_returns_ok` |

**Deviations:** none. No scope creep. No requirements implemented wrong.

---

## Summary

- **Standards:** 1 accepted judgement, 1 fixed (smoke coverage), 2 minor notes accepted.
- **Spec:** 6/6 acceptance criteria checked (1 coverage gap hardened per axis), 0 deviations.

## Phase 4 verification

| Check | Result |
|---|---|
| T01–T07 baseline (pre-T08 tests) | 111 passed |
| T08 red phase | 2 failed (missing `/health`), 117 passed |
| Green (after `/health`) | **119 passed** |
| After review hardening | **119 passed**, 2 warnings |
| Baseline snapshot integrity | 5/5 files match `MANIFEST.sha256` |
| `/health` | 200 `{"status":"ok","service":"medical-pacs"}`, no secrets/PHI |
| `Procfile` | `uvicorn main:app` present |
