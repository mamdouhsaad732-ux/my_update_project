"""Ticket 08 — production readiness and integration verification.

Verifies configuration contracts, deployment artifacts, and core integration
surfaces. The `/health` probe is specified by the ticket; it may be absent
until implemented.
"""

import asyncio
import datetime
import json
import os

import main
from conftest import REPO_ROOT, get_record, insert_record, run_in_isolated_cwd


# --- health probe -----------------------------------------------------------------


def test_health_endpoint_returns_ok(clean_db):
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"
    # Must not leak secrets or PHI.
    serialized = json.dumps(body, ensure_ascii=False).lower()
    for forbidden in ("secret", "password", "token", "patient", "record", "qr_signing"):
        assert forbidden not in serialized, f"health payload leaked '{forbidden}'"


# --- app / routes integration -----------------------------------------------------


def test_app_imports_and_core_routes_registered():
    paths = {getattr(route, "path", "") for route in main.app.routes}
    required = {
        "/health",
        "/login",
        "/doctor",
        "/secretary",
        "/technician",
        "/patient/{identifier}",
        "/save-report",
        "/static/uploads/{file_path:path}",
        "/static/qrs/{file_path:path}",
    }
    missing = required - paths
    assert not missing, f"missing core routes: {sorted(missing)}"


def test_full_integration_smoke(admin_client, clean_static):
    # A minimal coherent flow: authenticated dashboard, signed patient page, and
    # guarded static access are all reachable.
    doctor = admin_client.get("/doctor")
    assert doctor.status_code == 200

    session = main.SessionLocal()
    try:
        record = main.PatientRecord(
            patient_name="مريض جاهزية",
            birth_date="1990-01-01",
            modality="CT",
            image_path="/static/uploads/readiness.png",
            qr_code="qr_1.png",
        )
        session.add(record)
        session.commit()
        record_id = record.id
        record.qr_code = f"qr_{record_id}.png"
        session.commit()
    finally:
        session.close()

    os.makedirs(main.UPLOADS_DIR, exist_ok=True)
    os.makedirs(main.QRS_DIR, exist_ok=True)
    with open(os.path.join(main.UPLOADS_DIR, "readiness.png"), "wb") as f:
        f.write(b"IMG")
    with open(os.path.join(main.QRS_DIR, f"qr_{record_id}.png"), "wb") as f:
        f.write(b"QR")

    token_path = main.patient_url(record_id, "http://testserver").replace("http://testserver", "")
    patient = admin_client.get(token_path)
    assert patient.status_code == 200
    assert "مريض جاهزية" in patient.text

    upload = admin_client.get("/static/uploads/readiness.png")
    assert upload.status_code == 200 and upload.content == b"IMG"
    qr = admin_client.get(f"/static/qrs/qr_{record_id}.png")
    assert qr.status_code == 200 and qr.content == b"QR"


# --- configuration contracts (isolated imports) -----------------------------------


def test_session_secret_unset_warns_and_set_is_respected():
    unset = run_in_isolated_cwd(
        "import main\n"
        "print(main.SESSION_SECRET == 'medical-pacs-super-secret-production-key-2026')\n"
    )
    assert unset.returncode == 0, unset.stderr
    combined = (unset.stdout + unset.stderr)
    assert "auth: SESSION_SECRET is unset" in combined
    assert "True" in unset.stdout.splitlines()

    set_env = run_in_isolated_cwd(
        "import os\n"
        "os.environ['SESSION_SECRET'] = 'prod-session-secret'\n"
        "import main\n"
        "print(main.SESSION_SECRET)\n"
    )
    assert set_env.returncode == 0, set_env.stderr
    assert "prod-session-secret" in set_env.stdout.splitlines()
    assert "auth: SESSION_SECRET is unset" not in (set_env.stdout + set_env.stderr)


def test_qr_signing_secret_unset_warns():
    result = run_in_isolated_cwd("import main\n")
    assert result.returncode == 0, result.stderr
    assert "QR_SIGNING_SECRET is unset" in (result.stdout + result.stderr)


def test_database_url_default_and_override():
    default = run_in_isolated_cwd(
        "import main\n"
        "print(main.SQLALCHEMY_DATABASE_URL)\n"
        "print(main.DEFAULT_DATABASE_URL)\n"
    )
    assert default.returncode == 0, default.stderr
    lines = [line.strip() for line in default.stdout.splitlines() if line.strip()]
    assert lines[-2] == "sqlite:///./medical_pacs.db"
    assert lines[-1] == "sqlite:///./medical_pacs.db"

    override = run_in_isolated_cwd(
        "import os\n"
        "os.environ['DATABASE_URL'] = 'sqlite:///./override.db'\n"
        "import main\n"
        "print(main.SQLALCHEMY_DATABASE_URL)\n"
    )
    assert override.returncode == 0, override.stderr
    assert "sqlite:///./override.db" in override.stdout.splitlines()


