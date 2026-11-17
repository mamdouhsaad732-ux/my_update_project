# Spec: QR credentials — signed patient URLs

## Problem

`GET /patient/{record_id}` (`main.py:775-790`) is public by design: a patient scans a printed
QR label with no login. The URL contains the sequential primary key, so `/patient/1`, `/2`,
`/3` enumerate the entire archive — patient name, birth date, modality, report text, every
image, and the QR itself.

Seen in the review for Ticket 01: QR minting is duplicated and contradictory. `generate_patient_qr`
is defined twice (`main.py:580-594`, `main.py:791-806`); the second shadows the first, so the
upload path (which builds its payload inline at `main.py:679-685`) and the report-save path
(`main.py:610`) end up pointing at different hosts — one at `request.base_url`, one at a
hardcoded `https://al-pacs-system-1.onrender.com`.

## Decision

ADR-0001: sign the record ID with `itsdangerous`, salt `qr-v1`, and encode
`/patient/<token>`. No schema change.

Approved parameters:

| Question | Decision |
|---|---|
| Legacy URLs | Keep `GET /patient/<int>` working behind `LEGACY_PATIENT_URLS`, **default on**, redirecting (303) to the signed URL and logging each hit |
| Minting | One `write_qr(record_id, base_url)` used by upload and report-save; the shadowed duplicate is deleted |
| Expiry | None (`max_age=None`) — printed labels cannot expire |
| Secret | `QR_SIGNING_SECRET` env, falling back to the session secret, read **per call** so rotation needs no reload |
| Threat model | Stop enumeration only. Not "stop someone who photographs a QR" |

## Scope

- `main.py`: `QR_TOKEN_SALT`, `qr_signing_secret()`, `mint_patient_token()`,
  `read_patient_token()`, `patient_url()`, `write_qr()`, `legacy_patient_urls_enabled()`;
  `/patient/{token}` resolves signed tokens and handles legacy numerics; upload and
  report-save both call `write_qr()`.
- `tests/test_qr_tokens.py`: new.
- `docs/adr/0001-qr-credentials-signed-tokens.md`: written.

## Out of scope

- Making the patient page require a login (contradicts the printed-QR workflow).
- Per-record revocation (`token_version` column) — needs a migration path.
- Authenticating `/save-report-inline` (Ticket 04). This ticket touches that handler only to
  route its QR through `write_qr()`.
- Rate limiting, audit trail, `noindex` headers.
- Changing `/view-scan/{id}` (admin-only, unchanged).

## Acceptance criteria

- [ ] `mint_patient_token(id)` → `read_patient_token()` round-trips to the same integer.
- [ ] `patient_url(id, base)` returns `{base}/patient/<token>`, with a single trailing slash
      normalised, and the token verifies to `id`.
- [ ] `GET /patient/<valid token>` renders the patient page (200) for that record.
- [ ] `GET /patient/<tampered token>` → 404, never 500 or 422.
- [ ] `GET /patient/<valid token for a missing record>` → 404.
- [ ] `LEGACY_PATIENT_URLS` unset/true: `GET /patient/7` → 303 to the signed URL, which then
      returns 200.
- [ ] `LEGACY_PATIENT_URLS=false`: `GET /patient/7` → 404.
- [ ] Changing `QR_SIGNING_SECRET` invalidates a previously minted token (404).
- [ ] Upload and report-save QR payloads both point at `{request base}/patient/<token>`, and the
      token verifies to the record's id.
- [ ] `write_qr()` returns `qr_<id>.png` and writes `static/qrs/qr_<id>.png`.
- [ ] Only one QR-minting implementation remains; the shadowing duplicate is gone.
- [ ] Ticket 01 suite stays green (26 tests).

## Risks

- **Old printed QRs.** Mitigated by the legacy route and its log line; the flag is the escape
  hatch in both directions.
- **Token length.** A signed token is ~60-90 chars; `QRCode(version=2, fit=True)` keeps labels
  scannable. Verified by the existing `fit=True` behaviour.
- **Secret coupling.** Until Ticket 04, the fallback secret is the hardcoded session secret, so
  rotating it silently invalidates QRs. Documented in ADR-0001 and in the handler docstring.
