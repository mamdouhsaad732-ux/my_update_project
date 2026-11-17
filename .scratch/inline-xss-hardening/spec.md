# Spec: Inline HTML f-string routes XSS mitigation

## Problem

Ticket 05 enabled autoescaping for the Jinja `Environment` used by template-backed routes, but
several routes in `main.py` construct HTML by interpolating values directly into Python f-strings
and return it with `HTMLResponse(...)`. User-controlled and stored patient data (names, birth
dates, modalities, reports) is emitted raw in these responses, so stored XSS payloads execute even
after Ticket 05.

## Inventory (HTML responses built from f-strings)

| Route / function | Access | Interpolated patient data | Notes |
|---|---|---|---|
| `GET /doctor/archive/{modality}/{month}/{day}` (`archive_records`) | admin | `record.patient_name`, `record.birth_date`, `record.report`, `record.qr_code`/ids in table/textarea/attrs | Primary stored-XSS surface (rows rendered into a large HTML document). |
| `GET /secretary/qr-preview/{record_id}` (`secretary_qr_preview`) | secretary | `record.patient_name`, `record.birth_date`, `record.modality`, `record.report`, ids/qr filename | Primary stored-XSS surface (title, text, textarea, image src). |
| Archive navigation pages (`archive_home`, `archive_months`, `archive_days`) | admin | path segments `modality`/`month`/`day` reflected into headings/links | User-controlled URL components, not stored PHI; escape as part of hardening where touched. |
| Error handlers in these routes | admin/secretary | `str(e)`/tracebacks | Information disclosure / reflected content, not stored patient PHI — out of scope except avoid making worse. |

**Not in scope here:** `GET /download-report/{record_id}` returns `application/msword` text content
(not rendered as HTML); escaping `<`/`>` would corrupt the document format. The generic 404/500
HTML fragments that do not interpolate patient fields are also out of scope.

## Decision

| Concern | Decision |
|---|---|
| Escaping | Escape all untrusted/patient-controlled values before interpolating into HTML text, attribute, and textarea contexts (e.g. `html.escape(value, quote=True)` or a small helper). `None` must render as a safe empty/default string. |
| Approach | Prefer minimal, local escaping inside existing f-string builders; migrating whole pages to Jinja templates is allowed only if clearly equivalent and low-risk, but not required. |
| Correctness | Escaping must neutralize `<script>`, tag injection, and event-handler payloads in HTTP HTML responses while preserving normal/Arabic text and existing page structure/actions. |
| Scope boundary | Do not change the download `.doc` content encoding/format; do not refactor unrelated routes. |

## Scope

- `main.py`: escape patient/user-controlled interpolations in the inline HTML routes listed above
  (at minimum `archive_records` and `secretary_qr_preview`).
- `tests/test_inline_xss.py`: new.

## Out of scope

- `/download-report` (non-HTML response) and other non-HTML outputs.
- CSP, CSRF, input sanitization at write time, or WYSIWYG/report markup.
- Broader template migration of all inline pages beyond what is necessary to escape safely.

## Acceptance criteria

- [ ] `GET /doctor/archive/{modality}/{month}/{day}` renders stored `patient_name` and `report` payloads escaped (no raw `<script>` / raw injected tag) in the HTML response.
- [ ] `GET /secretary/qr-preview/{record_id}` renders stored `patient_name`, `modality`/`birth_date` (as displayed), and `report` payloads escaped in the HTML response.
- [ ] Normal patient data (Arabic names, plain report text) still renders visibly/correctly on these pages.
- [ ] Download-report response format/endpoint remains functional (no HTML-escaping regression introduced into the `.doc` path).
- [ ] Ticket 01–05 suites stay green.

## Risks

- **Double-escaping or broken attributes/textarea content** if escaping is applied in the wrong
  context or twice. Use a single, consistent escape at interpolation points.
- **Missed interpolation sites** inside large f-string blocks; tests must target the actual fields
  rendered by each route.
- **Path parameters reflected in archive pages**: escaping them is safe defense-in-depth but tests
  focus on stored patient data per objective.
