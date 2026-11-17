from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine, Column, Integer, String, true
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fastapi.templating import Jinja2Templates
from itsdangerous import BadData, URLSafeTimedSerializer
import hashlib
import hmac
import logging
import os
import secrets
import shutil
import datetime
import qrcode
from PIL import Image
from typing import List
import pydicom
import numpy as np
import io


DEFAULT_DATABASE_URL = "sqlite:///./medical_pacs.db"
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

# `check_same_thread` is a SQLite-only connect argument. The DATABASE_URL seam accepts any
# scheme, and create_engine() raises TypeError on a connect arg the dialect doesn't know.
CONNECT_ARGS = (
    {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=CONNECT_ARGS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
LEGACY_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
TRUTHY_VALUES = frozenset({"1", "true", "yes"})

# Insecure fallback: published in source and used only when no env secret is provided.
_DEFAULT_SESSION_SECRET = "medical-pacs-super-secret-production-key-2026"
SESSION_SECRET = os.getenv("SESSION_SECRET") or _DEFAULT_SESSION_SECRET
QR_TOKEN_SALT = "qr-v1"

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Make this module's INFO output visible when the host app configured nothing.

    uvicorn configures its own loggers and leaves the root logger without handlers, so a
    library logger's INFO records are dropped in deployment while still being captured by
    pytest's caplog. Install a root handler only when there isn't one, so a host app's
    logging configuration (and caplog) always wins.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


_configure_logging()

if SESSION_SECRET == _DEFAULT_SESSION_SECRET:
    logger.warning(
        "auth: SESSION_SECRET is unset — using the built-in fallback session secret, which is "
        "published in this repository. Set SESSION_SECRET before handling real sessions or PHI."
    )

if not os.getenv("QR_SIGNING_SECRET"):
    logger.warning(
        "qr: QR_SIGNING_SECRET is unset — patient QR tokens are being signed with the "
        "session secret. Set QR_SIGNING_SECRET before printing labels for real patients."
    )


def created_at_default() -> str:
    """Return a fresh timestamp for each insert.

    Always a ``str`` in ``TIMESTAMP_FORMAT``: the column is ``String``, ``parse_timestamp``
    inverts it, and the archive pages slice ``created_at[:10]``. ``str(datetime)`` would
    silently drop the microseconds whenever they are zero, breaking that guarantee.
    """
    return datetime.datetime.now().strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime.datetime:
    """Inverse of ``created_at_default``, tolerant of older rows written without microseconds."""
    try:
        return datetime.datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return datetime.datetime.strptime(value, LEGACY_TIMESTAMP_FORMAT)


def purge_enabled() -> bool:
    """Retention is opt-in: deleting patient data by accident is worse than not at all."""
    return os.getenv("PURGE_ENABLED", "").strip().lower() in TRUTHY_VALUES


def qr_signing_secret() -> str:
    """Signing key for patient QR tokens.

    Read per call, so rotating the key takes effect without a restart. Until Ticket 04
    lands, the fallback is the same literal the session cookie signs with — rotating one
    rotates both, which mints new tokens and invalidates every printed label at once.
    """
    return os.getenv("QR_SIGNING_SECRET") or SESSION_SECRET


def _qr_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(qr_signing_secret(), salt=QR_TOKEN_SALT)


def mint_patient_token(record_id: int) -> str:
    """A signed QR credential: unforgeable without the QR secret, but not opaque (ADR-0001)."""
    return _qr_serializer().dumps(record_id)


def read_patient_token(token: str) -> int:
    """Verify a QR credential and return the record id it authorises.

    Raises ``itsdangerous.BadData`` for a tampered, foreign-keyed or truncated token.
    """
    return int(_qr_serializer().loads(token, max_age=None))


def patient_url(record_id: int, base_url: str) -> str:
    """The canonical, unsigned-out patient link: the only place a QR target is built."""
    return f"{base_url.rstrip('/')}/patient/{mint_patient_token(record_id)}"


def write_qr(record_id: int, base_url: str) -> str:
    """Mint the patient URL, render its QR into ``static/qrs``, return the filename.

    The single writer for both call sites. ``fit=True`` sizes the grid to the payload,
    which is longer than the numeric paths this replaced.
    """
    payload = patient_url(record_id, base_url)
    qr = qrcode.QRCode(version=2, box_size=10, border=5)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    filename = f"qr_{record_id}.png"
    path = os.path.join("static", "qrs", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return filename


def legacy_patient_urls_enabled() -> bool:
    """Labels printed before signed URLs existed keep working until the flag is retired."""
    return os.getenv("LEGACY_PATIENT_URLS", "true").strip().lower() in TRUTHY_VALUES


def safe_next_path(next_url: str, fallback: str) -> str:
    """Redirect target for a form submission, which is attacker-controlled input.

    Only same-origin relative paths are allowed. Anything with a scheme, a protocol-relative
    prefix, a backslash (browsers normalise ``/\\host`` to ``//host``), a space, or a control
    character is discarded in favour of ``fallback`` rather than rejected with an error.
    """
    if not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url:
        return fallback
    if any(ord(character) < 0x20 or ord(character) == 0x7F or character == " " for character in next_url):
        return fallback
    return next_url


class PatientRecord(Base):
    __tablename__ = "patient_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, index=True)
    birth_date = Column(String)
    modality = Column(String)
    image_path = Column(String)
    report = Column(String, default="بانتظار كتابة التقرير الطبي من السكرتارية...")
    qr_code = Column(String)
    created_at = Column(String, default=created_at_default)
    dicom_file=Column(String,nullable=true)

Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")


app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


env = Environment(loader=FileSystemLoader("templates"))


_PASSWORD_HASH_ITERATIONS = 200_000


def hash_password(plain: str, *, iterations: int = _PASSWORD_HASH_ITERATIONS) -> str:
    """Return a salted, non-reversible password hash suitable for `USERS` storage."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time verification against a hash produced by `hash_password`."""
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


USERS = {
    "ct_user": {"password": hash_password("123"), "role": "technician", "modality": "CT", "name": "فني الطبقي المحوري"},
    "mri_user": {"password": hash_password("123"), "role": "technician", "modality": "MRI", "name": "فني الرنين المغناطيسي"},
    "xray_user": {"password": hash_password("123"), "role": "technician", "modality": "X-Ray", "name": "فني الأشعة السينية"},
    "echo_user": {"password": hash_password("123"), "role": "technician", "modality": "Echo", "name": "فني الأمواج فوق الصوتية"},
    "secretary": {"password": hash_password("123"), "role": "secretary", "name": "موظف الاستقبال والسكرتارية"},
    "samer": {"password": hash_password("123"), "role": "admin", "name": "الدكتور سامر (الأدمن المطلق)"}
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def cleanup_old_records(db: Session) -> int:
    """Delete records older than 30 days, returning how many were purged.

    Destructive by nature, so callers must gate it on ``purge_enabled()``. Records are
    logged only after the commit succeeds: a rolled-back delete is not a deletion.
    """
    purged = []
    try:
        threshold_date = datetime.datetime.now() - datetime.timedelta(days=30)
        for record in db.query(PatientRecord).all():
            if not record.created_at:
                continue
            try:
                record_date = parse_timestamp(record.created_at)
            except (TypeError, ValueError):
                logger.warning(
                    "retention: skipping record id=%s with unparseable created_at=%r",
                    record.id,
                    record.created_at,
                )
                continue
            if record_date >= threshold_date:
                continue
            try:
                record_id, record_created_at = record.id, record.created_at
                if record.image_path:
                    for p in record.image_path.split(","):
                        img_file = p.strip().lstrip("/")
                        if os.path.exists(img_file):
                            os.remove(img_file)
                if record.qr_code and record.qr_code != "temp.png":
                    qr_file = f"static/qrs/{record.qr_code}"
                    if os.path.exists(qr_file):
                        os.remove(qr_file)
                db.delete(record)
                purged.append((record_id, record_created_at))
            except Exception:
                # Filesystem failure on one record must not abort the sweep, but it must
                # not be silent either: the record stays and the next sweep retries.
                logger.warning("retention: could not purge record id=%s", record.id, exc_info=True)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("retention: sweep failed; no records were purged")
        return 0
    for record_id, record_created_at in purged:
        logger.info("retention: purged record id=%s created_at=%s", record_id, record_created_at)
    if purged:
        logger.info("retention: sweep removed %d record(s) older than 30 days", len(purged))
    return len(purged)

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    if "user" in request.session:
        role = request.session["user"]["role"]
        if role == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "admin":return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
    
    template = env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request))

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    template = env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request))

