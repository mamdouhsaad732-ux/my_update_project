"""Shared fixtures and the throwaway-database guard for the whole suite.

`main` builds its engine and runs `Base.metadata.create_all()` at import time, so the
environment must be configured before *any* test module imports it. `conftest.py` is
imported by pytest before collection, which is the only reliable place for that. Setting
it inside a test module would be silently bypassed the moment a second module imports
`main` first — and `clean_db` would then drop tables in the real patient database.
"""

import os
import base64
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DB_DIR = tempfile.mkdtemp(prefix="pacs-test-")
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test.db")

os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DB_PATH.replace(os.sep, "/")
os.environ.pop("PURGE_ENABLED", None)

import main  # noqa: E402  (import order is the point)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


# Fail loudly rather than let a mis-ordered import point the suite at live patient data.
if not _same_path(main.engine.url.database or "", TEST_DB_PATH):
    raise RuntimeError(
        f"test suite is bound to {main.engine.url.database!r}, not {TEST_DB_PATH!r}: "
        "main was imported before conftest.py configured DATABASE_URL"
    )


@pytest.fixture()
def clean_db():
    main.Base.metadata.drop_all(bind=main.engine)
    main.Base.metadata.create_all(bind=main.engine)
    yield
    main.Base.metadata.drop_all(bind=main.engine)
    main.Base.metadata.create_all(bind=main.engine)


# 1x1 PNG: the smallest thing the non-DICOM upload branch will accept.
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

STATIC_DIRS = ("static/uploads", "static/qrs")


def insert_record(created_at=None, name="مريض اختبار", **overrides) -> int:
    """Insert a record directly, bypassing the upload route."""
    fields = dict(
        patient_name=name,
        birth_date="1990-01-01",
        modality="CT",
        image_path="/static/uploads/none.png",
        qr_code="temp.png",
    )
    fields.update(overrides)
    if created_at is not None:
        fields["created_at"] = created_at

    session = main.SessionLocal()
    try:
        record = main.PatientRecord(**fields)
        session.add(record)
        session.commit()
        return record.id
    finally:
        session.close()


def get_record(record_id: int):
    session = main.SessionLocal()
    try:
        return session.query(main.PatientRecord).filter(main.PatientRecord.id == record_id).first()
    finally:
        session.close()


@pytest.fixture()
def clean_static():
    """Remove anything a test writes into the static upload/QR directories."""
    before = {directory: set(os.listdir(directory)) for directory in STATIC_DIRS}
    yield
    for directory, names in before.items():
        for name in set(os.listdir(directory)) - names:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                os.remove(path)


def _login(client, username: str):
    response = client.post(
        "/login",
        data={"username": username, "password": "123"},
        follow_redirects=False,
    )
    assert response.status_code == 303, f"fixture login failed for {username!r}"
    return client


@pytest.fixture()
def admin_client(clean_db):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        yield _login(client, "samer")


@pytest.fixture()
def technician_client(clean_db):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        yield _login(client, "ct_user")


def run_in_isolated_cwd(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a scratch directory that can import the repo but owns its own database.

    Used for assertions about import-time behaviour (the DATABASE_URL fallback, logger
    configuration) that would otherwise require polluting the real working directory.
    """
    directory = tempfile.mkdtemp(prefix="pacs-subproc-")
    os.makedirs(os.path.join(directory, "static"), exist_ok=True)
    environment = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    environment["PYTHONPATH"] = REPO_ROOT
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
