# Ticket 03 — review record

Two-axis review of `.scratch/report-loop/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. Spec axis re-ran the suite once (77 passed).

Baseline integrity at review time: all five files in `.scratch/report-loop/baseline/` match
`MANIFEST.sha256`. The diff covers `main.py`, the three templates, `tests/conftest.py`, and the
new `tests/test_report_loop.py`; `tests/test_qr_tokens.py` was also modified (harness moved to
`conftest.py`, tamper test de-flaked) and that change is declared in the ticket.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern process/domain only. The only standard is the smell baseline.

**Correctness / security (diff-introduced) — no issues found; hardening observed:**

- `safe_next_path` rejects scheme/`//`, backslash, space/control chars/CRLF, and non-`/`
  targets before redirect (`main.py`); used by the save handler (open-redirect/response-splitting
  guarded).
- Role gate runs **before** the record lookup, so unauthenticated/unauthorised callers get
  303 `/login` without an id-existence oracle; 404 is only for authorised misses.
- `record.qr_code = write_qr(...)` is assigned **before** `db.commit()` and the log is emitted
  **after** commit — a QR failure does not persist a half-saved record/report–QR mismatch.
- `/save-report-inline` aliases the same function and inherits the auth/logging gate, closing the
  prior unauthenticated write path.

**Smells (all judgement calls):**

| Smell | Location | Disposition |
|---|---|---|
| Shotgun Surgery / Duplicated Code (pre-existing, amplified) — report-form contract hand-maintained in 3 templates and 2 inline HTML blocks | `templates/doctor.html`, `secretary.html`, `archive_records.html`, `main.py` archive day + QR preview forms | Deferred — alignment was required by the ticket. Follow-up: shared Jinja partial/macro once inline pages are templatized |
| Primitive Obsession / weak seam (minor) — dead template uses generic `next="/doctor/archive"` while live inline archive uses the day-specific path | `templates/archive_records.html` | Rejected now — template unwired; tests pin alignment. If wired later, render the concrete day path |
| Module-global `_CAPTURED_PAYLOADS` in the QR harness | `tests/conftest.py` | Rejected — isolated by the `captured_qr` fixture today; parallel runs not in scope. Smallest follow-up: store on the fixture/closure |

---

## Spec

**Acceptance criteria** (`.scratch/report-loop/spec.md`, walked item by item):

| Criterion | Verdict | Evidence |
|---|---|---|
| Admin save → 303 `/doctor`, report persisted | checked | `save_report`, `test_admin_saves_report_from_dashboard` |
| Secretary save → 303 `/secretary`, report persisted | checked | `test_secretary_saves_report_from_dashboard` |
| Technician & anonymous → 303 `/login`, record unchanged | checked | gate before query; `test_technician_cannot_save_report`, `test_anonymous_cannot_save_report` (and alias variant) |
| Unknown `record_id` → 404, not 500 | checked | handler detail `السجل غير موجود`; `test_unknown_record_is_404` |
| Save regenerates signed QR via `write_qr`, token verifies to id | checked | `test_admin_saves_report_from_dashboard`, `test_save_regenerates_the_signed_qr` |
| Empty report clears (no 422) | checked | `Form("")`; `test_empty_report_clears_the_stored_report` |
| `next` honoured for local paths, ignored for hostile values | checked | `safe_next_path`; `test_local_next_is_honoured`, `test_unsafe_next_falls_back` (5 values, incl. `javascript:` — stricter, aligned with "local path only") |
| No `next` → role default | checked | `test_no_next_uses_the_role_default` |
| All forms aligned (`action`, `name="report"`, hidden `next`, no `report_text`) incl. dead template & QR preview | checked | all three templates + inline archive + QR preview; form-alignment tests incl. `test_dead_archive_template_is_aligned_too` |
| Saving from QR preview returns to preview with new report | checked | `test_qr_preview_form_uses_the_unified_endpoint` |
| Exactly one save log line | checked | log after commit; `test_save_is_logged_once` |
| `/save-report-inline` still works as alias | checked | `test_inline_alias_still_works`, `test_inline_alias_requires_authorisation`, `test_alias_shares_one_implementation` |
| Ticket 01 (26) and Ticket 02 (27) suites stay green | checked | full suite 77 passed |

No criterion is satisfied only by a non-discriminating/baseline-passing test: baseline lacked
`/save-report`, used `report_text`/inline action, and had no auth/log/single-commit contract.

**Behaviour not asked for / deviations:**
- Declared in ticket: QR-capture harness moved to `tests/conftest.py` and
  `test_tampered_token_is_refused` de-flaked (middle signature char, not padding bit). No other
  scope creep; `javascript:` rejection is stricter-than-spec but consistent with "local path only".

**Implemented but wrong:** none found. Auth precedes DB read, alias is the same function object,
one commit, QR minted before commit, log after commit.

**Defensive hardening applied after Spec axis:** added `name="next"` assertion to
`test_dead_archive_template_is_aligned_too` for parity with the "hidden `next`" criterion.

---

## Summary

- **Standards:** 3 judgement-call smells noted — 0 fixed, 3 deferred/rejected as out of scope.
  No correctness or security defects in the diff; the change closes the prior unauthenticated
  `/save-report-inline` write path.
- **Spec:** 13/13 acceptance criteria checked with evidence, 0 missing, 0 wrong, 1 declared
  deviation (T02 harness/flake fix, pre-recorded), 1 small defensive assertion added.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (before impl, after T03 tests) | 23 failed, 54 passed |
| Green (after impl) | **77 passed** (26 T01 + 27 T02 + 24 T03) |
| After review hardening | **77 passed** |
| Baseline snapshot integrity | 5/5 files match `MANIFEST.sha256` |
| No `report_text` remains | none in `main.py` or `templates/*.html` |
| App imports | routes registered, no import error |
