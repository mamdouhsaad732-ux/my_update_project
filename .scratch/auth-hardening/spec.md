# Spec: Authentication & PHI security hardening

## Problem

Authentication is currently a demo stub, but the app already holds PHI and is reachable over
HTTP:

- `USERS` stores plaintext passwords (`"123"`) in `main.py`; `login_post` compares them with
  `==`. A source leak or log of the structure exposes every credential immediately.
- `SESSION_SECRET` is a hardcoded constant baked into `SessionMiddleware` at import time, and
  `qr_signing_secret()` falls back to it. A deployment cannot rotate either secret without
  editing source, and anyone who reads the repo can mint session cookies and QR tokens.
- Destructive routes have inconsistent gates. `POST /doctor/delete/{record_id}` requires
  `admin`, but `POST /technician/delete/{record_id}` is defined twice and only permits the
  `technician` role; unauthenticated requests are rejected, yet the route contract, role policy,
  and duplication are untested and easy to regress.

## Decision

| Concern | Decision |
|---|---|
| Password storage | No plaintext passwords in `USERS`. Store a non-reversible hash per user and verify with a constant-time check. Correct credentials must still log users in. |
| Verification API | Provide `verify_password(plain, stored)` (and a hashing helper) in `main` so tests and the login route share one implementation. Wrong password → login redirect, no session. |
| Session secret | `SESSION_SECRET = os.getenv("SESSION_SECRET") or <fallback>` read at import; `SessionMiddleware` and the QR fallback use that value. A non-empty `SESSION_SECRET` env var must take precedence. The fallback may remain for local/dev, but must be clearly identified as insecure in code. |
| Doctor delete | `admin` only. Unauthenticated or non-admin → 303 `/login`, record and files untouched. |
| Technician delete | `technician` only (the uploader role). Unauthenticated or any other role → 303 `/login`, record and files untouched. Exactly one route/implementation must remain. |
| Response shape | Keep the existing 303 `/login` convention for unauthorised access and 303 back to the role dashboard on success. Do not introduce 401/403 JSON responses in this ticket. |

## Scope

- `main.py`: credential hashing + verification, `login_post` uses verification, `SESSION_SECRET`
  sourced from env, consolidate the duplicate technician-delete definition, preserve/clarify role
  gates.
- `tests/conftest.py`: fixture login must continue to work with the real user credentials.
- `tests/test_auth_hardening.py`: new.

## Out of scope

- CSRF tokens, rate limiting, account lockout, password rotation UI.
- Per-user secrets in a database, user management, or changing usernames/roles/password values.
- Rewriting every route to a unified RBAC framework; only the two delete endpoints named above.
- Removing the hardcoded QR/session fallback entirely (production deployment config is a follow-up
  once env plumbing exists), except making `SESSION_SECRET` env-respected as specified.
- Hashing algorithm choice beyond "non-reversible, salted, constant-time verify" (stdlib is fine).

## Acceptance criteria

- [ ] `USERS` contains no plaintext user passwords (the literal `"123"` must not appear as a stored password value).
- [ ] `verify_password("123", stored)` returns true for a known user; wrong password returns false.
- [ ] `POST /login` with correct credentials still establishes a session and redirects by role; wrong password redirects to `/login` with no session.
- [ ] With `SESSION_SECRET` set in the environment at import, `main.SESSION_SECRET` equals that value (and differs from the built-in fallback).
- [ ] `POST /doctor/delete/{id}`: admin succeeds (303 `/doctor`, record removed); secretary, technician, and anonymous → 303 `/login`, record remains.
- [ ] `POST /technician/delete/{id}`: technician succeeds (303 `/technician`, record removed); admin, secretary, and anonymous → 303 `/login`, record remains.
- [ ] Only one `POST /technician/delete/{record_id}` route is registered.
- [ ] Ticket 01–03 suites stay green.

## Risks

- **Breaking every fixture login.** `_login` posts the known password; the verifier must accept it.
- **Import-time secret.** `SessionMiddleware` is installed at import, so env-driven secret must be
  read before middleware registration; tests that rely on the in-process app cannot re-read env
  without isolation.
- **Route deduplication.** Removing the wrong duplicate could change which handler runs if they
  ever diverged; current copies are identical, so keep one and delete the other.
