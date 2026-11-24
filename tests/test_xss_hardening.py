"""Ticket 05 — template autoescaping and stored XSS hardening.

Contract (spec: `.scratch/xss-hardening/spec.md`): the active Jinja environment
autoescapes HTML, so user-controlled values are rendered escaped on template pages.
"""

from urllib.parse import urlparse

import main
from conftest import insert_record


XSS_NAME = '<script>alert("name")</script>'
XSS_REPORT = "<img src=x onerror=alert(1)>"
ESCAPED_SCRIPT_LT = "&lt;script&gt;"
ESCAPED_SCRIPT_GT = "&lt;/script&gt;"
ESCAPED_IMG = "&lt;img"


def _patient_path(record_id: int) -> str:
    return urlparse(main.patient_url(record_id, "http://testserver")).path


# --- patient name -----------------------------------------------------------------


def test_script_in_patient_name_is_escaped_on_doctor_dashboard(admin_client):
    insert_record(name=XSS_NAME)

    body = admin_client.get("/doctor").text

    assert XSS_NAME not in body, "raw script tag rendered on doctor dashboard"
    assert ESCAPED_SCRIPT_LT in body


def test_script_in_patient_name_is_escaped_on_secretary_dashboard(secretary_client):
    insert_record(name=XSS_NAME)

    body = secretary_client.get("/secretary").text

    assert XSS_NAME not in body, "raw script tag rendered on secretary dashboard"
    assert ESCAPED_SCRIPT_LT in body


def test_script_in_patient_name_is_escaped_on_technician_dashboard(technician_client):
    insert_record(name=XSS_NAME)

    body = technician_client.get("/technician").text

    assert XSS_NAME not in body, "raw script tag rendered on technician dashboard"
    assert ESCAPED_SCRIPT_LT in body


def test_script_in_patient_name_is_escaped_on_patient_page(admin_client):
    record_id = insert_record(name=XSS_NAME)

    body = admin_client.get(_patient_path(record_id)).text

    assert XSS_NAME not in body, "raw script tag rendered on patient page"
    assert ESCAPED_SCRIPT_LT in body


# --- report -----------------------------------------------------------------------


def test_script_in_report_is_escaped_on_doctor_dashboard(admin_client):
    insert_record(report=XSS_REPORT)

    body = admin_client.get("/doctor").text

    assert XSS_REPORT not in body, "raw HTML payload rendered in doctor report field"
    assert ESCAPED_IMG in body


def test_script_in_report_is_escaped_on_secretary_dashboard(secretary_client):
    insert_record(report=XSS_REPORT)

    body = secretary_client.get("/secretary").text

    assert XSS_REPORT not in body, "raw HTML payload rendered in secretary report field"
    assert ESCAPED_IMG in body


def test_script_in_report_is_escaped_on_admin_report_view(admin_client):
    record_id = insert_record(report=XSS_REPORT)

    body = admin_client.get(f"/doctor/report/{record_id}").text

    assert XSS_REPORT not in body, "raw HTML payload rendered in admin report view"
    assert ESCAPED_IMG in body


def test_script_in_patient_name_is_escaped_on_admin_report_view(admin_client):
    record_id = insert_record(name=XSS_NAME)

    body = admin_client.get(f"/doctor/report/{record_id}").text

    assert XSS_NAME not in body, "raw script tag rendered in admin report view"
    assert ESCAPED_SCRIPT_LT in body


# --- regression -------------------------------------------------------------------


def test_normal_patient_data_still_renders(admin_client):
    name = "مريض سليم"
    report = "تقرير طبيعي بدون وسوم"
    insert_record(name=name, report=report)

    body = admin_client.get("/doctor").text

    assert name in body
    assert report in body
