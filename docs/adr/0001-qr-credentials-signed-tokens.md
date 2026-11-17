# Patient QR codes carry a signed token, not a database ID

**Status:** accepted · 2026-11-14

Patient QR codes encode `/patient/<signed-token>` instead of `/patient/<id>`. The patient page
is deliberately public — a patient scans a printed label with no login — but record IDs are
sequential, so `/patient/1`, `/2`, `/3` let anyone walk the archive and read names, birth dates,
reports and images. Signing the ID with `itsdangerous` under `salt="qr-v1"` makes a URL
unforgeable without changing the schema, which is decisive here: this project has no migration
tooling and `Base.metadata.create_all()` never alters an existing table. A stored opaque token
per record is the stronger design, but obtaining it means altering a live SQLite table that
already contains patient data.

## Considered options

- **Stored UUID4 per record — rejected for now.** Truly opaque and revocable per record, but it
  needs `ALTER TABLE`, a backfill, and a unique index on a database holding PHI with no safe
  migration path. Revisit when a migration story exists.
- **HMAC of the ID — rejected.** Same secret dependency, no expiry, and the ID stays in the
  clear; strictly less capable than signing for equal cost.
- **Short-lived signed links — rejected.** QR labels are printed and physical. An expiring link
  converts a security control into a support queue.
- **Route-by-obscurity (random paths, no signature) — rejected.** Not verifiable server-side,
  and collisions and orphans become a data problem rather than a signature check.

## Consequences

- A signed token is **unguessable, not opaque**: its payload is base64 JSON, so whoever holds a
  token can read the record ID from it. The threat model is enumeration, not photography.
- Rotating `QR_SIGNING_SECRET` invalidates every printed QR at once. Per-record revocation needs
  a `token_version` column and therefore a migration; until then, revocation means reprinting.
- Tokens never expire (`max_age=None`), because printed labels outlive any sensible TTL.
- Legacy `/patient/<int>` URLs stay routable behind `LEGACY_PATIENT_URLS` (default on) until
  existing labels age out. Each legacy hit is logged, so the flag can be retired on evidence
  rather than on a guess.
- QR minting collapses into one helper, `write_qr()`. Two competing implementations previously
  existed (one encoding `/view-scan/<id>`, one encoding a hardcoded production host), and the
  later definition silently won.
