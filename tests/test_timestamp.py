"""Ticket 01 — timestamp integrity, purge opt-in, DATABASE_URL seam.

Environment setup lives in `conftest.py`, which pytest imports before this module.
"""

import datetime
import logging
import os

import pytest

import main
from conftest import (
    ONE_PIXEL_PNG,
    TEST_DB_PATH,
    get_record,
    insert_record,
    run_in_isolated_cwd,
)

DEFAULT_DB_URL = "sqlite:///./medical_pacs.db"


def _stamp(days_ago: float = 0) -> str:
    moment = datetime.datetime.now() - datetime.timedelta(days=days_ago)
    return moment.strftime(main.TIMESTAMP_FORMAT)


# --- the frozen-scalar defect --------------------------------------------------


def test_created_at_default_is_callable(clean_db):
    """A scalar default is evaluated once at import; only a callable is per-insert."""
    column = main.PatientRecord.__table__.c.created_at
    assert column.default is not None, "created_at must declare a default"
    assert callable(column.default.arg), (
        f"created_at default is a frozen value, not a callable: {column.default.arg!r}"
    )


def test_two_records_get_distinct_parseable_timestamps(clean_db):
    """The core symptom: every row in one process shared the import-time stamp."""
    first_id = insert_record()
    second_id = insert_record()

    first = get_record(first_id).created_at
    second = get_record(second_id).created_at

    assert first != second, "both records share one timestamp (import-time default)"
    now = datetime.datetime.now()
    for stamp in (first, second):
        parsed = main.parse_timestamp(stamp)
        assert abs((now - parsed).total_seconds()) < 120, f"stamp is not fresh: {stamp}"


def test_default_format_is_always_microsecond_precision(clean_db):
    """`str(datetime)` drops the microseconds when they are zero; the format must not depend on luck."""
    for _ in range(50):
        stamp = main.created_at_default()
        assert len(stamp) == 26, f"unexpected stamp shape: {stamp!r}"
        main.parse_timestamp(stamp)  # raises if the format is not %Y-%m-%d %H:%M:%S.%f


def test_parse_timestamp_accepts_legacy_rows_without_microseconds():
    parsed = main.parse_timestamp("2026-01-02 03:04:05")
    assert parsed == datetime.datetime(2026, 1, 2, 3, 4, 5)


def test_records_carry_their_own_date_for_archive_grouping(clean_db):
    """Archive pages group by created_at[:10]; a frozen stamp put every row in one bucket."""
    today_id = insert_record()
    older_id = insert_record(created_at=_stamp(days_ago=2))

    today_day = get_record(today_id).created_at[:10]
    older_day = get_record(older_id).created_at[:10]

    assert today_day == datetime.datetime.now().strftime("%Y-%m-%d")
    assert older_day == (datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    assert today_day != older_day


# --- the DATABASE_URL seam -----------------------------------------------------


def test_database_url_env_is_honoured(clean_db):
    # Compare the resolved filesystem path: SQLAlchemy percent-encodes the drive colon in
    # str(url), which says nothing about which database we are actually bound to.
    resolved = main.engine.url.database
    assert os.path.normcase(os.path.abspath(resolved)) == os.path.normcase(
        os.path.abspath(TEST_DB_PATH)
    ), f"engine is bound to {resolved!r}, not the DATABASE_URL test database"


def test_database_url_falls_back_to_default():
    """With DATABASE_URL unset the engine must resolve to the historical path, in cwd."""
    result = run_in_isolated_cwd(
        "import main; print(main.engine.url)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == DEFAULT_DB_URL


# --- the purge must be opt-in ---------------------------------------------------


def test_purge_is_disabled_by_default(admin_client):
    """A 40-day-old record must survive a dashboard visit when PURGE_ENABLED is unset."""
    os.environ.pop("PURGE_ENABLED", None)
    old_id = insert_record(created_at=_stamp(days_ago=40))

    response = admin_client.get("/doctor")

    assert response.status_code == 200
    assert get_record(old_id) is not None, "purge ran without being enabled"


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_explicit_false_values_do_not_purge(admin_client, monkeypatch, value):
    monkeypatch.setenv("PURGE_ENABLED", value)
    old_id = insert_record(created_at=_stamp(days_ago=40))

    admin_client.get("/doctor")

    assert get_record(old_id) is not None, f"PURGE_ENABLED={value!r} must not enable retention"


def test_purge_enabled_deletes_old_records_and_logs(admin_client, caplog):
    old_id = insert_record(created_at=_stamp(days_ago=40))
    with caplog.at_level(logging.INFO, logger="main"):
        os.environ["PURGE_ENABLED"] = "true"
        try:
            response = admin_client.get("/doctor")
        finally:
            os.environ.pop("PURGE_ENABLED", None)

    assert response.status_code == 200
    assert get_record(old_id) is None, "PURGE_ENABLED=true did not delete the stale record"

    messages = [record.getMessage() for record in caplog.records if record.name == "main"]
    per_record = [m for m in messages if m.startswith(f"retention: purged record id={old_id} ")]
    assert len(per_record) == 1, f"expected exactly one purge log line for id={old_id}: {messages}"
    assert any(m.startswith("retention: sweep removed 1 record(s)") for m in messages), messages


def test_purge_enabled_keeps_recent_records(admin_client):
    recent_id = insert_record(created_at=_stamp(days_ago=5))
    os.environ["PURGE_ENABLED"] = "true"
    try:
        admin_client.get("/doctor")
    finally:
        os.environ.pop("PURGE_ENABLED", None)

    assert get_record(recent_id) is not None, "purge deleted a record inside the 30-day window"


@pytest.mark.parametrize("value", ["1", "yes", "TRUE", "True"])
def test_purge_flag_accepts_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv("PURGE_ENABLED", value)
    assert main.purge_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off", "on"])
def test_purge_flag_rejects_everything_else(monkeypatch, value):
    monkeypatch.setenv("PURGE_ENABLED", value)
    assert main.purge_enabled() is False


def test_retention_log_is_visible_without_host_logging_config():
    """uvicorn leaves the root logger handler-less; the purge log must still be emitted."""
    result = run_in_isolated_cwd(
        "import logging, main; print(main.logger.isEnabledFor(logging.INFO)); "
        "main.logger.info('retention probe')"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[0] == "True", (
        f"INFO is filtered out under a bare interpreter: {result.stdout!r}"
    )
    assert "retention probe" in result.stderr, "log record never reached a handler"


# --- record creation must be unchanged ------------------------------------------


def test_upload_creates_record_with_fresh_timestamp(technician_client, clean_db, clean_static):
    response = technician_client.post(
        "/technician/upload",
        data={"patient_name": "مريض اختبار", "birth_date": "1990-01-01", "modality": "CT"},
        files={"files": ("scan.png", ONE_PIXEL_PNG, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]

    db = main.SessionLocal()
    try:
        record = db.query(main.PatientRecord).order_by(main.PatientRecord.id.desc()).first()
    finally:
        db.close()

    assert record is not None, "upload did not create a record"
    created = main.parse_timestamp(record.created_at)
    assert abs((datetime.datetime.now() - created).total_seconds()) < 120
    assert record.qr_code.startswith("qr_"), "upload did not attach a QR code"
    assert record.image_path.startswith("/static/uploads/")
