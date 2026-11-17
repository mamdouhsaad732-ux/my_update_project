# Spec: Jinja2 autoescape & stored XSS hardening

## Problem

User-controlled values (patient name, birth date, modality, report text, etc.) are rendered into
HTML without automatic escaping. The active Jinja environment is created as:

```python
env = Environment(loader=FileSystemLoader("templates"))
```

(`main.py`, `env = Environment(...)`) with no `autoescape`, so `{{ record.patient_name }}` /
`{{ record.report }}` in templates are emitted raw. A value like `<script>…</script>` stored in a
record becomes executable markup in any page that renders it.

An unused `Jinja2Templates(directory="templates")` instance also exists in `main.py`; it is not on
the render path used by the app's routes.

## Decision

| Concern | Decision |
|---|---|
| Template autoescape | Enable autoescaping for HTML/XML on the Jinja `Environment` used by routes (`select_autoescape(['html', 'xml'])` or equivalent). This is the primary render path. |
| Template audit | Audit templates for variables that must remain unescaped; mark them explicitly with `| safe` only where the source is trusted/constructed, not for user-controlled PHI fields. |
| Textareas / attributes | Rely on Jinja's contextual escaping in HTML text and attribute contexts; do not introduce `| safe` for reports, names, dates, or other patient-supplied data. |
| Inline HTML in routes | `main.py` contains routes that build HTML via f-strings (e.g. archive day view, QR preview, download report). Securing those requires explicit escaping of interpolated values and is **out of scope** for this ticket's autoescape change except that the change must not break existing behaviour. |
| Unused renderer | The unused `Jinja2Templates(...)` instance may be aligned or left alone; it must not become a second, divergent configuration that confuses future work. |

## Scope

- `main.py`: configure `env` with HTML autoescaping (and align/remove unused renderer only if
  trivial and clearly safe).
- `templates/*.html`: add `| safe` only where a deliberate raw-HTML rendering is required and
  justified; otherwise no functional changes.
- `tests/test_xss_hardening.py`: new regression tests.

## Out of scope

- Escaping or refactoring inline f-string HTML builders in `main.py` (archive/QR-preview/download
  routes) — tracked as follow-up; tests in this ticket target template-rendered surfaces.
- CSP headers, input sanitisation/stripping, rich-text/Markdown rendering of reports.
- Public `/static/uploads` exposure, CSRF, `autoescape=False` in any hypothetical future renderer
  outside the audited `env`.

## Acceptance criteria

- [ ] The Jinja `Environment` used to render routes enables autoescaping for HTML responses.
- [ ] A record whose `patient_name` contains `<script>alert(1)</script>` renders that payload
      escaped (e.g. `&lt;script&gt;`) and not as a raw `<script>` tag on template-rendered pages
      that display it (at minimum: doctor dashboard, secretary dashboard, technician dashboard,
      patient page).
- [ ] A record whose `report` contains HTML/script payloads is rendered escaped in
      template-rendered contexts that display the report (doctor/secretary dashboards).
- [ ] Normal patient data (Arabic names, plain report text) still renders visibly/correctly.
- [ ] No template marks user-controlled PHI fields as `| safe`.
- [ ] Ticket 01–04 suites stay green.

## Risks

- **Breaking intentional markup.** If any template relied on unescaped HTML in a variable, enabling
  autoescape will escape it; the template audit must catch and explicitly `| safe` only trusted
  values.
- **JS attribute contexts** (e.g. inline `onclick` handlers that embed values) are not fully
  protected by HTML autoescaping; this ticket does not introduce them but must not make them worse.
  Flag any newly noticed cases as follow-up, do not expand scope silently.
- **Inline f-string pages remain vulnerable** until refactored; this is a documented residual risk,
  not a regression introduced here.
