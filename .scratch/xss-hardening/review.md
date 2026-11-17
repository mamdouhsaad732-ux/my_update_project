# Ticket 05 — review record

Two-axis review of `.scratch/xss-hardening/changes.diff` (baseline vs working tree).
Both axes ran as parallel fresh-context sub-agents. Spec axis re-ran the suite once (93 passed).

Baseline integrity at review time: `main.py` and all 10 `templates/*` files in
`.scratch/xss-hardening/baseline/` match `MANIFEST.sha256` (11 entries). Templates are unchanged.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern process/domain only. The only standard is the smell baseline.

**Correctness / security (diff-introduced):**

| Finding | Disposition |
|---|---|
| Active render path `env = Environment(..., autoescape=select_autoescape(["html","xml"]))` (`main.py`) correctly autoescapes template output | OK |
| No `| safe` / `{% autoescape %}` added; user-controlled PHI fields remain escaped. Pre-existing `| safe` use is limited to `templates/view_scan.html` (`dicom_urls | tojson | safe`, server-built URL list, not PHI) | OK |
| Unused `templates = Jinja2Templates(directory="templates")` (`main.py:190`) left on a non-render path | **Accepted (trivial).** FastAPI's default autoescapes HTML; spec allows align-or-leave if not clearly safe/trivial. Not a divergent unsafe config in effect. |

**Residual / out of scope (not regressions):**

- Inline f-string HTML routes in `main.py` (e.g. archive day records, `secretary_qr_preview`,
  archive builders, `/download-report`) still interpolate user-controlled values raw and remain
  XSS-vulnerable; they bypass `env`. Documented in spec as out of scope — separate hardening
  ticket should escape/templatize these.
- HTML autoescaping does not protect JS/URL contexts; no new inline JS/event-handler sinks were
  introduced in the changed surface.

**Smells:** none in the diff above "not worth fixing for this ticket" (pre-existing inline page
builders).

---

## Spec

**Acceptance criteria** (`.scratch/xss-hardening/spec.md`, walked item by item):

| Criterion | Verdict | Evidence |
|---|---|---|
| Jinja `Environment` used to render routes enables autoescaping for HTML responses | checked | `main.py:204-207` (`select_autoescape(["html","xml"])`), routes render via `env` |
| `patient_name` containing `<script>alert(1)</script>` rendered escaped (not raw) on doctor, secretary, technician, and patient pages | checked | `test_script_in_patient_name_is_escaped_on_doctor_dashboard`, `_secretary_dashboard`, `_technician_dashboard`, `_patient_page` (raw absent, `&lt;script&gt;` present) |
| `report` containing HTML/script payloads rendered escaped on doctor/secretary dashboards | checked | `test_script_in_report_is_escaped_on_doctor_dashboard`, `_secretary_dashboard` (`&lt;img` present) |
| Normal patient data (Arabic names, plain report text) still renders visibly/correctly | checked | `test_normal_patient_data_still_renders` |
| No template marks user-controlled PHI fields as `| safe` | checked | templates unchanged; no PHI `| safe` usage |
| Ticket 01–04 suites stay green | checked | full suite 93 passed |

All escaping criteria are discriminating (assert raw payload absent and escaped entity present on
the named template surfaces).

**Behaviour not asked for / deviations:**
- No scope creep in code (diff limited to `select_autoescape` import + `env` config; templates
  unchanged). Unused `Jinja2Templates` left non-divergent in effect per spec. Inline f-string
  routes remain unfixed — explicitly out of scope (spec), recorded as residual risk. No PHI marked
  `| safe`.

**Implemented but wrong:** none found.

---

## Summary

- **Standards:** 0 in-scope defects; 1 trivial accepted note (unused renderer), 2 residual
  out-of-scope risks documented (inline f-string XSS, JS/URL contexts). No regressions.
- **Spec:** 6/6 acceptance criteria checked with evidence, 0 missing, 0 wrong, 0 deviations.

## Phase 4 verification

| Check | Result |
|---|---|
| Red (T05 baseline) | 6 failed, 87 passed |
| Green (after impl) | **93 passed** (86 prior + 7 T05) |
| Final (after review) | **93 passed** |
| Baseline snapshot integrity | 11/11 files match `MANIFEST.sha256` |
| Templates changed | none |
| `env` autoescape | `select_autoescape(['html','xml'])` on active render path |