def test_database_url_normalizes_postgres_scheme():
    # Managed providers (e.g. Render) may supply postgres://; SQLAlchemy expects postgresql://.
    # Validate normalization without requiring a live Postgres server or driver connection.
    result = run_in_isolated_cwd(
        "import importlib.util, os, pathlib, sys\n"
        "os.environ['DATABASE_URL'] = 'postgres://user:pass@host:5432/dbname'\n"
        "root = pathlib.Path(os.environ['PYTHONPATH'])\n"
        "sys.path.insert(0, str(root))\n"
        "spec = importlib.util.spec_from_file_location('main_dbnorm', root / 'main.py')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "try:\n"
        "    spec.loader.exec_module(mod)\n"
        "except Exception as exc:\n"
        "    # Driver may be unavailable in minimal envs; normalization must still have applied.\n"
        "    print(getattr(mod, 'SQLALCHEMY_DATABASE_URL', ''))\n"
        "    print(type(exc).__name__)\n"
        "else:\n"
        "    print(mod.SQLALCHEMY_DATABASE_URL)\n"
        "    print(mod.engine.dialect.name)\n"
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "postgresql://user:pass@host:5432/dbname" in out
    assert "sqlite" not in (result.stdout + result.stderr).lower() or "postgresql" in result.stdout.lower()


def test_purge_enabled_default_off_and_opt_in():
    # Isolated checks pin the documented contract independent of process-global env.
    default = run_in_isolated_cwd("import main\nprint(main.purge_enabled())\n")
    assert default.returncode == 0, default.stderr
    assert default.stdout.strip().splitlines()[-1] == "False"

    for value, expected in (("1", "True"), ("true", "True"), ("yes", "True"), ("0", "False"), ("false", "False"), ("no", "False")):
        result = run_in_isolated_cwd(
            "import os, main\n"
            f"os.environ['PURGE_ENABLED'] = '{value}'\n"
            "print(main.purge_enabled())\n"
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == expected, f"PURGE_ENABLED={value!r}"


# --- storage configuration --------------------------------------------------------


def test_storage_dirs_default_and_env_configurable():
    """Persistent storage roots default locally but can target a durable disk path.

    Public URL routes and stored DB value formats remain `/static/...` (see other tests);
    this pins that only the backing filesystem location is configurable.
    """
    import tempfile

    default = run_in_isolated_cwd(
        "import os, main\n"
        "print(main.UPLOADS_DIR)\n"
        "print(main.QRS_DIR)\n"
        "print(os.path.isdir(main.UPLOADS_DIR))\n"
        "print(os.path.isdir(main.QRS_DIR))\n"
    )
    assert default.returncode == 0, default.stderr
    lines = [line.strip() for line in default.stdout.splitlines() if line.strip()]
    assert lines[-4:] == ["static/uploads", "static/qrs", "True", "True"]

    with tempfile.TemporaryDirectory(prefix="pacs-storage-") as storage_root:
        storage_posix = storage_root.replace("\\", "/")
        configured = run_in_isolated_cwd(
            "import os\n"
            f"os.environ['STORAGE_DIR'] = r'{storage_root}'\n"
            "import main\n"
            "print(main.UPLOADS_DIR)\n"
            "print(main.QRS_DIR)\n"
            "print(os.path.isdir(main.UPLOADS_DIR))\n"
            "print(os.path.isdir(main.QRS_DIR))\n"
            "name = main.write_qr(123, 'http://example.test')\n"
            "print(name)\n"
            "print(os.path.exists(os.path.join(main.QRS_DIR, name)))\n"
        )
        assert configured.returncode == 0, configured.stderr
        out = [line.strip() for line in configured.stdout.splitlines() if line.strip()]
        assert out[0].replace("/", "\\") == os.path.join(storage_root, "uploads").replace("/", "\\")
        assert out[1].replace("/", "\\") == os.path.join(storage_root, "qrs").replace("/", "\\")
        assert out[2:4] == ["True", "True"]
        assert out[4] == "qr_123.png"
        assert out[5] == "True"


# --- deployment artifacts ---------------------------------------------------------


def test_procfile_runs_uvicorn_app():
    procfile = os.path.join(REPO_ROOT, "Procfile")
    assert os.path.exists(procfile), "Procfile missing"
    with open(procfile, encoding="utf-8") as handle:
        content = handle.read()
    assert "uvicorn" in content and "main:app" in content


# --- DWV orientation fix: backend series grouping ---------------------------------


def _write_test_dicom(name, *, orientation=(1, 0, 0, 0, 1, 0), spacing=(0.5, 0.5),
                      rows=64, columns=64, bits=16):
    """Write a minimal real DICOM file into the configured uploads directory.

    Returns the public URL form (`/static/uploads/<name>`) used in `dicom_file`.
    """
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import generate_uid

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"

    ds = Dataset()
    ds.file_meta = file_meta
    ds.ImageOrientationPatient = list(orientation)
    ds.PixelSpacing = list(spacing)
    ds.Rows = rows
    ds.Columns = columns
    ds.BitsAllocated = bits
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

    path = os.path.join(main.UPLOADS_DIR, name)
    ds.save_as(path, enforce_file_format=False)
    return f"/static/uploads/{name}"


def test_select_primary_series_keeps_largest_compatible_group(clean_static):
    """Mixed-orientation uploads keep the majority series and count the rest as skipped."""
    same_a = _write_test_dicom("a.dcm")
    same_b = _write_test_dicom("b.dcm")
    other = _write_test_dicom("c.dcm", orientation=(0, 1, 0, 1, 0, 0))
    urls = [same_a, same_b, other]

    primary, skipped = main._select_primary_series(urls, record_id=42)

    assert sorted(primary) == sorted([same_a, same_b])
    assert skipped == 1


def test_select_primary_series_single_and_empty_passthrough(clean_static):
    url = _write_test_dicom("single.dcm")
    assert main._select_primary_series([url], record_id=1) == ([url], 0)
    assert main._select_primary_series([], record_id=1) == ([], 0)


def test_select_primary_series_unreadable_files_skipped_when_better_exists(clean_static):
    """Corrupt headers only join the load when there is nothing fingerprintable."""
    good_a = _write_test_dicom("good_a.dcm")
    good_b = _write_test_dicom("good_b.dcm")
    corrupt_path = os.path.join(main.UPLOADS_DIR, "corrupt.dcm")
    with open(corrupt_path, "wb") as handle:
        handle.write(b"not a dicom file at all")
    corrupt = "/static/uploads/corrupt.dcm"

    primary, skipped = main._select_primary_series([good_a, corrupt, good_b], record_id=7)
    assert primary == [good_a, good_b]
    assert skipped == 1

    # With no fingerprintable alternative, unreadable files load alone (defensive group).
    only_corrupt = _write_test_dicom("ignored.dcm")  # ensure dir exists; unused below
    del only_corrupt
    corrupt_only = "/static/uploads/corrupt.dcm"
    primary2, skipped2 = main._select_primary_series([corrupt_only], record_id=8)
    assert primary2 == [corrupt_only]
    assert skipped2 == 0


def test_view_scan_template_warns_on_skipped_files():
    """The viewer template renders the dismissible warning only when skipped_count > 0."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(os.path.join(REPO_ROOT, "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("view_scan.html")
    context = {
        "record": {"id": 1, "patient_name": "مريض", "modality": "CT", "birth_date": "1990-01-01"},
        "dicom_urls": ["/static/uploads/a.dcm"],
    }

    warned = template.render(**context, skipped_count=3)
    assert "تم تخطي 3 ملفات غير متوافقة من العرض" in warned
    assert 'id="skipWarning"' in warned and 'id="dismissSkipWarning"' in warned

    for skipped in (0, None):
        silent = template.render(**context, skipped_count=skipped) if skipped is not None \
            else template.render(**context)
        # Check for the banner markup itself, not the string (the JS references the id).
        assert '<div id="skipWarning"' not in silent, \
            f"warning banner must be absent for skipped_count={skipped!r}"


# --- hard delete: DB row + every server file (previews, DICOM originals, QR) -------

def _write_asset(path: str, content: bytes = b"PHI-BYTES") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def _insert_record_with_qr(**overrides) -> int:
    """Insert a record, then give it a real (non-placeholder) QR filename."""
    record_id = insert_record(**overrides)
    session = main.SessionLocal()
    try:
        record = session.query(main.PatientRecord).filter(main.PatientRecord.id == record_id).first()
        record.qr_code = f"qr_{record_id}.png"
        session.commit()
    finally:
        session.close()
    return record_id


def test_admin_delete_is_hard_delete_including_dicom_originals(admin_client, clean_static):
    preview = _write_asset(os.path.join(main.UPLOADS_DIR, "rec_preview.png"))
    original = _write_asset(os.path.join(main.UPLOADS_DIR, "rec_stack.dcm"), b"DICM\x00ORIGINAL")
    record_id = _insert_record_with_qr(
        image_path="/static/uploads/rec_preview.png",
        dicom_file="/static/uploads/rec_stack.dcm",
    )
    qr = _write_asset(os.path.join(main.QRS_DIR, f"qr_{record_id}.png"))

    response = admin_client.post(f"/doctor/delete/{record_id}", follow_redirects=False)

    assert response.status_code == 303
    assert get_record(record_id) is None, "record row must be hard-deleted from the database"
    for path in (preview, original, qr):
        assert not os.path.exists(path), f"{path} must be gone from the server"


def test_technician_delete_is_hard_delete_including_dicom_originals(technician_client, clean_static):
    preview = _write_asset(os.path.join(main.UPLOADS_DIR, "tech_preview.png"))
    original = _write_asset(os.path.join(main.UPLOADS_DIR, "tech_stack.dcm"), b"DICM\x00ORIGINAL")
    record_id = _insert_record_with_qr(
        image_path="/static/uploads/tech_preview.png",
        dicom_file="/static/uploads/tech_stack.dcm",
    )
    qr = _write_asset(os.path.join(main.QRS_DIR, f"qr_{record_id}.png"))

    response = technician_client.post(f"/technician/delete/{record_id}", follow_redirects=False)

    assert response.status_code == 303
    assert get_record(record_id) is None, "record row must be hard-deleted from the database"
    for path in (preview, original, qr):
        assert not os.path.exists(path), f"{path} must be gone from the server"


def test_delete_refuses_paths_outside_storage_roots(admin_client, clean_static):
    """A stored `../` path must never delete files outside the uploads/QR roots."""
    canary_dir = os.path.join(main.UPLOADS_DIR, "..", "escape-test")
    canary = _write_asset(os.path.join(canary_dir, "canary.txt"))
    record_id = insert_record(image_path="/static/uploads/../escape-test/canary.txt")

    admin_client.post(f"/doctor/delete/{record_id}")

    assert os.path.exists(canary), "file outside the storage root must not be deleted"
    os.remove(canary)
    os.rmdir(canary_dir)


def test_cleanup_old_records_removes_dicom_originals(clean_static):
    preview = _write_asset(os.path.join(main.UPLOADS_DIR, "old_preview.png"))
    original = _write_asset(os.path.join(main.UPLOADS_DIR, "old_stack.dcm"), b"DICM\x00OLD")
    old_stamp = (datetime.datetime.now() - datetime.timedelta(days=40)).strftime(main.TIMESTAMP_FORMAT)
    record_id = insert_record(
        created_at=old_stamp,
        image_path="/static/uploads/old_preview.png",
        dicom_file="/static/uploads/old_stack.dcm",
    )

    purged = main.cleanup_old_records(main.SessionLocal())

    assert purged == 1
    assert get_record(record_id) is None
    assert not os.path.exists(preview)
    assert not os.path.exists(original)


# --- 30-day retention: background sweep configuration ------------------------------


def test_retention_window_and_background_sweep_configured():
    assert main.RETENTION_DAYS == 30
    assert main.RETENTION_SWEEP_INTERVAL_SECONDS == 24 * 60 * 60
    import inspect
    assert inspect.iscoroutinefunction(main._retention_sweep_loop)
    # Retention stays opt-in: the background sweep must respect the same gate as the
    # on-visit sweep (asserted separately by test_purge_enabled_default_off_and_opt_in).


def test_retention_days_env_configurable():
    result = run_in_isolated_cwd(
        "import os\n"
        "os.environ['RETENTION_DAYS'] = '90'\n"
        "import main\n"
        "print(main.RETENTION_DAYS)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "90"


# --- galleries never render non-image entries as broken <img> ----------------------


def test_galleries_hide_non_image_entries(admin_client, clean_static):
    _write_asset(os.path.join(main.UPLOADS_DIR, "ok_preview.png"))
    _write_asset(os.path.join(main.UPLOADS_DIR, "ok_stack.dcm"), b"DICM\x00DATA")
    record_id = insert_record(
        image_path="/static/uploads/ok_preview.png,/static/uploads/ok_stack.dcm",
        dicom_file="/static/uploads/ok_stack.dcm",
    )

    png_page = admin_client.get(f"/view-png/{record_id}").text
    assert "/static/uploads/ok_preview.png" in png_page
    assert "ok_stack.dcm" not in png_page, "a .dcm fallback entry must not render as <img>"

    token = main.mint_patient_token(record_id)
    patient_page = admin_client.get(f"/patient/{token}").text
    assert "/static/uploads/ok_preview.png?patient_token=" in patient_page
    assert "ok_stack.dcm" not in patient_page, "a .dcm fallback entry must not render as <img>"
