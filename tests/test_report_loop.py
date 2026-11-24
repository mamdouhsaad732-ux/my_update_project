"""Ticket 03 — the report loop.

Contract (spec: `.scratch/report-loop/spec.md`):

    POST /save-report {record_id, report, next?} -> 303
        admin fallback /doctor · secretary fallback /secretary
        anonymous / technician -> 303 /login, record untouched
        unknown record -> 404
    every dashboard form: action="/save-report", name="report", hidden next
    POST /save-report-inline stays as an alias on the same function
"""

import logging
import os
from urllib.parse import urlparse

import pytest

import main
from conftest import get_record, insert_record


def _save(client, record_id, report, next_url=None):
    data = {"record_id": record_id, "report": report}
    if next_url is not None:
        data["next"] = next_url
    return client.post("/save-report", data=data, follow_redirects=False)


def _archive_day_path(record_id):
    record = get_record(record_id)
    return f"/doctor/archive/{record.modality}/{record.created_at[:7]}/{record.created_at[:10]}"


# --- the route works at all -------------------------------------------------------


def test_admin_saves_report_from_dashboard(admin_client, clean_static):
    record_id = insert_record()

    response = _save(admin_client, record_id, "تقرير الطبيب التشخيصي")

    assert response.status_code == 303, response.text[:400]
    assert response.headers["location"] == "/doctor"

    saved = get_record(record_id)
    assert saved.report == "تقرير الطبيب التشخيصي"
    assert saved.qr_code == f"qr_{record_id}.png"
    assert os.path.exists(os.path.join("static", "qrs", saved.qr_code))


def test_secretary_saves_report_from_dashboard(secretary_client, clean_static):
    record_id = insert_record()

    response = _save(secretary_client, record_id, "تقرير السكرتارية")

    assert response.status_code == 303, response.text[:400]
    assert response.headers["location"] == "/secretary"
    assert get_record(record_id).report == "تقرير السكرتارية"


def test_save_regenerates_the_signed_qr(admin_client, captured_qr, clean_static):
    record_id = insert_record()

    response = _save(admin_client, record_id, "تقرير جديد")

    assert response.status_code == 303
    assert len(captured_qr) == 1, f"expected one QR mint per save, got {captured_qr}"

    payload = urlparse(captured_qr[0])
    assert payload.netloc == "testserver", f"QR used a hardcoded host: {captured_qr[0]}"
    token = payload.path.rsplit("/", 1)[1]
    assert main.read_patient_token(token) == record_id


def test_empty_report_clears_the_stored_report(admin_client, clean_static):
    record_id = insert_record(report="تقرير قديم")

    response = _save(admin_client, record_id, "")

    assert response.status_code == 303, "clearing a report must not be a 422"
    assert get_record(record_id).report == ""


def test_saved_report_appears_on_admin_report_page(admin_client, clean_static):
    """Editing the report must be visible on /doctor/report/{id} immediately."""
    record_id = insert_record(report="تقرير قديم")

    response = _save(admin_client, record_id, "تقرير جديد بعد التعديل\nسطر ثانٍ")

    assert response.status_code == 303
    page = admin_client.get(f"/doctor/report/{record_id}").text
    assert "تقرير جديد بعد التعديل" in page
    assert "سطر ثانٍ" in page
    assert "تقرير قديم" not in page


def test_saved_report_appears_on_admin_dashboard(admin_client, clean_static):
    record_id = insert_record(report="تقرير قديم")

    _save(admin_client, record_id, "تقرير محدّث في اللوحة")

    dashboard = admin_client.get("/doctor").text
    assert "تقرير محدّث في اللوحة" in dashboard
    assert "تقرير قديم" not in dashboard


def test_report_containing_pending_word_is_not_hidden(admin_client, clean_static):
    """Only the placeholder itself is 'pending' — a real report may mention بانتظار."""
    record_id = insert_record()
    real_report = "بانتظار نتيجة الخزعة، التقرير الأولي: لا كسور."

    _save(admin_client, record_id, real_report)

    dashboard = admin_client.get("/doctor").text
    report_page = admin_client.get(f"/doctor/report/{record_id}").text

    assert real_report in dashboard
    assert 'report-empty">بانتظار' not in dashboard, "dashboard still rendered the pending placeholder"
    assert real_report in report_page
    assert 'report-text empty' not in report_page, "report page still rendered the pending placeholder"