@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    user = USERS.get(username)
    if user and verify_password(password, user["password"]):
        request.session["user"] = user
        role = user["role"]
        if role == "admin":
            return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/view-scan/{record_id}", response_class=HTMLResponse) 
def view_scan(request: Request, record_id: int, db: Session = Depends(get_db)):
    # 1. التحقق من صلاحية الأدمن
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # 2. جلب بيانات السجل
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first() 
    if not record: 
        raise HTTPException(status_code=404, detail="السجل غير موجود")

    # 3. جلب مسارات الصور اعتماداً على الحقل image_path في قاعدة البيانات
    dicom_urls = []
    if record.image_path:
        dicom_urls = [p.strip() for p in record.image_path.split(",") if p.strip()]

    # 4. إرسال البيانات إلى صفحة المعاينة المستقلة view_scan.html
    template = env.get_template("view_scan.html")
    return HTMLResponse(content=template.render(
        request=request, 
        record=record, 
        dicom_urls=dicom_urls
    ))

@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if purge_enabled():
        cleanup_old_records(db)
    records = db.query(PatientRecord).all()
    template = env.get_template("doctor.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"]))

@app.post("/doctor/delete/{record_id}")
def doctor_delete_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record:
        if record.image_path:
            for p in record.image_path.split(","):
                img_file = p.strip().lstrip("/")
                if os.path.exists(img_file):
                    os.remove(img_file)
        if record.qr_code and record.qr_code != "temp.png":
            qr_file = f"static/qrs/{record.qr_code}"
            if os.path.exists(qr_file):
                os.remove(qr_file)
        
        db.delete(record)
        db.commit()
        
    return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)

