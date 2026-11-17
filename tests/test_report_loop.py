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
