# 02 — QR credentials: signed patient URLs

- **Status**: resolved
- **Type**: task
- **Depends on**: 01 (resolved) — the DB seam and per-insert timestamps this builds on.
- **Spec**: `.scratch/qr-credentials/spec.md` · **Decision**: `docs/adr/0001-qr-credentials-signed-tokens.md`

## Objective

Make the QR code the credential. Replace the enumerable `/patient/<id>` with a signed token,
keep legacy integer URLs working behind a flag, and collapse the two conflicting QR-minting
implementations into one helper.

## Architecture impact

| Component | Change |
|---|---|
| Token layer | New: `QR_TOKEN_SALT`, `qr_signing_secret()`, `mint_patient_token()`, `read_patient_token()`, `patient_url()` |
| QR writer | New `write_qr(record_id, base_url)`; both call sites use it; shadowed `generate_patient_qr` at `main.py:791-806` deleted |
| `GET /patient/{token}` | Accepts a signed token; digits handled by the legacy policy; bad signature → 404 |
| `GET /technician/upload` | Payload built by `write_qr()` instead of inline (`main.py:679-685`) |
| `POST /save-report-inline` | Regenerates via `write_qr()` with `request.base_url`, not the hardcoded Render host (`main.py:610`) |
| Config | New `QR_SIGNING_SECRET` (fallback: session secret), `LEGACY_PATIENT_URLS` (default on), both read per call |
| Tests | New `tests/test_qr_tokens.py` |

## Plan

1. Baseline snapshot of `main.py` → `.scratch/qr-credentials/baseline/` + `MANIFEST.sha256`.
2. Write `tests/test_qr_tokens.py` (red).
3. Implement the token layer and `write_qr()`; rewrite the `/patient/{token}` handler; replace
   both QR call sites; delete the duplicate definition.
4. Re-run the suite (green), including Ticket 01's 26 tests.
5. Phase 3 two-axis review; fix; re-run.

## Risk assessment

**Medium-low.** Three things can break, each with a named guard:

- *Printed labels stop working.* Guarded by `LEGACY_PATIENT_URLS` (default on) and a log line per
  legacy hit, so the flag is retired on evidence.
- *QR payloads grow past a scan-friendly size.* Guarded by `QRCode(..., fit=True)` and a payload
  assertion on length.
- *A tampered or shortened token 500s.* Guarded by catching the signature errors and returning
  404 — asserted explicitly, because a 500 here leaks that the token was well-formed enough to
  parse.

Rollback: restore `main.py` from `baseline/`; no schema, no data change, so no migration to undo.

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_minted_token_round_trips` | token ↔ id |
| `test_token_is_not_the_raw_id` | not `"42"`, single URL-safe path segment |
| `test_patient_url_builds_a_verifying_link` | trailing-slash normalisation, token verifies |
| `test_signed_token_opens_the_patient_page` | 200, record content rendered |
| `test_tampered_token_is_refused` | 404, not 500/422 |
| `test_token_for_unknown_record_is_404` | valid signature, absent record |
| `test_legacy_numeric_url_redirects_when_enabled` | 303 → signed URL → 200 |
| `test_legacy_numeric_url_is_404_when_disabled` | flag off |
| `test_secret_change_invalidates_tokens` | env read per call |
| `test_upload_qr_payload_is_a_signed_patient_url` | one writer, correct host |
| `test_report_save_qr_payload_is_a_signed_patient_url` | kills the Render hardcode |
| `test_write_qr_returns_the_expected_filename` | `qr_<id>.png` on disk |

## Deviations to report

- None expected. If `itsdangerous` needs a pin in `requirements.txt`, say so rather than adding
  it silently: it is currently only a transitive dependency of `SessionMiddleware`.

## Resolution

**Resolved 2026-11-14.** `main.py` → `3cb70d59…` (baseline `df5b0674…`, diff in
`.scratch/qr-credentials/changes.diff`, review in `.scratch/qr-credentials/review.md`).
Suite: **53 passed** (26 Ticket 01 + 27 Ticket 02), up from a red phase of 19 failed / 2 passed.
No schema change, no data migration.

Shipped:

- `QR_TOKEN_SALT = "qr-v1"`, `qr_signing_secret()` (env read per call, session-secret
  fallback), `mint_patient_token()`, `read_patient_token()`, `patient_url()`, `write_qr()`,
  `legacy_patient_urls_enabled()`, `legacy_record_id()`.
- `GET /patient/{identifier}`: signed token → 200/404; ASCII-convertible digits →
  303 relative redirect + one INFO line; flag off → 404; anything else → 404, never 500.
- Upload and `/save-report-inline` both mint through `write_qr()` with `request.base_url`.
  The hardcoded `al-pacs-system-1.onrender.com` and both `generate_patient_qr` definitions are
  gone.
- Startup warning when `QR_SIGNING_SECRET` is unset.

Review fixes applied (details in `review.md`): 500 on Unicode numeric identifiers; absolute
redirect derived from an attacker-controllable `Host`; unclosed test session; weak
garbage-token assertions; AC 11 and AC 6 had no route-level test.

## Deviations

1. **`itsdangerous` is now a direct import.** The ticket's "currently only a transitive
   dependency" premise was stale: `requirements.txt` already listed it (unpinned, like every
   other dependency), so nothing was added silently and no pin was proposed. Flagged here as
   the ticket required.
2. **`PURGE_TRUTHY_VALUES` → `TRUTHY_VALUES`.** Reusing the constant for
   `legacy_patient_urls_enabled()` left the old name lying about its contents. No behaviour
   change.
3. **`SESSION_SECRET` extracted** from the inline `SessionMiddleware` literal so the QR fallback
   and the cookie signer provably share one value.

## Follow-ups (not this ticket)

1. **Before setting `LEGACY_PATIENT_URLS=false`:** replace the numeric patient links in
   `main.py:481`, `templates/doctor.html:77`, and `templates/archive_records.html:67` with
   signed URLs, or flipping the flag 404s the app's own buttons.
2. **Ticket 04:** remove the hardcoded session secret, then require `QR_SIGNING_SECRET`. Until
   then a deployment without the env var signs QR tokens with a secret published in this repo
   (warned at startup).
3. No backfill for rows whose QR PNG predates this change; they hold the old payload until
   re-saved or reprinted.

