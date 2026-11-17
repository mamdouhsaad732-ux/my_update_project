"""Ticket 02 — signed QR credentials.

The contract these tests pin (spec: `.scratch/qr-credentials/spec.md`, ADR-0001):

    mint_patient_token(id) -> str        read_patient_token(token) -> id
    patient_url(id, base)  -> str        write_qr(id, base)        -> "qr_<id>.png"
    legacy_patient_urls_enabled() -> bool
    GET /patient/<token>   signed token -> 200 | 404
    GET /patient/<digits>  legacy flag  -> 303 redirect | 404
"""

import logging
import os
import re
from urllib.parse import urlparse

import pytest

import main
from conftest import ONE_PIXEL_PNG, get_record, insert_record

# itsdangerous emits ``payload.timestamp.signature``: base64url plus dot separators,
# all legal inside one URL path segment.
TOKEN_PATH = re.compile(r"^/patient/(?P<token>[A-Za-z0-9_\-.=]+)$")


def _path(record_id: int, base: str = "http://testserver") -> str:
    """Path component of a minted patient URL, so TestClient can request it."""
    return urlparse(main.patient_url(record_id, base)).path


# --- the token layer ------------------------------------------------------------


def test_minted_token_round_trips():
    assert main.read_patient_token(main.mint_patient_token(42)) == 42


def test_token_is_not_the_raw_id():
    token = main.mint_patient_token(42)
    assert token != "42", "a credential that is just the primary key is enumerable"
    assert "/" not in token, "token must be a single URL path segment"
    assert TOKEN_PATH.match(f"/patient/{token}"), f"token is not URL-safe: {token!r}"


def test_distinct_records_get_distinct_tokens():
    first = main.mint_patient_token(1)
    second = main.mint_patient_token(2)
    assert first != second
    assert main.read_patient_token(first) == 1
    assert main.read_patient_token(second) == 2


def test_patient_url_builds_a_verifying_link():
    url = main.patient_url(42, "https://pacs.example.test/")

    assert url.startswith("https://pacs.example.test/patient/"), url
    assert "//patient" not in url, "trailing slash on the base was not normalised"
    token = urlparse(url).path.rsplit("/", 1)[1]
    assert main.read_patient_token(token) == 42


def test_payload_stays_scan_friendly():
    payload = main.patient_url(123456, "https://al-pacs-system-1.onrender.com")
    assert len(payload) < 512, f"QR payload too long to scan reliably: {len(payload)} chars"


# --- the route ------------------------------------------------------------------


def test_signed_token_opens_the_patient_page(admin_client):
    record_id = insert_record(name="سالم الاختبار")

    response = admin_client.get(_path(record_id))

    assert response.status_code == 200
    assert "سالم الاختبار" in response.text


def _flip_middle(text: str) -> str:
    """Change one base64 digit in the middle of a segment.

    Flipping the *last* character is not a tamper: the final digit of an unpadded
    base64 segment carries padding bits, so the decoded bytes can stay identical and
    the signature still verifies. That made the earlier version of this test flaky.
    """
    index = len(text) // 2
    replacement = "A" if text[index] != "A" else "B"
    return text[:index] + replacement + text[index + 1 :]


def test_tampered_token_is_refused(admin_client):
    record_id = insert_record()
    token = main.mint_patient_token(record_id)
    payload, timestamp, signature = token.split(".")
    tampered = ".".join([payload, timestamp, _flip_middle(signature)])

    response = admin_client.get(f"/patient/{tampered}")

    assert response.status_code == 404, "a bad signature must not 500 or leak a parse error"


@pytest.mark.parametrize("token", ["not-a-token", "abc.def.ghi", "AAAA"])
def test_garbage_tokens_are_404_not_500(admin_client, token):
    response = admin_client.get(f"/patient/{token}", follow_redirects=False)
    assert response.status_code == 404, f"unexpected status for {token!r}"


@pytest.mark.parametrize(
    "identifier",
    [
        "\u00b2",  # superscript two: isdigit() is True, int() raises
        "\u2461",  # circled two: same trap
        "9" * 5000,  # past CPython's 4300-digit int conversion limit
    ],
)
def test_unconvertible_numeric_identifiers_are_404(admin_client, identifier):
    """`str.isdigit()` is not the same question as `int()` — asking the wrong one 500s."""
    response = admin_client.get(f"/patient/{identifier}", follow_redirects=False)
    assert response.status_code == 404


def test_token_for_unknown_record_is_404(admin_client):
    response = admin_client.get(_path(999_999))
    assert response.status_code == 404


def test_secret_change_invalidates_tokens(admin_client, monkeypatch):
    monkeypatch.setenv("QR_SIGNING_SECRET", "signing-secret-one")
    record_id = insert_record()
    path = _path(record_id)

    monkeypatch.setenv("QR_SIGNING_SECRET", "signing-secret-two")
    response = admin_client.get(path)

    assert response.status_code == 404, "tokens must be bound to the current signing secret"


def test_signing_secret_falls_back_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("QR_SIGNING_SECRET", raising=False)
    assert main.qr_signing_secret(), "a fallback secret is required so QR minting never crashes"


