"""Ticket 07 â€” access control for PHI-bearing static assets.

Contract (spec: `.scratch/uploads-auth/spec.md`):
- `/static/uploads/*` and `/static/qrs/*` are not anonymously retrievable
- authenticated staff sessions may retrieve them
- a valid signed patient token may retrieve that patient's assets
"""

import os

import pytest

import main
from conftest import insert_record


def _upload_path(name: str) -> str:
    return os.path.join(main.UPLOADS_DIR, name)


def _qr_path(name: str) -> str:
    return os.path.join(main.QRS_DIR, name)


def _write(path: str, content: bytes = b"PHI-BYTES") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def _is_rejected(response) -> bool:
    # Spec allows 401, 403, or 404; body must not be the file content.
    return response.status_code in {401, 403, 404}


# --- anonymous direct access is blocked -------------------------------------------


def test_anonymous_cannot_fetch_upload(clean_db, clean_static):
    from fastapi.testclient import TestClient

    _write(_upload_path("secret-scan.png"))
    with TestClient(main.app) as client:
        response = client.get("/static/uploads/secret-scan.png")

    assert _is_rejected(response), f"expected rejection, got {response.status_code}"
    assert b"PHI-BYTES" not in response.content


def test_anonymous_cannot_fetch_qr(clean_db, clean_static):
    from fastapi.testclient import TestClient

    _write(_qr_path("qr_999.png"), b"QR-PHI")
    with TestClient(main.app) as client:
        response = client.get("/static/qrs/qr_999.png")

    assert _is_rejected(response), f"expected rejection, got {response.status_code}"
    assert b"QR-PHI" not in response.content


# --- authenticated staff access ---------------------------------------------------


def test_admin_can_fetch_upload(admin_client, clean_static):
    _write(_upload_path("admin-scan.png"))

    response = admin_client.get("/static/uploads/admin-scan.png")

    assert response.status_code == 200
    assert response.content == b"PHI-BYTES"


def test_admin_can_fetch_qr(admin_client, clean_static):
    _write(_qr_path("qr_admin.png"), b"QR-PHI")

    response = admin_client.get("/static/qrs/qr_admin.png")

    assert response.status_code == 200
    assert response.content == b"QR-PHI"


def test_secretary_can_fetch_protected_assets(secretary_client, clean_static):
    _write(_upload_path("sec-scan.png"), b"UPLOAD")
    _write(_qr_path("qr_sec.png"), b"QR")

    up = secretary_client.get("/static/uploads/sec-scan.png")
    qr = secretary_client.get("/static/qrs/qr_sec.png")

    assert up.status_code == 200 and up.content == b"UPLOAD"
    assert qr.status_code == 200 and qr.content == b"QR"


def test_technician_can_fetch_protected_assets(technician_client, clean_static):
    _write(_upload_path("tech-scan.png"), b"UPLOAD")
    _write(_qr_path("qr_tech.png"), b"QR")

    up = technician_client.get("/static/uploads/tech-scan.png")
    qr = technician_client.get("/static/qrs/qr_tech.png")

    assert up.status_code == 200 and up.content == b"UPLOAD"
    assert qr.status_code == 200 and qr.content == b"QR"


# --- patient token access ---------------------------------------------------------


def _linked_record(upload_name: str) -> int:
    """Insert a record and point its assets at `upload_name` / `qr_<id>.png`."""
    record_id = insert_record()
    session = main.SessionLocal()
    try:
        record = session.query(main.PatientRecord).filter(main.PatientRecord.id == record_id).first()
        record.qr_code = f"qr_{record_id}.png"
        record.image_path = f"/static/uploads/{upload_name}"
        session.commit()
    finally:
        session.close()
    return record_id


def test_valid_patient_token_can_fetch_patient_assets(clean_db, clean_static):
    """The signed patient token (T02 credential) must authorize that record's assets."""
    from fastapi.testclient import TestClient

    record_id = _linked_record("patient-scan.png")
    _write(_upload_path("patient-scan.png"), b"PATIENT-UPLOAD")
    _write(_qr_path(f"qr_{record_id}.png"), b"PATIENT-QR")
    token = main.mint_patient_token(record_id)

    with TestClient(main.app) as client:
        up = client.get("/static/uploads/patient-scan.png", params={"patient_token": token})
        qr = client.get(f"/static/qrs/qr_{record_id}.png", params={"patient_token": token})

    assert up.status_code == 200 and up.content == b"PATIENT-UPLOAD", (
        f"upload not accessible with patient token: {up.status_code}"
    )
    assert qr.status_code == 200 and qr.content == b"PATIENT-QR", (
        f"qr not accessible with patient token: {qr.status_code}"
    )


def test_patient_token_cannot_fetch_other_record_assets(clean_db, clean_static):
    """Ownership must be scoped to the token's record, not just 'any valid token'."""
    from fastapi.testclient import TestClient

    record_a = _linked_record("a.png")
    record_b = _linked_record("b.png")
    _write(_upload_path("a.png"), b"A")
    _write(_upload_path("b.png"), b"B")
    _write(_qr_path(f"qr_{record_a}.png"), b"QR-A")
    _write(_qr_path(f"qr_{record_b}.png"), b"QR-B")
    token_a = main.mint_patient_token(record_a)

    with TestClient(main.app) as client:
        up = client.get("/static/uploads/b.png", params={"patient_token": token_a})
        qr = client.get(f"/static/qrs/qr_{record_b}.png", params={"patient_token": token_a})

    assert _is_rejected(up), f"token for record A fetched record B upload: {up.status_code}"
    assert b"B" not in up.content
    assert _is_rejected(qr), f"token for record A fetched record B QR: {qr.status_code}"
    assert b"QR-B" not in qr.content


# --- non-PHI public assets remain available ---------------------------------------


def test_non_phi_static_asset_still_public(clean_db):
    from fastapi.testclient import TestClient

    # Branding asset referenced by the patient template; must stay public.
    path = "static/image/MRI IMAGE.jpg"
    assert os.path.exists(path), f"expected public asset missing: {path}"

    with TestClient(main.app) as client:
        response = client.get("/static/image/MRI IMAGE.jpg")

    assert response.status_code == 200
    assert len(response.content) > 0

