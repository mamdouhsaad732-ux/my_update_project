from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine, Column, Integer, String, true
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import shutil
import datetime
import qrcode
from PIL import Image
from typing import List
import pydicom
import numpy as np
import io
SQLALCHEMY_DATABASE_URL = "sqlite:///./medical_pacs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PatientRecord(Base):
    __tablename__ = "patient_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, index=True)
    birth_date = Column(String)
    modality = Column(String)
    image_path = Column(String)
    report = Column(String, default="بانتظار كتابة التقرير الطبي من السكرتارية...")
    qr_code = Column(String)
    created_at = Column(String, default=str(datetime.datetime.now()))
    dicom_file=Column(String,nullable=true)

Base.metadata.create_all(bind=engine)

app = FastAPI()


app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key="medical-pacs-super-secret-production-key-2026")
app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


env = Environment(loader=FileSystemLoader("templates"))

USERS = {
    "ct_user": {"password": "123", "role": "technician", "modality": "CT", "name": "فني الطبقي المحوري"},
    "mri_user": {"password": "123", "role": "technician", "modality": "MRI", "name": "فني الرنين المغناطيسي"},
    "xray_user": {"password": "123", "role": "technician", "modality": "X-Ray", "name": "فني الأشعة السينية"},
    "echo_user": {"password": "123", "role": "technician", "modality": "Echo", "name": "فني الأمواج فوق الصوتية"},
    "secretary": {"password": "123", "role": "secretary", "name": "موظف الاستقبال والسكرتارية"},
    "samer": {"password": "123", "role": "admin", "name": "الدكتور سامر (الأدمن المطلق)"}
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def cleanup_old_records(db: Session):
    try:
        threshold_date = datetime.datetime.now() - datetime.timedelta(days=30)
        records = db.query(PatientRecord).all()
        for record in records:
            if record.created_at:
                try:
                    record_date = datetime.datetime.strptime(record.created_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
                    if record_date < threshold_date:
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
                except Exception:
                    pass
        db.commit()
    except Exception:
        pass

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
    if username in USERS and USERS[username]["password"] == password:
        request.session["user"] = USERS[username]
        role = USERS[username]["role"]
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
    # 1. جلب بيانات السجل 
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first() 
    if not record: 
        raise HTTPException(status_code=404, detail="السجل غير موجود")
# 2. تحديد مسار المجلد الذي يحتوي على صور المريض
    patient_dir = os.path.join("static", "dicoms", str(record_id))
    os.makedirs(patient_dir, exist_ok=True)
    for file in File:
     if file.filename:
      file_path = os.path.join(patient_dir, file.filename)
    with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
    dicom_urls = []
# إذا كان هناك مجلد برقم السجل، نجمع كافة ملفات DICOM من داخله
    if os.path.exists(patient_dir):
     files = sorted(os.listdir(patient_dir))
     dicom_urls = [f"/static/dicoms/{record_id}/{f}" for f in files if not f.startswith('.')]

# إذا لم يكن المجلد موجوداً، نتحقق مما إذا كان هناك ملف مائل مباشر ينتهي بـ .dcm
    if not dicom_urls:
        
     direct_file = os.path.join("static", "dicoms", f"{record_id}.dcm")
    if os.path.exists(direct_file):
        dicom_urls = [f"/static/dicoms/{record_id}.dcm"]
# 3. تمرير قائمة الروابط الكاملة إلى الواجهة
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

# --- عرض جميع الصور في نفس الصفحة للأدمن (بدون روابط خارجية) ---
import os
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

# ملاحظة: قم باستيراد get_db و PatientRecord من مشروعك الفعلي
# from .database import get_db
# from .models import PatientRecord

app = FastAPI()

@app.get("/doctor/view-images/{record_id}", response_class=HTMLResponse)
def view_patient_images(record_id: int, request: Request, db: Session = Depends(get_db)):
    # 1. التحقق من صلاحية الأدمن أولاً
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # 2. التحقق من وجود السجل في قاعدة البيانات
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="السجل غير موجود")

    # 3. جلب مسار ملفات المريض
    patient_dir = os.path.join("static", "dicoms", str(record_id))
    dicom_urls = []
    if os.path.exists(patient_dir):
        files = sorted(os.listdir(patient_dir))
        # استخراج روابط الصور وتجنب الملفات المخفية
        dicom_urls = [f"/static/dicoms/{record_id}/{f}" for f in files if not f.startswith('.')]

    # 4. بناء قالب الـ HTML مع الـ Lightbox
    images_html = ""
    if dicom_urls:
        for url in dicom_urls:
            images_html += f'''
            <div style="background: #1e293b; border-radius: 12px; padding: 10px; cursor: pointer; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                <img src="{url}" alt="Scan" style="width: 200px; height: 150px; object-fit: cover; border-radius: 8px;" onclick="openLightbox('{url}')">
            </div>
            '''
    else:
        images_html = '<p style="color: #94a3b8; font-size: 18px; width: 100%; text-align: center;">لا توجد صور مسجلة لهذا المريض حتى الآن.</p>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>معاينة صور الفحص للأدمن</title>
        <style>
            body {{ font-family: Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; text-align: center; }}
            .btn-back {{ background: #e74c3c; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; display: inline-block; margin-bottom: 20px; font-weight: bold; }}
            .gallery {{ display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; margin-top: 20px; }}
            /* Lightbox Modal */
            #lightbox {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); justify-content: center; align-items: center; z-index: 1000; }}
            #lightbox img {{ max-width: 90%; max-height: 90%; border-radius: 8px; box-shadow: 0 0 20px rgba(255,255,255,0.2); }}
            .close-btn {{ position: absolute; top: 20px; right: 30px; font-size: 40px; color: white; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/doctor" class="btn-back">← عودة لوحة التحكم</a>
            <h2 style="color: #38bdf8;">معاينة صور الفحص للأدمن</h2>
            <div class="gallery">
                {images_html}
            </div>
        </div>

        <!-- Lightbox Overlay -->
        <div id="lightbox" onclick="closeLightbox()">
            <span class="close-btn">×</span>
            <img id="lightbox-img" src="">
        </div>

        <script>
            function openLightbox(url) {{
                document.getElementById('lightbox-img').src = url;
                document.getElementById('lightbox').style.display = 'flex';
            }}
            function closeLightbox() {{
                document.getElementById('lightbox').style.display = 'none';
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
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
                            <textarea name="report_text">{record.report}</textarea>
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
        <form action="/save-report-inline" method="POST">
            <input type="hidden" name="record_id" value="{record.id}">
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
def generate_patient_qr(record_id: int): 
    base_url = "http://127.0.0.1:8000" 
    scan_url = f"{base_url}/view-scan/{record_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(scan_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    qr_filename = f"qr_{record_id}.png"
    save_path = os.path.join("static", "qrs", qr_filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)

    return qr_filename

@app.post("/save-report-inline") 
def save_report_inline( 
    record_id: int = Form(...), 
    report: str = Form(...), 
    db: Session = Depends(get_db) ): 
 # 1. البحث عن السجل 
  record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first() 
  if not record: 
      raise HTTPException(status_code=404, detail="السجل غير موجود")
# 2. تحديث التقرير وحفظه
  record.report = report
  db.commit()

# 3. توليد وتخزين رمز الـ QR الخاص بهذا السجل تلقائياً
  record.qr_code = generate_patient_qr(record.id)
  db.commit()

# 4. العودة إلى نفس صفحة المعاينة للمريض
  return RedirectResponse(url=f"/secretary/qr-preview/{record_id}", status_code=status.HTTP_303_SEE_OTHER)

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

        base_url = str(request.base_url).rstrip("/")
        qr_data = f"{base_url}/patient/{new_record.id}"
        
        qr_img = qrcode.make(qr_data)
        qr_filename = f"qr_{new_record.id}.png"
        qr_path = f"static/qrs/{qr_filename}"
        qr_img.save(qr_path)

        new_record.qr_code = qr_filename
        db.commit()

        return RedirectResponse(url="/technician?success=1", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        return HTMLResponse(content=f"<h3 style='color:red;'>خطأ أثناء الرفع:</h3><pre>{err_details}</pre>", status_code=500)

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
@app.get("/patient/{record_id}", response_class=HTMLResponse)
def print_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record is None:
     return HTMLResponse(content="<div style='font-family:Tahoma; text-align:center; margin-top:50px;'><h3>السجل غير موجود</h3></div>", status_code=404)
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
def generate_patient_qr(record_id: int):
    # استبدل هذا الرابط برابط موقعك الفعلي على Render لضمان صحته دائماً 
   base_url = "https://al-pacs-system-1.onrender.com"
   scan_url = f"{base_url}/patient/{record_id}"
   qr = qrcode.QRCode(version=1, box_size=10, border=5)
   qr.add_data(scan_url)
   qr.make(fit=True)

   img = qr.make_image(fill_color="black", back_color="white")

   qr_filename = f"qr_{record_id}.png"
   save_path = os.path.join("static", "qrs", qr_filename)
   os.makedirs(os.path.dirname(save_path), exist_ok=True)
   img.save(save_path)

   return qr_filename
