# 03 — Report loop restoration and dashboard form alignment

- **Status**: resolved
- **Type**: task
- **Depends on**: 02 (resolved) — every save regenerates its QR through `write_qr()`.
- **Spec**: `.scratch/report-loop/spec.md`

## Objective

Make writing a report actually work. Four dashboards post to `POST /save-report`, which does
not exist, so the product's core loop ends in a 404. Restore it as one authenticated handler,
align every form onto it, and keep the QR regenerated on each save.

## Architecture impact

| Component | Change |
|---|---|
| `POST /save-report` | New: auth (admin/secretary), 404 on missing record, report + QR in one commit, post-commit log |
| `POST /save-report-inline` | Deprecated alias on the same function; no second implementation |
| `safe_next_path()` | New helper: local-path-only redirect target with role fallback |
| `templates/doctor.html:69` | `action="/save-report"`, `name="report"`, hidden `next=/doctor` |
| `templates/secretary.html:54` | Same, `next=/secretary` |
| `main.py:481` (archive day, inline) | Same, `next` = the page being viewed |
| `templates/archive_records.html:58` | Same (template is currently dead; aligned to stop drift) |
| `main.py:630` (QR preview) | Form posts to `/save-report` with `next=/secretary/qr-preview/<id>` |
| `tests/conftest.py` | New `secretary_client` fixture |
| `tests/test_report_loop.py` | New |

## Plan

1. Baseline snapshot (`main.py`, three templates, `tests/conftest.py`) + `MANIFEST.sha256`. Done.
2. Write `tests/test_report_loop.py` (red).
3. Add `safe_next_path()` and the unified handler; align four forms.
4. Green, including Ticket 01 + 02 suites.
5. Two-axis review; fix; re-run.

## Risk assessment

**Medium.** The failure mode that matters is silent data loss: a doctor types a report, the
save errors, and the text is gone. Guards:

- Auth is checked **before** any query, so an unauthorised POST cannot even probe for record ids.
- One commit for report + QR, so a record can never point at a QR for a different report.
- `next` is whitelisted to local paths; the fallback is a dashboard that renders the saved report.
- The handler is the only writer of `record.report`; grep proves no other route assigns it.

Rollback: restore the five baseline files. No schema change, so no data migration.

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_admin_saves_report_from_dashboard` | 303 `/doctor`, DB updated, QR filename renewed |
| `test_secretary_saves_report_from_dashboard` | 303 `/secretary`, DB updated |
| `test_save_regenerates_the_signed_qr` | one mint, `testserver` host, token → id |
| `test_technician_cannot_save_report` | 303 `/login`, record untouched |
| `test_anonymous_cannot_save_report` | 303 `/login`, record untouched |
| `test_unknown_record_is_404` | the handler's own 404 detail, not the router's "Not Found" |
| `test_empty_report_clears_the_stored_report` | no 422 |
| `test_local_next_is_honoured` | archive path round-trip |
| `test_unsafe_next_falls_back` | five hostile values |
| `test_no_next_uses_the_role_default` | admin/secretary divergence |
| `test_doctor_dashboard_form_is_aligned` | action + field + next, no `report_text` |
| `test_secretary_dashboard_form_is_aligned` | same |
| `test_archive_day_form_is_aligned` | same, `next` names the day page |
| `test_qr_preview_form_uses_the_unified_endpoint` | action, `next`, new report visible after redirect |
| `test_dead_archive_template_is_aligned_too` | the unused template cannot drift |
| `test_save_is_logged_once` | one INFO line, correct id |
| `test_inline_alias_still_works` | compatibility |
| `test_inline_alias_requires_authorisation` | the old endpoint inherits the new gate |
| `test_alias_shares_one_implementation` | two paths, one function object |

## Deviations

- **`/save-report-inline` kept as an alias** on the same handler (`include_in_schema=False`,
  `deprecated=True`) because Ticket 02 posts to it and open preview tabs may still exist. One
  function object, so it cannot drift.
- **Red-phase (declared, carried through):** QR-capture harness moved from
  `tests/test_qr_tokens.py` to `tests/conftest.py` for reuse; `test_tampered_token_is_refused`
  de-flaked by flipping a middle base64 signature character instead of the padding-carrying last
  character (it failed once during this ticket's red run).
- `safe_next_path` also rejects `javascript:` targets (stricter than the spec's four hostile
  examples, consistent with "local path only").

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (5 files) verified intact; diff in
`.scratch/report-loop/changes.diff`, review in `.scratch/report-loop/review.md`.
Suite: **77 passed** (26 T01 + 27 T02 + 24 T03), up from 23 failed / 54 passed at the T03 red phase.

Shipped:

- `POST /save-report` is the single report writer; `POST /save-report-inline` aliases the same
  function. Auth gate runs **before** any DB read: only `admin`/`secretary` may write, others
  → 303 `/login` with no record mutation (closes the prior unauthenticated inline write path).
- `safe_next_path(next, fallback)`: local-path-only whitelist (rejects non-`/`, `//`, `\`,
  space/control chars); fallback `/doctor` or `/secretary` by role.
- One commit: report + `write_qr()`-regenerated QR filename together, QR minted before commit,
  `logger.info("report: saved record id=%s role=%s", ...)` after commit.
- Forms aligned to `action="/save-report"`, `name="report"`, hidden `next`, no `report_text`:
  `templates/doctor.html`, `templates/secretary.html`, `templates/archive_records.html` (dead,
  aligned), and inline archive-day + QR-preview forms in `main.py`. QR preview now returns to
  `/secretary/qr-preview/<id>`.

## Follow-ups (not this ticket)

1. Report-form contract is duplicated across 3 templates and 2 inline HTML blocks (Shotgun
   Surgery noted in review) — extract a shared partial/macro when inline pages are templatized.
2. If `archive_records.html` is ever wired up, render a concrete day-specific `next` instead of
   the current generic `/doctor/archive`.
3. Global defects unchanged: no CSRF, plaintext passwords, public `/static/uploads`,
   `autoescape=False`, duplicate `/technician/delete/{record_id}` routes.
