"""Ticket 06 — XSS hardening for inline f-string HTML routes.

Contract (spec: `.scratch/inline-xss-hardening/spec.md`): routes that build HTML via
f-strings must escape stored/user-controlled values before interpolation.
"""

import main
from conftest import insert_record


XSS_NAME = '<script>alert("name")</script>'
XSS_REPORT = "<img src=x onerror=alert(1)>"
XSS_ATTR_BREAK = '2000-01-01"><script>alert(1)</script>'
ESCAPED_SCRIPT_LT = "&lt;script&gt;"
ESCAPED_IMG = "&lt;img"


def _archive_day_path(modality: str, created_at: str) -> str:
    day = created_at[:10]
    month = created_at[:7]
    return f"/doctor/archive/{modality}/{month}/{day}"


# --- doctor archive day (inline f-string HTML) ------------------------------------


def test_archive_records_escapes_patient_name(admin_client):
    created_at = "2026-11-15 10:00:00.000000"
    insert_record(name=XSS_NAME, modality="CT", created_at=created_at)

    body = admin_client.get(_archive_day_path("CT", created_at)).text

    assert XSS_NAME not in body, "raw script tag rendered in archive records"
    assert ESCAPED_SCRIPT_LT in body


def test_archive_records_escapes_report(admin_client):
    created_at = "2026-11-15 11:00:00.000000"
    insert_record(report=XSS_REPORT, modality="CT", created_at=created_at)

    body = admin_client.get(_archive_day_path("CT", created_at)).text

    assert XSS_REPORT not in body, "raw HTML payload rendered in archive report"
    assert ESCAPED_IMG in body


def test_archive_records_renders_normal_data(admin_client):
    created_at = "2026-11-15 12:00:00.000000"
    name = "مريض الأرشيف"
    report = "تقرير أرشيف عادي"
    insert_record(name=name, report=report, modality="CT", created_at=created_at)

    body = admin_client.get(_archive_day_path("CT", created_at)).text

    assert name in body
    assert report in body


# --- secretary QR preview (inline f-string HTML) ---------------------------------


def test_secretary_qr_preview_escapes_patient_name(secretary_client):
    record_id = insert_record(name=XSS_NAME)

    body = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert XSS_NAME not in body, "raw script tag rendered in QR preview"
    assert ESCAPED_SCRIPT_LT in body


def test_secretary_qr_preview_escapes_report(secretary_client):
    record_id = insert_record(report=XSS_REPORT)

    body = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert XSS_REPORT not in body, "raw HTML payload rendered in QR preview report"
    assert ESCAPED_IMG in body


def test_secretary_qr_preview_escapes_birth_date(secretary_client):
    record_id = insert_record(birth_date=XSS_ATTR_BREAK)

    body = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert XSS_ATTR_BREAK not in body, "raw payload rendered in QR preview birth date"
    assert ESCAPED_SCRIPT_LT in body


def test_secretary_qr_preview_escapes_modality(secretary_client):
    record_id = insert_record(modality=XSS_ATTR_BREAK)

    body = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert XSS_ATTR_BREAK not in body, "raw payload rendered in QR preview modality"
    assert ESCAPED_SCRIPT_LT in body


def test_secretary_qr_preview_renders_normal_data(secretary_client):
    name = "مريض المعاينة"
    report = "تقرير معاينة عادي"
    record_id = insert_record(name=name, report=report)

    body = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert name in body
    assert report in body


# --- download endpoint must remain functional (non-HTML) -------------------------


def test_download_report_still_returns_content(admin_client):
    name = "مريض التحميل"
    report = "نص التقرير"
    record_id = insert_record(name=name, report=report, modality="MRI")

    response = admin_client.get(f"/download-report/{record_id}")

    assert response.status_code == 200
    # Contract: downloadable report content still contains the stored data.
    text = response.text
    assert name in text
    assert report in text
    assert str(record_id) in text
