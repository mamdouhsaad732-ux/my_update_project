# Ticket 07 — review record

Two-axis review of `.scratch/uploads-auth/changes.diff` (baseline `main.py` → working tree,
`templates/patient.html` vs T05 baseline for context, plus `tests/test_uploads_auth.py`).
Both axes ran as parallel fresh-context sub-agents. Spec axis invoked the suite once (run did not
complete in that environment); full suite verified locally after triage.

Baseline integrity at review time: `main.py` in `.scratch/uploads-auth/baseline/` matches
`MANIFEST.sha256`.

---

## Standards

**Documented standards:** none. No `CODING_STANDARDS.md`, no `CONTRIBUTING.md`, no linter
config; `docs/agents/*` govern process/domain only. The only standard is the smell baseline.

**Correctness / security (diff-introduced):**

| Finding | Disposition |
|---|---|
| PHI subtrees `/static/uploads/*` and `/static/qrs/*` served only by guarded handlers; anonymous/unauthorized requests rejected (403), missing/unresolvable/non-file → 404 | OK |
| Path traversal mitigated: `_resolve_protected_static_path` resolves and enforces containment within the intended base dir | OK |
| Staff access: any authenticated session user authorized (matches spec's "any application role") | OK (broad by design) |
| Patient-token access scoped by ownership: upload must be listed in `record.image_path`, QR must be `qr_{record_id}.png` | OK — **test-pinning gap fixed** (see Spec) |
| Patient token transported in query string (`?patient_token=`) and appended to patient-page asset URLs | **Known tradeoff, documented.** Tokens may appear in browser history/proxy logs/Referer, but the patient credential is already present in the page URL (spec risk L56-57). Out of scope to redesign transport. |
| Non-PHI `static/image` re-mounted publicly; other `static/*` subtrees no longer served by the removed broad mount | OK for evidenced assets (branding). Other public subtrees, if any, would be blocked — none required by tests/spec evidence. |

**Smells (judgement calls):**

| Smell | Location | Disposition |
|---|---|---|
| Obscure test setup (`qr_code` placeholder then manual DB fixup) | `tests/test_uploads_auth.py` | **Fixed** — replaced with `_linked_record` helper |

---

## Spec

**Acceptance criteria** (`.scratch/uploads-auth/spec.md`, walked item by item):

| Criterion | Verdict | Evidence |
|---|---|---|
| Anonymous `GET /static/uploads/<existing file>` rejected (not 200, no file body) | checked | `test_anonymous_cannot_fetch_upload` |
| Anonymous `GET /static/qrs/<existing file>` rejected (not 200, no file body) | checked | `test_anonymous_cannot_fetch_qr` |
| Authenticated `admin` can retrieve existing `/static/uploads/*` and `/static/qrs/*` (200) | checked | `test_admin_can_fetch_upload`, `test_admin_can_fetch_qr` |
| Authenticated `secretary` and `technician` can retrieve protected assets | checked | `test_secretary_can_fetch_protected_assets`, `test_technician_can_fetch_protected_assets` |
| Valid signed patient token can authorize retrieval of that patient's assets | checked (hardened) | `test_valid_patient_token_can_fetch_patient_assets`; **Spec axis noted ownership was not discriminatingly pinned** — added `test_patient_token_cannot_fetch_other_record_assets` (token for record A rejected for record B upload/QR, no body leak) |
| Non-PHI public static content required by the app not broken | checked | `static/image` mounted; `test_non_phi_static_asset_still_public` (`MRI IMAGE.jpg`) |
| Ticket 01–06 suites stay green | checked | full suite 111 passed locally |

**Behaviour not asked for / deviations (reported per ticket):**

- **Patient-token transport added to URLs:** `?patient_token=<token>` on guarded asset requests;
  `print_record` appends it to `dicom_urls` and passes it to `patient.html`, which appends it to the
  QR `<img>` src. Required to keep the token-based patient page functional when embedded assets are
  separate HTTP requests (spec risk L56-57; ticket requires recording transport-in-URL).
- **Broad `/static` mount replaced with `/static/image` only:** preserves evidenced non-PHI public
  content; other previously-public non-protected subtrees are no longer served by a catch-all mount.
- `templates/patient.html` adjusted (not in T07 baseline snapshot) to carry the asset token.

**Implemented but wrong:** none found. No alternate public path/traversal bypass evidenced; staff
roles covered; ownership correctly scoped and now pinned.

---

## Summary

- **Standards:** 3 findings — 1 fixed (test setup clarity), 1 documented tradeoff (token in query
  string, anticipated), 1 accepted as spec-consistent (broad staff access). No bypass or traversal
  defect found.
- **Spec:** 7/7 acceptance criteria checked, 1 hardened with an additional discriminating ownership
  test (axis-driven), 2 deviations recorded (token transport in URLs, segmented static mount + patient
  template change).

## Phase 4 verification

| Check | Result |
|---|---|
| Red (T07 baseline) | 2 failed, 108 passed |
| Green (after impl) | **110 passed** (102 prior + 8 T07) |
| After review-driven hardening | **111 passed** (+ cross-record ownership test) |
| Baseline snapshot integrity | `main.py` matches `MANIFEST.sha256` |
| Anonymous `/static/uploads/*`, `/static/qrs/*` | rejected |
| Staff sessions / patient token (scoped) | authorized; other-record token rejected |
| Non-PHI `static/image` | public |
