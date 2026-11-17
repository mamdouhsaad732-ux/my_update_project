# Ticket 06 — review record

Two-axis review of `.scratch/inline-xss-hardening/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. Spec axis re-ran the suite once (100 passed
before the follow-up tests; 102 passed after).

Baseline integrity at review time: `main.py` in `.scratch/inline-xss-hardening/baseline/` matches
`MANIFEST.sha256`.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern process/domain only. The only standard is the smell baseline.

**Correctness / security (diff-introduced):**

| Finding | Disposition |
|---|---|
| Stored/user-controlled values in touched inline builders escaped with `html.escape(..., quote=True)` in text, attribute, textarea, and URL-derived `next` contexts (`patient_name`, `birth_date`, `report`, `qr_code`, `modality`, `month`, `day`) with `None` → safe defaults | OK |
| No double-escaping observed; `/download-report/{id}` (`application/msword` text, non-HTML) unchanged | OK |

**Residual / out of scope (not regressions):**

- `archive_months` / `archive_days` / `archive_home` nav builders still reflect `modality`/`month`/`day`
  path params without escaping where not touched by this diff. Spec listed nav pages as "escape as
  part of hardening where touched" (defense-in-depth, not stored PHI); `archive_records` (touched)
  now escapes them. Left for a follow-up touching those builders.
- Pre-existing inline f-string page builders remain duplicated/primitive-obessive; minimal local
  escaping was the chosen approach per spec.

**Smells:** duplicated inline HTML builders (pre-existing, unchanged pattern) — not worth fixing
for this ticket.

---

## Spec

**Acceptance criteria** (`.scratch/inline-xss-hardening/spec.md`, walked item by item):

| Criterion | Verdict | Evidence |
|---|---|---|
| `GET /doctor/archive/{modality}/{month}/{day}` renders stored `patient_name` and `report` payloads escaped (no raw `<script>` / raw injected tag) | checked | `archive_records` escapes fields in cells/textarea/attrs/title/links; `test_archive_records_escapes_patient_name`, `test_archive_records_escapes_report` (discriminating) |
| `GET /secretary/qr-preview/{record_id}` renders stored `patient_name`, `modality`/`birth_date` (as displayed), and `report` payloads escaped | checked | code escapes name/birth/modality/report/qr/next; `test_secretary_qr_preview_escapes_patient_name`, `_escapes_report`, `_escapes_birth_date`, `_escapes_modality` (discriminating). **Spec axis noted `birth_date`/`modality` were escaped in code but not test-pinned** — two tests added to close the gap. |
| Normal patient data (Arabic names, plain report text) still renders visibly/correctly on these pages | checked | `test_archive_records_renders_normal_data`, `test_secretary_qr_preview_renders_normal_data` |
| Download-report response format/endpoint remains functional (no HTML-escaping regression introduced into the `.doc` path) | checked | route unchanged; `test_download_report_still_returns_content` |
| Ticket 01–05 suites stay green | checked | full suite 102 passed |

**Behaviour not asked for / deviations:**
- Defense-in-depth escaping of reflected `modality`/`month`/`day` and derived `next`/`qr_code`
  values in the touched `archive_records` builder — consistent with spec ("escape as part of
  hardening where touched"). No template migration, no `/download-report` escaping.
- Added `test_secretary_qr_preview_escapes_birth_date` and `_escapes_modality` after Spec axis
  review to make criterion 2 fully discriminating (code was already correct).

**Implemented but wrong:** none found. No double-escaping, no broken normal text, download path
unmodified.

---

## Summary

- **Standards:** 0 in-scope defects; 1 residual out-of-scope surface noted (untouched nav builders'
  reflected params), 0 regressions.
- **Spec:** 5/5 acceptance criteria checked with discriminating evidence (2 tests added to pin
  `birth_date`/`modality` per axis finding), 0 missing, 0 wrong, 0 deviations.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (T06 baseline) | 4 failed, 96 passed |
| Green (after impl) | **100 passed** (93 prior + 7 T06) |
| After review-driven test additions | **102 passed** |
| Baseline snapshot integrity | `main.py` matches `MANIFEST.sha256` |
| `/download-report` | unchanged, functional |
| Escaping | `html.escape(..., quote=True)` at touched inline interpolation points |
