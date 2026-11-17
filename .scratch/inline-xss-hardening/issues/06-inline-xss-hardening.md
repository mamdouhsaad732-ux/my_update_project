# 06 — Inline HTML f-string routes XSS mitigation

- **Status**: resolved
- **Type**: task
- **Depends on**: 05 (resolved) — extends XSS hardening to routes that bypass the Jinja autoescape
  environment.
- **Spec**: `.scratch/inline-xss-hardening/spec.md`

## Objective

Neutralize stored XSS in inline f-string HTML responses (`archive_records`, `secretary_qr_preview`,
and related inline builders) by escaping untrusted/patient data before interpolation, while keeping
normal content and existing flows intact.

## Architecture impact

| Component | Change |
|---|---|
| `main.py` — `archive_records` (doctor archive day page) | Escape patient fields interpolated into row/cell/textarea HTML |
| `main.py` — `secretary_qr_preview` | Escape patient fields interpolated into title/body/textarea HTML |
| `main.py` — other inline HTML builders as needed | Escape reflected path params / shared helper if introduced |
| `tests/test_inline_xss.py` | New |

## Plan

1. Baseline snapshot (`main.py`) + `MANIFEST.sha256`. Done.
2. Write `tests/test_inline_xss.py` (red).
3. Add/apply HTML escaping at inline interpolation points; verify download-report unchanged.
4. Green, including Ticket 01–05 suites.
5. Two-axis review; fix; re-run.

## Risk assessment

**Medium.** Inline builders are large f-strings with many interpolation sites; a missed site leaves
XSS, and over/incorrect escaping can break forms or display. Guards: inventory-driven edits, tests
pinning the exact stored fields per route, full-suite run.

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_archive_records_escapes_patient_name` | admin archive day page shows escaped name, no raw script |
| `test_archive_records_escapes_report` | report in textarea/cell escaped |
| `test_secretary_qr_preview_escapes_patient_name` | QR preview escapes name |
| `test_secretary_qr_preview_escapes_report` | QR preview escapes report payload |
| `test_archive_records_renders_normal_data` | Arabic/plain text still visible |
| `test_secretary_qr_preview_renders_normal_data` | normal data still visible |
| `test_download_report_still_returns_content` | download endpoint functional, not broken by HTML escaping |

## Deviations

- None. `/download-report` was not HTML-escaped (non-HTML response) and no routes were migrated to
  templates. Defense-in-depth escaping of reflected path params / `next` / `qr_code` in the touched
  `archive_records` builder is consistent with spec ("escape as part of hardening where touched").
- **Review-driven additions (not a deviation):** added `test_secretary_qr_preview_escapes_birth_date`
  and `test_secretary_qr_preview_escapes_modality` after Spec axis found those spec-listed displayed
  fields were escaped in code but not discriminatingly pinned by tests.

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (`main.py`) verified intact; diff in
`.scratch/inline-xss-hardening/changes.diff`, review in `.scratch/inline-xss-hardening/review.md`.
Suite: **102 passed** (93 prior + 9 T06), up from 4 failed / 96 passed at the T06 red phase.

Shipped:

- **`archive_records` (`/doctor/archive/{modality}/{month}/{day}`):** escaped `patient_name`,
  `birth_date`, `report`, `qr_code`, reflected `modality`/`month`/`day`, and derived `next` in
  inline f-string HTML via `html.escape(..., quote=True)` with safe defaults for `None`.
- **`secretary_qr_preview` (`/secretary/qr-preview/{record_id}`):** escaped `patient_name`,
  `birth_date`, `modality`, `report`, `qr_code`, and `next`.
- **`/download-report/{id}`:** unchanged (raw `application/msword` content).

## Follow-ups (not this ticket)

1. Escape reflected path params in untouched inline nav builders (`archive_home/months/days`) and
   any remaining inline f-string HTML that interpolates untrusted values.
2. Consider migrating large inline HTML builders to Jinja templates to reduce duplication and make
   escaping harder to miss.
3. Broader hardening unchanged: CSP/CSRF, public `/static/uploads`.