def test_json_report_save_returns_updated_payload(admin_client, clean_static):
    record_id = insert_record()

    response = admin_client.post(
        "/save-report",
        data={"record_id": record_id, "report": "تقرير عبر الحفظ السريع", "next": "/doctor"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["record_id"] == record_id
    assert payload["report"] == "تقرير عبر الحفظ السريع"
    assert get_record(record_id).report == "تقرير عبر الحفظ السريع"
    assert "تقرير عبر الحفظ السريع" in admin_client.get(f"/doctor/report/{record_id}").text


def test_json_report_save_reports_server_failure(admin_client, clean_static, monkeypatch):
    """A failed write returns a clear JSON error, rolls back, and keeps the old report."""
    record_id = insert_record(report="تقرير قديم")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated QR failure")

    monkeypatch.setattr(main, "write_qr", _boom)

    response = admin_client.post(
        "/save-report",
        data={"record_id": record_id, "report": "لن يُحفظ", "next": "/doctor"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["ok"] is False
    assert "تعذر حفظ التقرير" in payload["error"]
    assert get_record(record_id).report == "تقرير قديم", "a failed save must not persist"


def test_json_report_save_unknown_record(admin_client):
    response = admin_client.post(
        "/save-report",
        data={"record_id": 999999, "report": "x"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["ok"] is False


def test_multipart_json_save_matches_browser_formdata(admin_client, clean_static):
    """A browser fetch() sends FormData (multipart), not urlencoded — keep that path working."""
    record_id = insert_record()

    response = admin_client.post(
        "/save-report",
        data={"record_id": str(record_id), "next": "/doctor"},
        files={"report": (None, "تقرير من نموذج المتصفح")},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert get_record(record_id).report == "تقرير من نموذج المتصفح"
    assert "تقرير من نموذج المتصفح" in admin_client.get(f"/doctor/report/{record_id}").text


def test_secretary_json_save_updates_dashboard_and_report_page(secretary_client, clean_static):
    record_id = insert_record(report="تقرير قديم للسكرتارية")

    response = secretary_client.post(
        "/save-report",
        data={"record_id": record_id, "report": "تقرير السكرتارية المحدّث", "next": "/secretary"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "تقرير السكرتارية المحدّث" in secretary_client.get("/secretary").text
    # The print/preview page reads the same field from the database.
    assert "تقرير السكرتارية المحدّث" in secretary_client.get(f"/secretary/qr-preview/{record_id}").text


def test_dashboards_disable_caching_for_fresh_reports(admin_client, secretary_client):
    """Stale cached HTML must never resurrect an old report after saving."""
    for client, path in ((admin_client, "/doctor"), (secretary_client, "/secretary")):
        response = client.get(path)
        assert "no-store" in response.headers.get("cache-control", ""), path


def test_save_forms_do_not_gate_on_confirm(admin_client, secretary_client):
    """A suppressed confirm() must not silently block saving on either dashboard."""
    for client, path in ((admin_client, "/doctor"), (secretary_client, "/secretary")):
        html = client.get(path).text
        assert 'id="modalStatus"' in html, path
        assert 'id="modalSave"' in html, path
        assert "application/json" in html, path
        assert "window.confirm" not in html, path
        assert "مؤكد من حفظ" not in html, path


def test_plain_save_error_shows_readable_page(admin_client):
    response = admin_client.post(
        "/save-report",
        data={"record_id": 999999, "report": "x", "next": "/doctor"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert "السجل غير موجود" in response.text
    assert 'href="/doctor"' in response.text


# --- authorisation ----------------------------------------------------------------


def test_technician_cannot_save_report(technician_client, clean_static):
    record_id = insert_record()
    before = get_record(record_id).report

    response = _save(technician_client, record_id, "تعديل غير مصرح")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id).report == before, "an unauthorised POST wrote to the record"


def test_anonymous_cannot_save_report(clean_db, clean_static):
    from fastapi.testclient import TestClient

    record_id = insert_record()
    before = get_record(record_id).report
    with TestClient(main.app) as client:
        response = _save(client, record_id, "تعديل مجهول")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id).report == before


def test_anonymous_json_save_gets_clear_401(clean_db, clean_static):
    from fastapi.testclient import TestClient

    record_id = insert_record()
    with TestClient(main.app) as client:
        response = client.post(
            "/save-report",
            data={"record_id": record_id, "report": "تعديل مجهول"},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert "صلاحية" in payload["error"] or "الجلسة" in payload["error"]


def test_unknown_record_is_404(admin_client):
    response = _save(admin_client, 999_999, "لا يوجد سجل")

    assert response.status_code == 404
    # "Not Found" is what a *missing route* returns; this must be the handler's own refusal.
    assert "السجل غير موجود" in response.text


# --- where the user lands afterwards ---------------------------------------------


@pytest.mark.parametrize(
    ("client_fixture", "expected"),
    [("admin_client", "/doctor"), ("secretary_client", "/secretary")],
)
def test_no_next_uses_the_role_default(request, client_fixture, expected, clean_static):
    client = request.getfixturevalue(client_fixture)
    record_id = insert_record()

    response = _save(client, record_id, "تقرير")

    assert response.status_code == 303
    assert response.headers["location"] == expected


def test_local_next_is_honoured(admin_client, clean_static):
    record_id = insert_record()
    target = _archive_day_path(record_id)

    response = _save(admin_client, record_id, "تقرير", next_url=target)

    assert response.status_code == 303
    assert response.headers["location"] == target


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.test/patient/1",
        "//evil.test/x",
        "/\\evil.test",
        "/doctor\r\nX-Injected: 1",
        "javascript:alert(1)",
    ],
)
def test_unsafe_next_falls_back(admin_client, clean_static, next_url):
    record_id = insert_record()

    response = _save(admin_client, record_id, "تقرير", next_url=next_url)

    assert response.status_code == 303
    assert response.headers["location"] == "/doctor", f"open redirect via next={next_url!r}"


# --- form alignment ---------------------------------------------------------------


def test_doctor_dashboard_form_is_aligned(admin_client):
    insert_record()

    html = admin_client.get("/doctor").text

    assert 'action="/save-report"' in html
    assert 'name="report"' in html, "the form must submit the field the route reads"
    assert 'name="report_text"' not in html, "stale field name remains"
    assert 'name="next"' in html


def test_secretary_dashboard_form_is_aligned(secretary_client):
    insert_record()

    html = secretary_client.get("/secretary").text

    assert 'action="/save-report"' in html
    assert 'name="report"' in html
    assert 'name="report_text"' not in html
    assert 'name="next"' in html


def test_secretary_qr_preview_opens_in_page_not_new_tab(secretary_client):
    """The preview button must open an in-page modal, never a new tab."""
    record_id = insert_record()

    html = secretary_client.get("/secretary").text

    # In-page modal wiring is present and the external/_blank link is gone.
    assert "data-qr-preview" in html
    assert 'id="qrPreviewModal"' in html
    assert 'id="previewBack"' in html
    assert 'target="_blank"' not in html
    assert f"/secretary/qr-preview/{record_id}" not in html

    # The standalone preview route stays reachable for backward compatibility.
    assert secretary_client.get(f"/secretary/qr-preview/{record_id}").status_code == 200


def test_archive_day_form_is_aligned(admin_client):
    record_id = insert_record()
    path = _archive_day_path(record_id)

    html = admin_client.get(path).text

    assert 'action="/save-report"' in html
    assert 'name="report"' in html
    assert 'name="report_text"' not in html
    assert f'value="{path}"' in html, "saving from the archive must return to that day"


def test_qr_preview_form_uses_the_unified_endpoint(secretary_client, clean_static):
    record_id = insert_record()

    html = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert 'action="/save-report"' in html
    assert 'action="/save-report-inline"' not in html, "the preview must use the canonical route"
    assert f'value="/secretary/qr-preview/{record_id}"' in html

    response = secretary_client.post(
        "/save-report",
        data={
            "record_id": record_id,
            "report": "تقرير المعاينة المحدث",
            "next": f"/secretary/qr-preview/{record_id}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/secretary/qr-preview/{record_id}"
    assert "تقرير المعاينة المحدث" in secretary_client.get(response.headers["location"]).text


def test_admin_dashboard_opens_report_in_same_tab(admin_client):
    """The old 'معاينة QR' link is now 'عرض التقرير' and must not open a new tab."""
    record_id = insert_record()

    html = admin_client.get("/doctor").text

    assert "عرض التقرير" in html
    assert f'href="/doctor/report/{record_id}"' in html
    assert f'href="/patient/{record_id}"' not in html
    assert 'target="_blank"' not in html


def test_admin_report_view_shows_report_and_qr_without_images(admin_client, clean_static):
    qr_name = "admin_report_qr.png"
    with open(os.path.join(main.QRS_DIR, qr_name), "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")  # presence on disk is all the route checks
    record_id = insert_record(
        report="تقرير طبي محفوظ.\nالسطر الثاني من التقرير.",
        qr_code=qr_name,
    )

    html = admin_client.get(f"/doctor/report/{record_id}").text

    # Saved report (with preserved lines) + branding + QR + clear return button.
    assert "تقرير طبي محفوظ." in html
    assert "السطر الثاني من التقرير." in html
    assert "/static/image/MRI%20IMAGE.jpg" in html
    assert "مركز محردة للرنين المغناطيسي والطبقي المحوري" in html
    assert "الدكتور سامر ممدوح سعد" in html
    assert f"/static/qrs/{qr_name}" in html
    assert 'href="/doctor"' in html
    assert "عودة إلى لوحة التحكم" in html

    # No imaging section, thumbnails, zoom controls, or lightbox.
    for needle in ("scan-card", "scan-thumb", "zoom-btn", "lb-root", "lightbox", "صور الأشعة"):
        assert needle not in html
    # The admin report view never routes through the public patient portal.
    assert "/patient/" not in html


def test_admin_report_view_pending_report_placeholder(admin_client):
    record_id = insert_record(report="بانتظار كتابة التقرير الطبي...")

    html = admin_client.get(f"/doctor/report/{record_id}").text

    assert "بانتظار كتابة التقرير الطبي" in html


def test_admin_report_view_requires_admin(secretary_client, technician_client):
    record_id = insert_record()

    for client in (secretary_client, technician_client):
        response = client.get(f"/doctor/report/{record_id}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_dead_archive_template_is_aligned_too():
    """`archive_records.html` is not wired up yet; aligned so it cannot drift."""
    path = os.path.join(os.path.dirname(__file__), "..", "templates", "archive_records.html")
    with open(path, encoding="utf-8") as handle:
        html = handle.read()

    assert 'action="/save-report"' in html
    assert 'name="report"' in html
    assert 'name="report_text"' not in html
    assert 'name="next"' in html


# --- observability and compatibility ----------------------------------------------


def test_save_is_logged_once(admin_client, clean_static, caplog):
    record_id = insert_record()

    with caplog.at_level(logging.INFO, logger="main"):
        _save(admin_client, record_id, "تقرير")

    hits = [r for r in caplog.records if "report: saved" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in caplog.records]
    assert f"id={record_id}" in hits[0].getMessage()


def test_inline_alias_still_works(secretary_client, clean_static):
    record_id = insert_record()

    response = secretary_client.post(
        "/save-report-inline",
        data={"record_id": record_id, "report": "عبر الاسم القديم"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert get_record(record_id).report == "عبر الاسم القديم"


def test_inline_alias_requires_authorisation(technician_client, clean_static):
    """The alias is the old unauthenticated endpoint; it must inherit the new gate."""
    record_id = insert_record()
    before = get_record(record_id).report

    response = technician_client.post(
        "/save-report-inline",
        data={"record_id": record_id, "report": "تعديل غير مصرح"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id).report == before


def test_alias_shares_one_implementation():
    endpoints = {
        route.path: route.endpoint
        for route in main.app.routes
        if getattr(route, "path", "") in {"/save-report", "/save-report-inline"}
    }

    assert set(endpoints) == {"/save-report", "/save-report-inline"}
    assert endpoints["/save-report"] is endpoints["/save-report-inline"], (
        "the compatibility alias must not be a second implementation"
    )
