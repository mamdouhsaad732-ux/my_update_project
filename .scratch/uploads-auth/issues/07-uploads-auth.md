# 07 — Static uploads PHI access control

- **Status**: resolved
- **Type**: task
- **Depends on**: 02 (resolved, signed patient tokens), 04 (resolved, session auth), 05–06 (resolved) — access control layered on current rendering/auth/token primitives.
- **Spec**: `.scratch/uploads-auth/spec.md`

## Objective

Stop serving patient uploads and QR images as anonymous public static files. Enforce authentication
/ authorization on `/static/uploads/*` and `/static/qrs/*` while preserving legitimate staff and
signed-token patient access.

## Architecture impact

| Component | Change |
|---|---|
| `main.py` static serving | Replace or guard the broad `/static` mount so PHI-bearing subtrees (`uploads`, `qrs`) require authorization; keep non-PHI public assets working |
| AuthZ check | Accept authenticated staff sessions; accept a valid signed patient token for that patient's assets (transport/mechanism defined in implementation) |
| Templates / routes | Adjust asset URLs or rendering as needed so authorized dashboards and the token-based patient page still load their images/QRs |
| `tests/test_uploads_auth.py` | New |

## Plan

1. Baseline snapshot (`main.py`) + `MANIFEST.sha256`. Done.
2. Write `tests/test_uploads_auth.py` (red).
3. Implement guarded serving + authorized URL/token plumbing; keep patient page and dashboards working.
4. Green, including Ticket 01–06 suites.
5. Two-axis review; fix; re-run.

## Risk assessment

**Medium-high.** This touches how browsers fetch embedded assets, so "page loads" and "images load"
can diverge. Guards:

- Tests assert direct file fetches are rejected for anonymous callers and allowed for authorized
  callers/tokens.
- Run full suite to catch template/route regressions (dashboards, patient page, QR preview, archive
  views all reference static assets).
- Prefer preserving existing paths where possible; if query params/tokens are added to URLs, update
  all render sites consistently.

Rollback: restore baseline `main.py` (and any touched templates/routes) — no schema change.

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_anonymous_cannot_fetch_upload` | direct `GET /static/uploads/<file>` rejected |
| `test_anonymous_cannot_fetch_qr` | direct `GET /static/qrs/<file>` rejected |
| `test_admin_can_fetch_upload` | staff session authorized |
| `test_admin_can_fetch_qr` | staff session authorized |
| `test_secretary_can_fetch_protected_assets` | staff session authorized |
| `test_technician_can_fetch_protected_assets` | staff session authorized |
| `test_valid_patient_token_can_fetch_patient_assets` | signed patient token grants access to that record's assets |
| `test_non_phi_static_asset_still_public` | non-protected static content not broken |

## Deviations

- **Token transport added to URLs:** guarded asset requests accept `?patient_token=<token>`;
  `print_record` appends it to patient `dicom_urls` and passes `patient_token` to
  `templates/patient.html`, which appends it to the QR `<img>` src so the token-based patient page
  can load embedded assets. (Known tradeoff: token may appear in history/logs/Referer, but the
  credential is already in the page URL — spec risk.)
- **Static serving segmented:** removed the broad `/static` mount and re-mounted only
  `/static/image` publicly; PHI subtrees served by guarded handlers. Non-PHI assets outside
  `static/image` that were previously public would no longer be catch-all served (none evidenced as
  required). `templates/patient.html` changed (outside the T07 `main.py`-only baseline snapshot) to
  carry the asset token.
- **Review-driven addition:** `test_patient_token_cannot_fetch_other_record_assets` added to pin
  ownership scoping (spec/axis gap); code already enforced it.

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (`main.py`) verified intact; diff in
`.scratch/uploads-auth/changes.diff`, review in `.scratch/uploads-auth/review.md`.
Suite: **111 passed** (102 prior + 9 T07), up from 2 failed / 108 passed at the T07 red phase.

Shipped:

- **Guarded PHI asset endpoints:** `GET /static/uploads/{path}` and `GET /static/qrs/{path}`
  (`_serve_protected_static`, `FileResponse`) replace the public broad mount. Anonymous/unauthorized
  requests rejected (403); missing/unresolvable/non-file → 404. Path containment enforced via
  `_resolve_protected_static_path`.
- **Authorization:** authenticated staff session (any role) allowed; valid signed patient token
  (`?patient_token=`) allowed only for that record's assets (upload path in `image_path`,
  `qr_{id}.png` match). Cross-record token access rejected.
- **Non-PHI assets:** `static/image` remains publicly mounted. Patient page appends the record token
  to embedded asset URLs so token-only viewing still works.

## Follow-ups (not this ticket)

1. Revisit token-in-query transport (history/logs/Referer) with a shorter-lived/path-bound or
   cookie-scoped asset authorization if threat model tightens.
2. Consider least-privilege scoping for staff (role/modality/record) instead of "any session user
   may fetch any protected file".
3. Audit for other non-PHI static paths that may need explicit public mounts now that the broad
   `/static` mount is removed.
4. Broader hardening unchanged: CSP/CSRF.

