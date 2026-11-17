"""Ticket 04 — authentication and deletion hardening.

Contract (spec: `.scratch/auth-hardening/spec.md`):
- credentials are stored as non-reversible hashes, verified via `verify_password`
- `SESSION_SECRET` is read from the environment at import (before middleware install)
- `POST /doctor/delete/{id}`: admin only
- `POST /technician/delete/{id}`: technician only, registered exactly once
"""

import os

import pytest

import main
from conftest import get_record, insert_record, run_in_isolated_cwd


def _login_response(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


# --- credential storage -----------------------------------------------------------


def test_stored_passwords_are_not_plaintext():
    # The demo password must never survive as a stored credential value.
    assert "123" not in {user["password"] for user in main.USERS.values()}
    for username, user in main.USERS.items():
        assert user["password"] != "123", f"{username} stores a plaintext password"


def test_verify_password_accepts_correct_and_rejects_wrong():
    stored = main.USERS["samer"]["password"]
    assert main.verify_password("123", stored) is True
    assert main.verify_password("wrong-password", stored) is False
    assert main.verify_password("", stored) is False


def test_login_with_correct_password_still_works(clean_db):
    from fastapi.testclient import TestClient

    cases = [
        ("samer", "/doctor"),
        ("secretary", "/secretary"),
        ("ct_user", "/technician"),
    ]
    with TestClient(main.app) as client:
        for username, location in cases:
            response = _login_response(client, username, "123")
            assert response.status_code == 303, response.text[:300]
            assert response.headers["location"] == location
            assert client.get(location, follow_redirects=False).status_code == 200
            client.get("/logout")


def test_login_with_wrong_password_does_not_create_session(clean_db):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        response = _login_response(client, "samer", "wrong-password")

        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        # No authenticated session: protected dashboard must bounce back to login.
        doctor = client.get("/doctor", follow_redirects=False)
        assert doctor.status_code == 303
        assert doctor.headers["location"] == "/login"


# --- session secret ---------------------------------------------------------------


def test_session_secret_respects_env_at_import():
    result = run_in_isolated_cwd(
        "import os\n"
        "os.environ['SESSION_SECRET'] = 'env-session-secret-04'\n"
        "import main\n"
        "from starlette.middleware.sessions import SessionMiddleware\n"
        "print(main.SESSION_SECRET)\n"
        "mw = [m for m in main.app.user_middleware if m.cls is SessionMiddleware][0]\n"
        "print(mw.kwargs['secret_key'])\n"
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[-2:] == ["env-session-secret-04", "env-session-secret-04"], result.stdout + result.stderr


def test_session_secret_env_differs_from_builtin_fallback():
    result = run_in_isolated_cwd(
        "import os\n"
        "os.environ['SESSION_SECRET'] = 'env-session-secret-04'\n"
        "import main\n"
        "print(main.SESSION_SECRET == 'medical-pacs-super-secret-production-key-2026')\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False", result.stdout + result.stderr


# --- delete endpoints -------------------------------------------------------------


def test_doctor_delete_requires_admin(admin_client, secretary_client, technician_client):
    # admin can delete
    record_id = insert_record(name="سجل أدمن")
    response = admin_client.post(f"/doctor/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/doctor"
    assert get_record(record_id) is None

    # secretary cannot
    record_id = insert_record(name="سجل سكرتارية")
    response = secretary_client.post(f"/doctor/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None

    # technician cannot
    record_id = insert_record(name="سجل فني")
    response = technician_client.post(f"/doctor/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None

    # anonymous cannot
    from fastapi.testclient import TestClient

    record_id = insert_record(name="سجل مجهول")
    with TestClient(main.app) as client:
        response = client.post(f"/doctor/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None


def test_technician_delete_requires_technician(technician_client, admin_client, secretary_client):
    # technician can delete
    record_id = insert_record(name="سجل فني")
    response = technician_client.post(f"/technician/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/technician"
    assert get_record(record_id) is None

    # admin cannot delete via technician endpoint
    record_id = insert_record(name="سجل أدمن")
    response = admin_client.post(f"/technician/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None

    # secretary cannot
    record_id = insert_record(name="سجل سكرتارية")
    response = secretary_client.post(f"/technician/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None

    # anonymous cannot
    from fastapi.testclient import TestClient

    record_id = insert_record(name="سجل مجهول")
    with TestClient(main.app) as client:
        response = client.post(f"/technician/delete/{record_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert get_record(record_id) is not None


def test_technician_delete_route_is_not_duplicated():
    routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", "") == "/technician/delete/{record_id}"
        and "POST" in getattr(route, "methods", set())
    ]
    assert len(routes) == 1, f"expected 1 technician delete route, found {len(routes)}"
