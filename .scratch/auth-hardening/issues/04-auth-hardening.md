# 04 — Authentication & PHI security hardening

- **Status**: resolved
- **Type**: task
- **Depends on**: 01–03 (resolved) — builds on the current login/session flow, QR signing fallback, and report/delete behaviour.
- **Spec**: `.scratch/auth-hardening/spec.md`

## Objective

Replace demo-grade auth with a minimally defensible baseline: hashed credentials, an env-configurable
session secret, and deletion endpoints that are both role-gated and unambiguous.

## Architecture impact

| Component | Change |
|---|---|
| `USERS` / login | Store password hashes, not plaintext; `login_post` verifies via a shared helper |
| `SESSION_SECRET` | Read from `SESSION_SECRET` env (with explicit insecure fallback) before middleware install; QR fallback follows it |
| `POST /doctor/delete/{id}` | Keep admin-only gate; add explicit regression coverage for unauth/unauthorised attempts |
| `POST /technician/delete/{id}` | Keep technician-only gate, remove the duplicate route definition, add regression coverage |
| `tests/conftest.py` | Fixture login remains compatible with hashed credentials |
| `tests/test_auth_hardening.py` | New |

## Plan

1. Baseline snapshot (`main.py`, `tests/conftest.py`) + `MANIFEST.sha256`. Done.
2. Write `tests/test_auth_hardening.py` (red).
3. Implement hashing/verification + env-respected secret + route dedup; keep fixture logins green.
4. Green, including Ticket 01–03 suites.
5. Two-axis review; fix; re-run.

## Risk assessment

**Medium.** The sharp edges:

- *Locked-out fixtures / all tests red for the wrong reason.* Guard by implementing verification in
  a way that accepts the existing `"123"` credential through the login path, and by running the
  full suite, not just the new file.
- *Secret read too late.* Guard by reading env into `SESSION_SECRET` at module scope and asserting
  it in an isolated subprocess.
- *Deletion policy confusion.* This ticket asserts the **current** intended split (admin deletes
  via `/doctor/delete`, technician via `/technician/delete`) rather than inventing a cross-role
  policy; any change must be called out as a deviation.

Rollback: restore the two baseline files. No schema change.

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_stored_passwords_are_not_plaintext` | no raw `"123"` stored |
| `test_verify_password_accepts_correct_and_rejects_wrong` | hash+verify contract |
| `test_login_with_correct_password_still_works` | role redirects preserved |
| `test_login_with_wrong_password_does_not_create_session` | no session on failure |
| `test_session_secret_respects_env_at_import` | env precedence over fallback (subprocess) |
| `test_doctor_delete_requires_admin` | admin ok; secretary/technician/anon rejected, record intact |
| `test_technician_delete_requires_technician` | technician ok; admin/secretary/anon rejected, record intact |
| `test_technician_delete_route_is_not_duplicated` | exactly one registered route |

## Deviations

- None. Technician-delete policy remains technician-only; no policy broadening. Additive startup
  `logger.warning` when the fallback session secret is in use is consistent with the spec's
  "fallback clearly identified as insecure" requirement (not a scope deviation).

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (2 files) verified intact; diff in
`.scratch/auth-hardening/changes.diff`, review in `.scratch/auth-hardening/review.md`.
Suite: **86 passed** (26 T01 + 27 T02 + 24 T03 + 9 T04), up from 5 failed / 81 passed at the T04
red phase.

Shipped:

- **Credentials:** `hash_password` / `verify_password` (PBKDF2-HMAC-SHA256, 200k iterations,
  per-user salt, `hmac.compare_digest`); `USERS` stores hashes only. `POST /login` verifies via
  the shared helper and preserves role redirects/session behaviour.
- **Session secret:** `_DEFAULT_SESSION_SECRET` is the explicit insecure fallback;
  `SESSION_SECRET = os.getenv("SESSION_SECRET") or _DEFAULT_SESSION_SECRET` read at import and
  passed to `SessionMiddleware` and the QR-signing fallback. Startup warns when the fallback is
  in use.
- **Deletions:** duplicate `POST /technician/delete/{record_id}` removed (exactly one route
  registered). `doctor/delete` remains admin-only; `technician/delete` remains technician-only;
  unauthenticated/unauthorised requests → 303 `/login` with record intact.

## Follow-ups (not this ticket)

1. Enforce `SESSION_SECRET` in non-dev/prod (fail closed or explicit dev flag) — the published
   fallback is still usable if unset.
2. Store minimal session claims instead of the full user record (avoids persisting the password
   hash in the session cookie payload).
3. Replace demo credentials with rotated/externally managed secrets; hashing removes
   plaintext-at-rest but not default-credential compromise.
4. Broader hardening unchanged: CSRF, plaintext-legacy fallback removal strategy, public
   `/static/uploads`, `autoescape=False`.

