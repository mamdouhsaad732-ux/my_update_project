# Ticket 04 — review record

Two-axis review of `.scratch/auth-hardening/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. Spec axis re-ran the suite once (86 passed).

Baseline integrity at review time: `main.py` and `tests/conftest.py` in
`.scratch/auth-hardening/baseline/` match `MANIFEST.sha256`. `tests/conftest.py` is unchanged.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern process/domain only. The only standard is the smell baseline.

**Correctness / security (diff-introduced):**

| Finding | Disposition |
|---|---|
| Passwords stored as salted PBKDF2-HMAC-SHA256 hashes; `verify_password` uses `hmac.compare_digest` and fails closed on malformed stored values | OK (constant-time, non-reversible) |
| `login_post` uses `verify_password` with a uniform redirect to `/login` (no user-existence leak added) | OK |
| `SESSION_SECRET` read from env at import, before `SessionMiddleware` install; fallback explicitly named insecure in code and warned at startup when in use | OK for the spec's goal (env-respected + identified fallback). **Deployment caveat:** the published fallback remains usable if operators do not set `SESSION_SECRET` — fail-closed/non-dev enforcement is a follow-up, not this ticket. |
| Duplicate `POST /technician/delete/{record_id}` removed; single technician-only handler remains | OK |
| Session stores the full user record including the password hash | **Noted, out of scope.** Pre-existing pattern preserved; smallest follow-up is to store minimal claims (`username`, `role`, `modality`). |
| Demo credentials (`"123"`) still the real secrets, now hashed | **Noted, out of scope.** Hashing removes plaintext-at-rest but not default-credential compromise; rotation/secret-store is a follow-up. |

**Smells (judgement calls):**

| Smell | Location | Disposition |
|---|---|---|
| Speculative Generality / dead code in a new test (unused first subprocess run, no-op `if False` probe) | `tests/test_auth_hardening.py` | **Fixed** — removed; test now asserts `main.SESSION_SECRET` and the `SessionMiddleware` `secret_key` both equal the env value |

---

## Spec

**Acceptance criteria** (`.scratch/auth-hardening/spec.md`, walked item by item):

| Criterion | Verdict | Evidence |
|---|---|---|
| `USERS` contains no plaintext user passwords | checked | `USERS` built with `hash_password("123")`; `test_stored_passwords_are_not_plaintext` |
| `verify_password("123", stored)` true for a known user; wrong/empty false | checked | PBKDF2+salt + `hmac.compare_digest`; `test_verify_password_accepts_correct_and_rejects_wrong` |
| Correct login establishes session and redirects by role; wrong password → `/login`, no session | checked | `login_post` uses shared verifier; `test_login_with_correct_password_still_works`, `test_login_with_wrong_password_does_not_create_session` |
| `SESSION_SECRET` env set at import takes precedence over built-in fallback | checked | read before middleware; `test_session_secret_respects_env_at_import` (asserts module value and middleware `secret_key`), `test_session_secret_env_differs_from_builtin_fallback` |
| `POST /doctor/delete/{id}`: admin succeeds; secretary/technician/anon rejected, record intact | checked | `test_doctor_delete_requires_admin` |
| `POST /technician/delete/{id}`: technician succeeds; admin/secretary/anon rejected, record intact | checked | `test_technician_delete_requires_technician` |
| Only one `POST /technician/delete/{record_id}` route registered | checked | duplicate removed; `test_technician_delete_route_is_not_duplicated` |
| Ticket 01–03 suites stay green | checked | full suite 86 passed |

No criterion is satisfied only by a non-discriminating/baseline-passing test: baseline stored
plaintext `"123"`, had no `verify_password`, hardcoded `SESSION_SECRET`, and registered the
technician delete route twice.

**Behaviour not asked for / deviations:**
- Additive `logger.warning` when the fallback session secret is in use — consistent with "fallback
  clearly identified as insecure"; not a deviation under the ticket.
- No deletion-policy broadening; technician delete remains technician-only.

**Implemented but wrong:** none found.

---

## Summary

- **Standards:** 5 findings — 1 fixed (test dead code), 2 accepted as in-scope OK, 2 noted as
  out-of-scope deployment follow-ups (fallback remains usable, session stores full user record /
  default creds hashed but unchanged). No correctness or security regression introduced.
- **Spec:** 8/8 acceptance criteria checked with evidence, 0 missing, 0 wrong, 0 deviations.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (T04 baseline) | 5 failed, 81 passed |
| Green (after impl) | **86 passed** (77 prior + 9 T04) |
| After review fix (test tightening) | **86 passed** |
| Baseline snapshot integrity | 2/2 files match `MANIFEST.sha256` |
| Technician delete routes | 1 registered |
| `SESSION_SECRET` env precedence | module value and `SessionMiddleware` secret key both match env in isolated import |