# --- legacy integer URLs ---------------------------------------------------------


def test_legacy_numeric_url_redirects_when_enabled(admin_client, monkeypatch):
    monkeypatch.setenv("LEGACY_PATIENT_URLS", "true")
    record_id = insert_record(name="مريض قديم")

    response = admin_client.get(f"/patient/{record_id}", follow_redirects=False)

    assert response.status_code == 303, "legacy printed QRs must keep working during transition"
    location = response.headers["location"]
    assert urlparse(location).netloc == "", (
        f"legacy redirect must be a relative path, not a Host-header-derived absolute URL: {location!r}"
    )
    match = TOKEN_PATH.match(urlparse(location).path)
    assert match, f"legacy redirect must target a signed URL, got {location!r}"
    assert main.read_patient_token(match.group("token")) == record_id

    followed = admin_client.get(urlparse(location).path)
    assert followed.status_code == 200
    assert "مريض قديم" in followed.text


def test_legacy_numeric_url_redirects_when_flag_is_unset(admin_client, monkeypatch):
    monkeypatch.delenv("LEGACY_PATIENT_URLS", raising=False)
    record_id = insert_record()

    response = admin_client.get(f"/patient/{record_id}", follow_redirects=False)

    assert response.status_code == 303
    assert TOKEN_PATH.match(urlparse(response.headers["location"]).path)


def test_legacy_hit_is_logged_once(admin_client, monkeypatch, caplog):
    """The log line is the evidence for retiring the flag; one hit, one line."""
    monkeypatch.setenv("LEGACY_PATIENT_URLS", "true")
    record_id = insert_record()

    with caplog.at_level(logging.INFO, logger="main"):
        admin_client.get(f"/patient/{record_id}", follow_redirects=False)

    hits = [r for r in caplog.records if "legacy numeric URL" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in caplog.records]
    assert f"record id={record_id}" in hits[0].getMessage()


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_legacy_numeric_url_is_404_when_disabled(admin_client, monkeypatch, value):
    monkeypatch.setenv("LEGACY_PATIENT_URLS", value)
    record_id = insert_record()

    response = admin_client.get(f"/patient/{record_id}", follow_redirects=False)

    assert response.status_code == 404, f"LEGACY_PATIENT_URLS={value!r} must close enumeration"


def test_legacy_flag_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("LEGACY_PATIENT_URLS", raising=False)
    assert main.legacy_patient_urls_enabled() is True


# --- one QR writer, both call sites ----------------------------------------------


def test_upload_qr_payload_is_a_signed_patient_url(technician_client, captured_qr, clean_static):
    response = technician_client.post(
        "/technician/upload",
        data={"patient_name": "مريض رفع", "birth_date": "1990-01-01", "modality": "CT"},
        files={"files": ("scan.png", ONE_PIXEL_PNG, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]
    assert len(captured_qr) == 1, f"expected exactly one QR mint per upload, got {captured_qr}"

    payload = captured_qr[0]
    parsed = urlparse(payload)
    assert parsed.scheme in ("http", "https"), payload
    assert parsed.netloc == "testserver", f"upload QR used a hardcoded host: {payload}"
    match = TOKEN_PATH.match(parsed.path)
    assert match, f"payload is not a signed patient URL: {payload}"

    session = main.SessionLocal()
    try:
        record = (
            session.query(main.PatientRecord)
            .order_by(main.PatientRecord.id.desc())
            .first()
        )
        assert record is not None, "upload did not create a record"
        assert main.read_patient_token(match.group("token")) == record.id
        assert record.qr_code == f"qr_{record.id}.png"
    finally:
        session.close()


def test_report_save_qr_payload_is_a_signed_patient_url(admin_client, captured_qr, clean_static):
    record_id = insert_record()

    response = admin_client.post(
        "/save-report-inline",
        data={"record_id": record_id, "report": "تقرير جديد"},
        follow_redirects=False,
    )
    assert response.status_code in (200, 303), response.text[:400]
    assert len(captured_qr) == 1, f"expected exactly one QR mint per report save, got {captured_qr}"

    payload = captured_qr[0]
    parsed = urlparse(payload)
    assert parsed.netloc == "testserver", (
        f"report-save QR still points at a hardcoded host: {payload}"
    )
    match = TOKEN_PATH.match(parsed.path)
    assert match, f"payload is not a signed patient URL: {payload}"
    assert main.read_patient_token(match.group("token")) == record_id

    saved = get_record(record_id)
    assert saved.report == "تقرير جديد"
    assert saved.qr_code == f"qr_{record_id}.png"


def test_write_qr_returns_the_expected_filename(clean_static):
    record_id = insert_record()

    filename = main.write_qr(record_id, "http://testserver")

    assert filename == f"qr_{record_id}.png"
    assert os.path.exists(os.path.join("static", "qrs", filename))


def test_no_shadowed_qr_writer_remains():
    """Two minting implementations once coexisted and the later one silently won."""
    assert not hasattr(main, "generate_patient_qr"), "a second QR writer shadows the real one"
