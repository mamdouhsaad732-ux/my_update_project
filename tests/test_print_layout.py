"""A4 print-readiness of every report/print surface.

These tests lock the physical layout contract: a real A4 page box, legible print
typography, a QR that keeps a clean fixed size, and no surface that silently drops
its content (the secretary preview used to print a blank report).

They intentionally assert on the CSS *contract*, not pixel rendering: a browser test
harness is not part of this suite, but every rule below is the one the print dialog
relies on.
"""

import main
from conftest import insert_record

A4 = "size: A4 portrait"


def _css(html):
    """Return only the <style> blocks so markup text can't satisfy a CSS assertion."""
    start = html.find("<style>")
    end = html.find("</style>")
    assert start != -1 and end > start, "page has no inline stylesheet"
    return html[start:end]


# --- admin report page (/doctor/report/{id}) --------------------------------------


def test_admin_report_page_is_an_a4_page(admin_client):
    record_id = insert_record(report="تقرير للطباعة على A4")

    css = _css(admin_client.get(f"/doctor/report/{record_id}").text)

    assert "@page" in css
    assert A4 in css
    assert "margin:" in css.split("@page", 1)[1].split("}", 1)[0], "A4 page needs margins"
    # Exact colours: the brand gradient/panel tints must survive the print engine.
    assert "print-color-adjust: exact" in css
    assert "-webkit-print-color-adjust: exact" in css


def test_admin_report_print_typography_is_legible(admin_client):
    record_id = insert_record(report="تقرير طبي")

    css = _css(admin_client.get(f"/doctor/report/{record_id}").text)
    print_block = css.split("@media print", 1)[1]

    # 11.5pt ≈ 15.3px: readable for a clinical report, not a shrunken table.
    assert "font-size: 11.5pt" in print_block
    assert "line-height: 1.8" in print_block
    # Muted grey was too faint on paper; the print palette must be darker.
    assert "#111827" in print_block


def test_admin_report_qr_prints_at_a_clean_fixed_size(admin_client):
    record_id = insert_record(qr_code="print_qr.png")

    css = _css(admin_client.get(f"/doctor/report/{record_id}").text)
    print_block = css.split("@media print", 1)[1]

    assert "42mm" in print_block, "QR needs a physical print size"
    assert "object-fit: contain" in css, "QR must not be stretched"
    # The download button is an action, not report content.
    assert ".qr-body .btn" in print_block and "display: none" in print_block
    assert "break-inside: avoid" in print_block


# --- secretary preview / print page (/secretary/qr-preview/{id}) ------------------


def test_secretary_preview_is_an_a4_page(secretary_client):
    record_id = insert_record(report="تقرير المعاينة")

    css = _css(secretary_client.get(f"/secretary/qr-preview/{record_id}").text)

    assert "@page" in css
    assert A4 in css
    assert "print-color-adjust: exact" in css


def test_secretary_preview_prints_the_report_instead_of_a_hidden_textarea(secretary_client):
    """Regression: the textarea was hidden for print and no .print-show element existed."""
    report = "تقرير يظهر في الطباعة\nالسطر الثاني"
    record_id = insert_record(report=report)

    html = secretary_client.get(f"/secretary/qr-preview/{record_id}").text
    css = _css(html)
    print_block = css.split("@media print", 1)[1]

    # A real, printable element carries the text (escaped newlines preserved by CSS).
    assert 'class="report-text print-show"' in html
    assert report.splitlines()[0] in html
    assert "textarea" in print_block and "display: none" in print_block
    assert ".print-show { display: block !important; }" in print_block
    assert "white-space: pre-wrap" in print_block
    # Printing an unsaved edit should print the edit, not the stale saved version.
    assert "syncPrintReport" in html


def test_secretary_preview_never_prints_a_broken_qr(secretary_client):
    record_id = insert_record(qr_code="temp.png")

    html = secretary_client.get(f"/secretary/qr-preview/{record_id}").text

    assert "/static/qrs/temp.png" not in html
    assert "qr-empty" in html
    assert "لا يوجد رمز QR" in html


# --- public patient portal (another print surface) -------------------------------


def test_patient_page_is_an_a4_page_without_clipped_scans(admin_client):
    record_id = insert_record()

    html = admin_client.get(f"/patient/{main.mint_patient_token(record_id)}").text
    css = _css(html)
    print_block = css.split("@media print", 1)[1]

    assert "@page" in css
    assert A4 in css
    # The on-screen 560px scroll box used to clip every scan beyond the first screen.
    assert ".scans-scroll" in print_block
    assert "max-height: none" in print_block
    assert "overflow: visible" in print_block
    # Screen-only controls must not appear on paper.
    assert ".zoom-btn" in print_block
    assert "break-inside: avoid" in print_block


# --- Word / print export (/download-report/{id}) ---------------------------------


def test_word_export_declares_an_a4_page_box(admin_client, clean_static):
    import os

    qr_name = "export_print_qr.png"
    with open(os.path.join(main.QRS_DIR, qr_name), "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
    record_id = insert_record(report="تقرير التصدير للطباعة", qr_code=qr_name)

    response = admin_client.get(f"/download-report/{record_id}")
    body = response.text

    assert response.status_code == 200
    assert "size: 21cm 29.7cm" in body, "Word export needs a real A4 page box"
    assert "margin: 14mm" in body
    assert "font-size: 11.5pt" in body
    assert "direction: rtl" in body
    assert "تقرير التصدير للطباعة" in body
    # QR is embedded at 42mm (159px @96dpi) when the file exists.
    assert 'width="159" height="159"' in body


def test_word_export_escapes_stored_html(admin_client):
    record_id = insert_record(name="<script>alert(1)</script>", report="<b>نص</b>")

    body = admin_client.get(f"/download-report/{record_id}").text

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "<b>نص</b>" not in body


def test_export_links_are_not_gated_on_confirm(admin_client, secretary_client):
    """A suppressed dialog used to make the Word export silently do nothing."""
    insert_record()
    for client, path in ((admin_client, "/doctor"), (secretary_client, "/secretary")):
        html = client.get(path).text
        assert 'href="/download-report/' in html, path
        assert "download-report" in html
        index = html.find('href="/download-report/')
        anchor_end = html.find("</a>", index)
        anchor = html[index:anchor_end]
        assert "confirm(" not in anchor, path
        assert "onclick" not in anchor, path

