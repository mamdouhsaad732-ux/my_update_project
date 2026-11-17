# Spec: Static uploads PHI access control

## Problem

`main.py` mounts the entire `static/` directory publicly:

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

This exposes `static/uploads/` (patient scan files / DICOM-derived images) and `static/qrs/`
(QR PNGs that embed signed patient URLs) to anyone who knows or guesses a path. Uploaded medical
images are PHI; QR images leak the credential that opens a patient record. No authentication or
authorization is enforced on these file fetches.

## Decision

| Concern | Decision |
|---|---|
| Direct access | Requests for PHI-bearing static assets under `/static/uploads/*` and `/static/qrs/*` must not be anonymously retrievable. Unauthenticated/unauthorized requests are rejected (401, 403, or 404) with no file body. |
| Staff access | An authenticated session for any application role (`admin`, `secretary`, `technician`) may retrieve files under `/static/uploads/*` and `/static/qrs/*` needed by dashboards/views. |
| Patient-token access | A valid signed patient token (the credential minted by `mint_patient_token` / used in `/patient/{token}`) may authorize retrieval of that same patient record's assets, so token-based patient views can still load their images/QR. The token transport and ownership check are defined by the implementation (e.g. query parameter or equivalent) and must be exercised by tests. |
| Non-PHI static assets | Public, non-PHI assets outside the protected PHI subtrees (e.g. branding under `static/image/`) must remain loadable without breaking the login/public pages, unless explicitly brought into scope. |
| Implementation shape | Allowed: guarded routes/handlers for the protected paths, middleware, or replacing the broad mount with a combination that preserves non-PHI public assets while protecting PHI paths. Avoid breaking existing URL shapes used by templates/routes where feasible. |

## Scope

- `main.py` (and any minimal template/route adjustments required to keep authorized access working).
- `tests/test_uploads_auth.py`: new.

## Out of scope

- Encrypting files at rest, changing on-disk filenames, or DICOM content redaction.
- CDN/object-storage migration.
- Reworking every template beyond what is necessary to preserve authorized access under the chosen
  token-transport mechanism.
- Full directory-traversal hardening beyond what the chosen static/file-serving mechanism provides
  (but implementations must not introduce path traversal).

## Acceptance criteria

- [ ] Anonymous `GET /static/uploads/<existing file>` is rejected (not 200, no file content served).
- [ ] Anonymous `GET /static/qrs/<existing file>` is rejected (not 200, no file content served).
- [ ] An authenticated `admin` session can retrieve an existing file under `/static/uploads/*` (200) and `/static/qrs/*` (200).
- [ ] An authenticated `secretary` and `technician` session can retrieve protected assets they need (at least `/static/uploads/*` and `/static/qrs/*` return 200 when authenticated).
- [ ] A valid signed patient token can authorize retrieval of that patient's assets (mechanism per implementation, covered by test).
- [ ] Non-PHI public static content required by the app (e.g. files not under protected PHI subtrees) is not broken.
- [ ] Ticket 01–06 suites stay green.

## Risks

- **Breaking the public patient page.** `/patient/{token}` embeds upload and QR URLs; if protection
  requires a token parameter, page rendering/URLs must be updated in lockstep.
- **Over-broad blocking.** Mounting/guarding `/static` wholesale can break login branding or other
  public assets; the spec explicitly preserves non-PHI public content.
- **Token leakage via query strings.** If tokens move to URLs, they may appear in logs/referrers;
  this is a known tradeoff to document if chosen (patient token is already in the page URL).
- **Filename/ownership mapping.** Proving a requested upload belongs to the token's record may
  require lookup; QR filenames include record id (`qr_<id>.png`) which helps scoping.
