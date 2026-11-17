# Ticket 02 — review record

Two-axis review of `.scratch/qr-credentials/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. The Spec axis re-ran the suite
(47 passed at review time) and walked every acceptance criterion in `spec.md` individually.

Baseline integrity at review time: `baseline/main.py` still hashes to
`df5b0674…`, matching `MANIFEST.sha256`, so the diff is a trustworthy record of what changed.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern issue/ADR process only. The only standard is the smell baseline.

**Smells found (all judgement calls):**

| Smell | Location | Disposition |
|---|---|---|
| Duplicated Code — `str(request.base_url)` at three call sites | `main.py:655`, `:775`, `:828` | Rejected — the spec pins `write_qr(record_id, base_url)`; passing `Request` in would couple the writer to HTTP |
| Data Clumps — `(record_id, base_url)` travels through two functions | `:114-125` | Rejected — two call sites do not justify a type |
| Speculative Generality — monkeypatched `qrcode.make`, which `write_qr` never calls | `tests/test_qr_tokens.py:61` | **Fixed** — dead hook deleted |
| Mysterious Name — route param `identifier` hides "token or legacy digits" | `:820` | **Fixed** — legacy branch extracted to `legacy_record_id()`, so the dual meaning is named |
| Missing separation between routes / class | `:811`, `:141` | **Fixed** — blank lines restored |
| `itsdangerous` unpinned | `requirements.txt:7` | Rejected — already listed unpinned before this change; every sibling is unpinned |

**Correctness / security findings:**

| Finding | Disposition |
|---|---|
| `'²'.isdigit()` is true but `int('²')` raises → **500** on `/patient/²`; likewise >4300 digits. Contradicts "never 500" | **Fixed** — `legacy_record_id()` converts inside `try/except ValueError`; three regression params |
| Legacy redirect built an absolute `Location` from `request.base_url`; `ProxyHeadersMiddleware(trusted_hosts="*")` and no `TrustedHostMiddleware` make `Host`/`X-Forwarded-Host` attacker-controlled, so the 303 carried a valid token to an arbitrary host | **Fixed** — relative `Location`, asserted to have no netloc |
| `QR_SIGNING_SECRET` unset in deployment falls back to a secret published in this repo, so tokens are forgeable; the docstring's "unforgeable" overclaimed | **Fixed as far as code can** — import-time `logger.warning` names the consequence; docstring now says "unforgeable without the QR secret". The config itself is Ticket 04 |
| Test opened a session it never closed; `finally` closed a different one | **Fixed** — single `session` variable closed in `finally` |

---

## Spec

**Missing / partial (all fixed):**

1. AC 4 "never 500 or 422" — the token branch was safe, the legacy branch 500'd on Unicode
   digits. → **Fixed** + `test_unconvertible_numeric_identifiers_are_404`.
2. AC 6 "unset **or** true → 303" — "unset" was only checked on the helper, never through
   `GET`. → **Fixed**: `test_legacy_numeric_url_redirects_when_flag_is_unset`.
3. AC 11 "only one implementation remains" had **no test**. → **Fixed**:
   `test_no_shadowed_qr_writer_remains` asserts `generate_patient_qr` is gone; it fails on the
   baseline.
4. `test_garbage_tokens_are_404_not_500` accepted `(404, 307)` and let `"12345"` pass by riding
   the default-on legacy flag into a 404. → **Fixed**: numeric input removed from that test,
   statuses pinned to 404.
5. The ticket promises "redirecting to the signed URL **with logging**", but nothing asserted
   the log line — the same shape of defect Ticket 01's review found. → **Fixed**:
   `test_legacy_hit_is_logged_once` pins exactly one hit and the record id; deleting the
   `logger.info` call fails it.

**Scope creep (declared, kept):**

- `PURGE_TRUTHY_VALUES` → `TRUTHY_VALUES` and `SESSION_SECRET` extraction. Both are forced by
  reusing the constant and by the secret fallback; no behaviour change, Ticket 01 suite green.
- `itsdangerous` is now a direct import. It was already in `requirements.txt`, so nothing was
  added silently — but the ticket's "currently only transitive" premise is stale. Recorded in
  the Resolution.

**Implemented but wrong — deferred with a named blocker:**

- The app's own UI still emits numeric links: `main.py:481` (doctor table), 
  `templates/doctor.html:77`, `templates/archive_records.html:67`. It matters only at
  retirement time: flipping `LEGACY_PATIENT_URLS=false` would 404 the app's own buttons. Those
  links are behind authenticated doctor/archive sessions, so the public enumeration threat the
  ticket targets is unaffected. → **Deferred**: listed as the first prerequisite for retiring
  the flag. Fixing them means computing tokens inside two templates, which is a separate,
  reviewable change.
- Existing rows keep the QR PNG they were minted with; no backfill. Out of scope by the spec.

---

## Summary

- **Standards:** 9 findings — 5 fixed, 3 rejected with reason, 1 recorded as a deployment
  prerequisite. Worst: a 500 reachable through `/patient/²`, and a Host-derived absolute redirect.
- **Spec:** 8 findings — 6 fixed, 1 deferred with a named blocker (UI numeric links at flag
  retirement), 1 declared deviation (constant reuse). Worst: AC 11 had no test at all, and AC 4
  was only half-true.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (baseline) | 19 failed, 2 passed |
| Green (working) | 47 passed |
| Green (after review fixes) | **53 passed** |
| Mutation: drop `int()` guard | 3 failed — Unicode/long-digit regression tests discriminate |
| Mutation: absolute redirect | 1 failed — relative-Location assertion discriminates |
| Mutation: cache the serializer at import | 1 failed — per-call secret read is pinned |
| Mutation: default `LEGACY_PATIENT_URLS=false` | 2 failed — helper and route both pinned |
| Mutation: drop `BadData` from the except tuple | 1 failed — tampered token really 500s without it |
| Mutation: delete the legacy-hit log line | 1 failed — the audit line is pinned too |
| Restore after mutations | `main.py` hash unchanged (`3cb70d59…`), suite 53 passed |
| Baseline snapshot integrity | `df5b0674…` matches `MANIFEST.sha256` |
| Import-time warning | fires with `QR_SIGNING_SECRET` unset, names the consequence |