# --- مسارات الأرشيف ---


@app.get("/doctor/archive", response_class=HTMLResponse)
def archive_home(request: Request):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    html_content = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الفحوصات الطبية الهرمي</title>
    <style>
        body { font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }
        .container { max-width: 900px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }
        h2 { color: #1e3a8a; margin-bottom: 5px; }
        p { color: #64748b; margin-bottom: 30px; font-size: 14px; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-bottom: 30px; }
        .card { background: #f1f5f9; border: 1px solid #cbd5e1; padding: 25px; border-radius: 8px; text-decoration: none; color: #1e3a8a; font-weight: bold; font-size: 18px; transition: 0.2s; display: block; }
        .card:hover { background: #1e3a8a; color: white; transform: translateY(-2px); }
        .btn-back { background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الفحوصات الطبية الهرمي</h2>
        <p>اختر نوع الجهاز (Modality) لعرض أرشيف الفحوصات حسب الترتيب الزمني</p>
        <div class="grid">
            <a href="/doctor/archive/CT" class="card">📁 أرشيف الطبقي المحوري (CT)</a>
            <a href="/doctor/archive/MRI" class="card">📁 أرشيف الرنين المغناطيسي (MRI)</a>
            <a href="/doctor/archive/X-Ray" class="card">📁 أرشيف الأشعة السينية (X-Ray)</a>
            <a href="/doctor/archive/Echo" class="card">📁 أرشيف الأمواج فوق الصوتية (Echo)</a>
        </div>
        <a href="/doctor" class="btn-back">← العودة إلى لوحة تحكم الأدمن</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.get("/doctor/archive/{modality}", response_class=HTMLResponse)
def archive_months(modality: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        months = sorted(list(set([str(r.created_at)[:7] for r in mod_records if r.created_at and len(str(r.created_at)) >= 7])), reverse=True)
        months_html = "".join([f'<a href="/doctor/archive/{modality}/{m}" class="item">📅 شهر: {m}</a>' for m in months]) if months else '<div class="no-data">لا توجد سجلات مسجلة لهذا الجهاز.</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الشهور - {modality}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }}
        .container {{ max-width: 800px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }}
        h2 {{ color: #1e3a8a; margin-bottom: 25px; }}
        .list {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px; }}
        .item {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 6px; text-decoration: none; color: #2563eb; font-weight: bold; font-size: 16px; display: block; }}
        .item:hover {{ background: #2563eb; color: white; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
        .no-data {{ color: #64748b; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الشهور لجهاز: {modality}</h2>
        <div class="list">{months_html}</div>
        <a href="/doctor/archive" class="btn-back">← العودة لاختيار الأجهزة</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; padding:30px; color:red;'><h3>خطأ:</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/doctor/archive/{modality}/{month}", response_class=HTMLResponse)
def archive_days(modality: str, month: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        month_records = [r for r in mod_records if r.created_at and str(r.created_at).startswith(month)]
        days = sorted(list(set([str(r.created_at)[:10] for r in month_records if len(str(r.created_at)) >= 10])), reverse=True)
        days_html = "".join([f'<a href="/doctor/archive/{modality}/{month}/{d}" class="item">📆 يوم: {d}</a>' for d in days]) if days else '<div class="no-data">لا توجد سجلات في هذا الشهر.</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الأيام - {month}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }}
        .container {{ max-width: 800px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }}
        h2 {{ color: #1e3a8a; margin-bottom: 25px; }}
        .list {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px; }}
        .item {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 6px; text-decoration: none; color: #16a34a; font-weight: bold; font-size: 16px; display: block; }}
        .item:hover {{ background: #16a34a; color: white; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
        .no-data {{ color: #64748b; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الأيام لشهر: {month} ({modality})</h2>
        <div class="list">{days_html}</div>
        <a href="/doctor/archive/{modality}" class="btn-back">← العودة للشهور</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; padding:30px; color:red;'><h3>خطأ:</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/doctor/archive/{modality}/{month}/{day}", response_class=HTMLResponse)
def archive_records(modality: str, month: str, day: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        day_records = [r for r in mod_records if r.created_at and str(r.created_at).startswith(day)]
        
        rows_html = ""
        if day_records:
            for record in day_records:
                qr_element = f'<img src="/static/qrs/{record.qr_code}" class="qr-img" alt="QR">' if record.qr_code and record.qr_code != "temp.png" else '<span>-</span>'
                rows_html += f"""
                <tr>
                    <td><b>#{record.id}</b></td>
                    <td>{record.patient_name}</td>
                    <td>{record.birth_date}</td>
                    <td><a href="/doctor/view-images/{record.id}" class="btn" style="background: #0284c7;">عرض وفحص الصور</a></td>
                    <td>{qr_element}</td>
                    <td>
                        <form action="/save-report" method="post" onsubmit="return confirm('هل أنت متأكد من حفظ التقرير الطبي؟');">
                            <input type="hidden" name="record_id" value="{record.id}">
                            <input type="hidden" name="next" value="/doctor/archive/{modality}/{month}/{day}">
                            <textarea name="report">{record.report}</textarea>
                            <br><button type="submit" class="btn-save" style="margin-top: 5px;">حفظ التقرير</button>
                        </form>
                    </td>
                    <td>
                        <a href="/download-report/{record.id}" onclick="return confirm('هل تريد حفظ وطباعة التقرير الآن؟');" class="btn" style="background: #0284c7; margin-bottom: 5px; display: block;">Word / طباعة</a>
                        <a href="/patient/{record.id}" target="_blank" class="btn" style="background: #9333ea; display: block; margin-bottom: 5px;">QR</a>
                        <form action="/doctor/delete/{record.id}" method="post" onsubmit="return confirm('هل أنت متأكد من حذف هذا السجل والصور نهائياً؟');">
                            <button type="submit" class="btn" style="background: #dc2626; border:none; cursor:pointer; width:100%;">حذف السجل</button>
                        </form>
                    </td>
                </tr>"""
        else:
            rows_html = '<tr><td colspan="7" style="padding: 30px; color: #64748b;">لا توجد سجلات في هذا اليوم.</td></tr>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>سجلات تاريخ: {day}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 30px; color: #1e293b; }}
        .container {{ max-width: 1250px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); border: 1px solid #e2e8f0; }}
        .header h2 {{ color: #1e3a8a; margin: 0; font-size: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 25px; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 12px 10px; text-align: center; font-size: 13px; vertical-align: middle; }}
        th {{ background: #1e3a8a; color: white; }}
        tr:nth-child(even) {{ background: #f8fafc; }}
        .qr-img {{ width: 50px; height: 50px; object-fit: contain; border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px; background: white; }}
        .btn {{ background: #2563eb; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block; }}
        .btn-save {{ background: #16a34a; border: none; cursor: pointer; padding: 6px 14px; color: white; border-radius: 6px; font-weight: bold; font-size: 13px; }}
        textarea {{ width: 100%; height: 60px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-family: Tahoma; font-size: 13px; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><h2>سجلات الفحوصات ليوم: {day} ({modality})</h2></div>
        <table>
            <thead>
                <tr>
                    <th>رقم السجل</th>
                    <th>اسم المريض</th>
                    <th>تاريخ الولادة</th>
                    <th>صور/لقطات الفحص</th>
                    <th>رمز الـ QR</th>
                    <th>التقرير الطبي التشخيصي</th>
                    <th>الإجراءات</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <a href="/doctor/archive/{modality}/{month}" class="btn-back">← العودة للأشهر</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; padding:30px; color:red;'><h3>خطأ:</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    records = db.query(PatientRecord).all()
    template = env.get_template("secretary.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"], success=request.query_params.get("success")))
@app.post("/technician/delete/{record_id}")
def technician_delete_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user or user["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # البحث المباشر عن السجل برقم الـ ID وحذفه من الجدول المركزي المشترك
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record:
        # حذف الصور المادية من السيرفر
        if record.image_path:
            for p in record.image_path.split(","):
                img_file = p.strip().lstrip("/")
                if os.path.exists(img_file):
                    os.remove(img_file)
        
        # حذف ملف الـ QR المادي
        if record.qr_code and record.qr_code != "temp.png":
            qr_file = f"static/qrs/{record.qr_code}"
            if os.path.exists(qr_file):
                os.remove(qr_file)
        
        # الحذف النهائي من قاعدة البيانات (يزول من السكرتارية والأدمن والأرشيف فوراً)
        db.delete(record)
        db.commit()
        
    return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/secretary/qr-preview/{record_id}", response_class=HTMLResponse)
def secretary_qr_preview(record_id: int, request: Request, db: Session = Depends(get_db)):
    # 1. التحقق الأمني من صلاحية السكرتارية
    user = request.session.get("user")
    if not user or user.get("role") != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # 2. جلب السجل من قاعدة البيانات
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود في النظام")
    
    # 3. بناء واجهة HTML المتكاملة (معاينة + تعديل التقرير وحفظه في نفس الصفحة)
    html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>معاينة وتعديل التقرير - {record.patient_name}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; padding: 30px; color: #1e293b; }}
        .card {{ max-width: 750px; background: white; margin: auto; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; }}
        .qr-img {{ width: 200px; height: 200px; margin: 15px auto; border: 2px solid #e2e8f0; padding: 10px; border-radius: 8px; }}
        .report-box {{ text-align: right; background: #f1f5f9; padding: 15px; border-radius: 6px; margin-top: 20px; }}
        textarea {{ width: 100%; height: 120px; padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-family: Tahoma, sans-serif; font-size: 14px; resize: vertical; box-sizing: border-box; }}
        .btn {{ background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; margin-top: 20px; font-size: 14px; }}
        .btn-save {{ background: #16a34a; margin-left: 10px; }}
        .btn-back {{ background: #64748b; margin-left: 10px; }}
        @media print {{
            .btn, .btn-back, textarea, .print-hide {{ display: none !important; }}
            .print-show {{ display: block !important; }}
            body {{ background: white; padding: 0; }}
            .card {{ box-shadow: none; border: none; }}
            textarea {{ border: none; background: transparent; resize: none; }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>معاينة بيانات المريض وتقرير الفحص</h2>
        <hr style="border:0; border-top:1px solid #e2e8f0; margin: 15px 0;">
        
        <div style="text-align: right; margin-bottom: 15px; font-size: 15px;">
            <p><strong>اسم المريض:</strong> {record.patient_name}</p>
            <p><strong>تاريخ الميلاد:</strong> {record.birth_date or '-'}</p>
            <p><strong>نوع الفحص (Modality):</strong> {record.modality or '-'}</p>
        </div>
        
        <div>
            <img src="/static/qrs/{record.qr_code}" class="qr-img" alt="QR Code">
            <p class="print-hide" style="font-size: 13px; color: #64748b;">رمز الاستجابة السريعة الخاص بالفحص</p>
        </div>

        <!-- نموذج تعديل وحفظ التقرير مباشرة -->
        <form action="/save-report" method="POST">
            <input type="hidden" name="record_id" value="{record.id}">
            <input type="hidden" name="next" value="/secretary/qr-preview/{record.id}">
            <div class="report-box">
                <h4 style="margin-top: 0; color: #1e3a8a; text-align: right;">التقرير التشخيصي والملاحظات:</h4>
                <textarea name="report">{record.report or ""}</textarea>
            </div>

            <div style="margin-top: 25px;">
                <a href="/secretary" class="btn btn-back">← العودة</a>
                <button type="submit" class="btn btn-save">💾 حفظ التقرير</button>
                <button type="button" onclick="window.print()" class="btn">🖨️ طباعة الكل</button>
            </div>
        </form>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
@app.post("/save-report")
@app.post("/save-report-inline", include_in_schema=False, deprecated=True)
def save_report(
    request: Request,
    record_id: int = Form(...),
    report: str = Form(""),
    next_url: str = Form("", alias="next"),
    db: Session = Depends(get_db),
):
    """The single report writer, reached from every dashboard and the QR preview.

    ``/save-report-inline`` is the pre-Ticket-03 name and shares this exact function
    object; it exists so a browser tab holding the old preview page still works.
    """
    user = request.session.get("user")
    role = user.get("role") if user else None
    if role not in {"admin", "secretary"}:
        # Check the gate before the query: an outsider must not even learn which ids exist.
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="السجل غير موجود")

    record.report = report
    # Mint before the commit: a QR failure must not leave the record half-saved.
    record.qr_code = write_qr(record.id, str(request.base_url))
    db.commit()

    logger.info("report: saved record id=%s role=%s", record_id, role)

    fallback = "/doctor" if role == "admin" else "/secretary"
    return RedirectResponse(
        url=safe_next_path(next_url, fallback),
        status_code=status.HTTP_303_SEE_OTHER,
    )

@app.get("/download-report/{record_id}")
def download_report(record_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record is None:raise HTTPException(status_code=404, detail="السجل غير موجود")
    
    file_content = f"""========================================
مركز التشخيص الطبي والتصوير الشعاعي
========================================
رقم السجل: #{record.id}
اسم المريض: {record.patient_name}
تاريخ الولادة: {record.birth_date}
نوع الفحص (Modality): {record.modality}
تاريخ الإنشاء: {record.created_at}
----------------------------------------
التقرير الطبي التشخيصي:
{record.report}
========================================
"""
    return Response(
        content=file_content,
        media_type="application/msword",
        headers={"Content-Disposition": f"attachment; filename=Patient_Report_{record.id}.doc"}
    )

@app.get("/technician", response_class=HTMLResponse)
def technician_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    user_modality = request.session["user"]["modality"]
    records = db.query(PatientRecord).filter(PatientRecord.modality == user_modality).all()
    
    template = env.get_template("technician.html")
    return HTMLResponse(content=template.render(request=request, user=request.session["user"], records=records, success=request.query_params.get("success")))

import datetime
import io
import os
import traceback
from typing import List
import numpy as np
import pydicom
from PIL import Image
import qrcode
from fastapi import Request, Form, UploadFile, File, Depends, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

@app.post("/technician/upload")
async def technician_upload(
    request: Request,
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    modality: str = Form(...),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    try:
        os.makedirs("static/uploads", exist_ok=True)
        os.makedirs("static/qrs", exist_ok=True)

        saved_paths = []
        for file in files:
            if file.filename:
                safe_filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename.replace(' ', '_')}"
                contents = await file.read()
                
                # التحقق مما إذا كان الملف بصيغة DICOM
                if file.filename.lower().endswith('.dcm') or 'dicom' in file.content_type.lower():
                    try:
                        ds = pydicom.dcmread(io.BytesIO(contents))
                        pixel_array = ds.pixel_array
                        
                        pixel_array = pixel_array.astype(float)
                        if pixel_array.max() > 0:
                            pixel_array = (pixel_array / pixel_array.max()) * 255.0
                        pixel_array = np.uint8(pixel_array)
                        
                        img = Image.fromarray(pixel_array)
                        png_filename = f"{safe_filename}.png"
                        png_path = f"static/uploads/{png_filename}"
                        img.save(png_path)
                        saved_paths.append(f"/{png_path}")
                    except Exception:
                        fallback_path = f"static/uploads/{safe_filename}"
                        with open(fallback_path, "wb") as f:
                            f.write(contents)
                        saved_paths.append(f"/{fallback_path}")
                else:
                    final_file_path = f"static/uploads/{safe_filename}"
                    with open(final_file_path, "wb") as f:
                        f.write(contents)
                    saved_paths.append(f"/{final_file_path}")

        images_string = ",".join(saved_paths) if saved_paths else ""

        new_record = PatientRecord(
            patient_name=patient_name,
            birth_date=birth_date,
            modality=modality,
            image_path=images_string,
            qr_code="temp.png"
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        new_record.qr_code = write_qr(new_record.id, str(request.base_url))
        db.commit()

        return RedirectResponse(url="/technician?success=1", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        return HTMLResponse(content=f"<h3 style='color:red;'>خطأ أثناء الرفع:</h3><pre>{err_details}</pre>", status_code=500)



def _patient_not_found() -> HTMLResponse:
    return HTMLResponse(
        content="<div style='font-family:Tahoma; text-align:center; margin-top:50px;'><h3>السجل غير موجود</h3></div>",
        status_code=404,
    )


def legacy_record_id(identifier: str) -> int | None:
    """The record id a pre-token URL names, or ``None`` if it names no usable id.

    ``str.isdigit()`` is True for characters ``int()`` rejects (``"²"``) and for
    strings past CPython's 4300-digit conversion limit, so the conversion itself
    decides. Callers must treat an exception here as "not a legacy URL", never as 500.
    """
    if not identifier.isdigit():
        return None
    try:
        return int(identifier)
    except ValueError:
        return None


@app.get("/patient/{identifier}", response_class=HTMLResponse)
def print_record(identifier: str, request: Request, db: Session = Depends(get_db)):
    """Public patient page. The signed token in the URL *is* the credential."""
    legacy_id = legacy_record_id(identifier)
    if legacy_id is not None:
        if not legacy_patient_urls_enabled():
            return _patient_not_found()
        # Evidence for retiring the flag: count how many printed labels still arrive this way.
        logger.info("patient: legacy numeric URL used for record id=%s", legacy_id)
        # Relative Location: an absolute one inherits the attacker-controllable Host header.
        return RedirectResponse(
            url=f"/patient/{mint_patient_token(legacy_id)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        record_id = read_patient_token(identifier)
    except (BadData, ValueError, TypeError):
        # A 500 here would confirm the token parsed; refuse uniformly instead.
        return _patient_not_found()

    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record is None:
        return _patient_not_found()
# جلب مسارات الصور من حقل image_path مباشرة لضمان التطابق التام مع لوحة الأدمن
    dicom_urls = []
    if record.image_path:
      dicom_urls = [p.strip() for p in record.image_path.split(",") if p.strip()]

    template = env.get_template("patient.html")
    return HTMLResponse(content=template.render(
      request=request, 
      record=record, 
      dicom_urls=dicom_urls
))
