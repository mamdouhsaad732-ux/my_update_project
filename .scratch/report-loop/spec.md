# Spec: Report loop restoration

## Problem

The product's core loop is: technician uploads a scan → doctor writes a report → the record gets
a QR code. The middle step is broken.

Four forms post to `POST /save-report`:

| Form | File | Field |
|---|---|---|
| doctor dashboard | `templates/doctor.html:69` | `report_text` |
| secretary dashboard | `templates/secretary.html:54` | `report_text` |
| archive day page | `main.py:481` (inline HTML) | `report_text` |
| archive day page, dead template | `templates/archive_records.html:58` | `report_text` |

**No such route exists.** Every one of those submissions is a 404, and no test notices.

The only working save path is `POST /save-report-inline` (`main.py:648-667`), reachable only from
the secretary QR preview page. It has three problems of its own:

1. **No authentication.** Anyone who can reach the app can rewrite any patient's report by
   POSTing `record_id` and `report`. This is the same defect class as the unauthenticated
   delete routes.
2. **Wrong field name.** It requires `report`; every dashboard form sends `report_text`. Adding
   the missing route naively would turn four 404s into four 422s.
3. **It commits twice** (report, then QR filename) and always redirects to the secretary preview,
   even if the form was submitted from the doctor's dashboard.

`templates/archive_records.html` is not loaded by any route — the live archive page is inline
HTML in `main.py:460-541`. It is aligned anyway so the two do not drift further.

## Decision

One canonical handler, `POST /save-report`, used by every form in the app. `/save-report-inline`
is kept as a deprecated alias on the same function (`include_in_schema=False`) so a browser tab
holding the old preview page still works; it costs one decorator, not a second implementation.

| Concern | Decision |
|---|---|
| Auth | `admin` or `secretary` may save; anything else → 303 `/login` and **no write** (same convention as `/doctor`, `/secretary`, `/view-scan`) |
| Fields | `record_id` (required), `report` (optional, empty allowed — a report must be clearable), `next` (optional local path) |
| Field alignment | Every form sends `name="report"`; `report_text` disappears from the codebase |
| Redirect | `next` when it is a local path, else `/doctor` for admin and `/secretary` for secretary, always 303 |
| `next` safety | Local path only: must start with `/`, must not start with `//`, must contain no backslash, space, or control character. Rejected values fall back silently rather than erroring |
| Missing record | 404 (same message as before) |
| QR | Regenerated on every successful save through `write_qr(record.id, str(request.base_url))` — the single writer from ADR-0001 |
| Commit | One commit for report + QR filename; log **after** the commit (the Ticket 01 lesson) |
| Logging | One INFO line per save: `report: saved record id=<id> role=<role>` |
| QR preview | Its form posts to `/save-report` with `next=/secretary/qr-preview/<id>`, so saving returns to the page it came from |

## Scope

- `main.py`: new `POST /save-report` (alias `/save-report-inline`), `safe_next_path()`,
  alignment of the inline archive form, QR preview form action/`next`.
- `templates/doctor.html`, `templates/secretary.html`, `templates/archive_records.html`: form
  action, field name, hidden `next`.
- `tests/test_report_loop.py`: new.
- `tests/conftest.py`: `secretary_client` fixture.

## Out of scope

- **CSRF tokens.** No route in the app has one; adding it to this form alone would be theatre.
  Recorded as a known global defect.
- **Password hashing / session hardening.** Ticket 04.
- **Authenticating `/download-report`** (it checks for a session but any role passes) and the
  duplicate `/technician/delete/{record_id}` definitions (`main.py:550`, `main.py:793`; the first
  shadows the second).
- Autoescaping (`env` is built with `autoescape=False`) and the public `/static/uploads` mount.
- Moving the inline archive page into `archive_records.html`.

## Acceptance criteria

- [ ] `POST /save-report` as admin with `record_id` + `report` → 303, report persisted.
- [ ] `POST /save-report` as secretary → 303, report persisted.
- [ ] Technician and anonymous submitters → 303 `/login`, record byte-identical.
- [ ] Unknown `record_id` → 404, not 500.
- [ ] A successful save regenerates `qr_<id>.png` through `write_qr`, stores its filename, and the
      payload's token verifies to that record id.
- [ ] An empty `report` clears the stored report (no 422).
- [ ] `next` is honoured for local paths (`/doctor/archive/CT/2026-11-14`) and ignored for
      `https://evil.test/`, `//evil.test/x`, `/\evil.test`, and values containing control characters.
- [ ] With no `next`, admin lands on `/doctor` and secretary on `/secretary`.
- [ ] Doctor dashboard, secretary dashboard, archive day page, and QR preview all render a form
      with `action="/save-report"`, `name="report"`, and a hidden `next`; none renders `report_text`.
- [ ] Saving from the QR preview returns to that preview and shows the new report.
- [ ] Exactly one save log line per successful save.
- [ ] `/save-report-inline` still works as an alias (one implementation, two paths).
- [ ] Ticket 01 (26) and Ticket 02 (27) suites stay green.

## Risks

- **A doctor loses a typed report when the redirect changes.** Mitigated by honouring `next`;
  the fallback only applies when `next` is absent or unsafe.
- **Open redirect via `next`.** Mitigated by the local-path whitelist, tested with four hostile
  values.
- **Double commit removed.** If `write_qr` raises (disk full), nothing is committed and the
  report edit is lost rather than half-saved. Accepted: a visible error beats a record whose
  report and QR disagree.
- **Alias drift.** The alias shares the function object, so it cannot drift.
