# 05 — Jinja2 autoescape & stored XSS mitigation

- **Status**: resolved
- **Type**: task
- **Depends on**: 01–04 (resolved) — hardens rendering on top of the current route/template
  structure.
- **Spec**: `.scratch/xss-hardening/spec.md`

## Objective

Turn on Jinja autoescaping for the app's template environment, audit templates for legitimate raw
HTML, and pin with tests that stored patient data cannot inject executable markup into
template-rendered pages.

## Architecture impact

| Component | Change |
|---|---|
| `main.py` (`env = Environment(...)`) | Enable `select_autoescape(['html', 'xml'])` (or equivalent) on the active Jinja environment |
| `main.py` (`Jinja2Templates(...)`) | Align or leave unused instance so it does not diverge confusingly (trivial only) |
| `templates/*.html` | Audit; add `| safe` only for trusted/non-PHI content if required |
| `tests/test_xss_hardening.py` | New |

## Plan

1. Baseline snapshot (`main.py`, `templates/*`) + `MANIFEST.sha256`. Done.
2. Write `tests/test_xss_hardening.py` (red) against template-rendered surfaces.
3. Enable autoescape, audit/fix templates for breakage, keep PHI fields escaped.
4. Green, including Ticket 01–04 suites.
5. Two-axis review; fix; re-run.

## Risk assessment

**Medium-low.** Main risk is accidental breakage of any template that depended on unescaped markup.
Guards: template audit, explicit `| safe` only for justified trusted values, full-suite run.
Residual: inline f-string HTML routes in `main.py` remain out of scope for autoescape and are
called out in the spec/review rather than silently "fixed".

## Test plan (red first)

| Test | Pins |
|---|---|
| `test_script_in_patient_name_is_escaped_on_doctor_dashboard` | doctor template renders escaped name, not raw `<script>` |
| `test_script_in_patient_name_is_escaped_on_secretary_dashboard` | secretary template |
| `test_script_in_patient_name_is_escaped_on_technician_dashboard` | technician template |
| `test_script_in_patient_name_is_escaped_on_patient_page` | patient template via signed token |
| `test_script_in_report_is_escaped_on_doctor_dashboard` | report in textarea/text context escaped |
| `test_script_in_report_is_escaped_on_secretary_dashboard` | report escaped |
| `test_normal_patient_data_still_renders` | no regression for plain/Arabic text |

## Deviations

- None. Inline f-string HTML routes were **not** escaped/refactored in this ticket and no PHI field
  was marked `| safe` — residual inline-route XSS risk is documented as out of scope (spec/review),
  not a silent fix. Unused `Jinja2Templates(...)` left in place (non-render path, non-divergent in
  effect).

## Resolution

**Resolved 2026-11-15.** Baseline `MANIFEST.sha256` (11 files) verified intact; diff in
`.scratch/xss-hardening/changes.diff`, review in `.scratch/xss-hardening/review.md`.
Suite: **93 passed** (86 prior + 7 T05), up from 6 failed / 87 passed at the T05 red phase.

Shipped:

- **Template autoescaping:** `env = Environment(loader=FileSystemLoader("templates"),
  autoescape=select_autoescape(["html","xml"]))` on the active render path in `main.py`.
- **Audit:** templates unchanged; no PHI/user-controlled fields marked `| safe` (pre-existing
  `| safe` is only `dicom_urls | tojson` in `view_scan.html`, server-built, non-PHI). Normal and
  Arabic text render correctly.

## Follow-ups (not this ticket)

1. Escape or templatize inline f-string HTML routes in `main.py` (archive day/records builders,
   `secretary_qr_preview`, download/report views) — still interpolate user data raw and bypass
   `env`.
2. Review JS/URL attribute contexts (e.g. inline handlers embedding values) for context-appropriate
   escaping; remove or align the unused `Jinja2Templates` instance if it becomes a source of
   confusion.
3. Broader hardening unchanged: CSP/CSRF, public `/static/uploads`.

