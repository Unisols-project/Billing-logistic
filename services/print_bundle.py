# services/print_bundle.py
# Direct A4 print bundle:
#   Page 1 = Invoice, ONE copy
#   Page 2 = Challan, ORIGINAL
#   Page 3 = Challan, DUPLICATE
#
# Windows default printer is used directly. No browser print dialog.

import os
import shutil
import tempfile
import subprocess
from pathlib import Path

from config import COMPANY
from database import conn
from services.pdf_service import make_pdf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors

try:
    from pypdf import PdfReader, PdfWriter, Transformation
except Exception:
    PdfReader = PdfWriter = Transformation = None


def _safe_float(v, default=0.0):
    try:
        return float(v or 0)
    except Exception:
        return default


def _row_dict(row):
    return dict(row) if row is not None else {}


def _find_challan_for_invoice(invoice_id, customer_id):
    """Prefer explicit invoice_challans relation; otherwise latest challan for customer."""
    with conn() as c:
        # Explicit link, if this table exists.
        try:
            r = c.execute(
                "SELECT challan_id FROM invoice_challans "
                "WHERE invoice_id=? ORDER BY rowid DESC LIMIT 1",
                (invoice_id,),
            ).fetchone()
            if r and r["challan_id"]:
                row = c.execute(
                    "SELECT * FROM challans WHERE id=?", (r["challan_id"],)
                ).fetchone()
                if row:
                    return _row_dict(row)
        except Exception:
            pass

        # Safe fallback: latest challan belonging to same customer.
        row = c.execute(
            "SELECT * FROM challans WHERE customer_id=? ORDER BY id DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
        return _row_dict(row)


def _load_challan_data(challan_row):
    if not challan_row:
        return {}, []

    cid = challan_row.get("customer_id")
    with conn() as c:
        if cid:
            cust_row = c.execute(
                "SELECT * FROM customers WHERE id=?", (cid,)
            ).fetchone()
            customer = _row_dict(cust_row)
        else:
            customer = {}

        items_rows = c.execute(
            "SELECT * FROM challan_items WHERE challan_id=? ORDER BY id",
            (challan_row.get("id"),),
        ).fetchall()

    items = [_row_dict(r) for r in items_rows][:25]
    customer["godown"] = challan_row.get("godown") or customer.get("godown") or ""

    header = {
        "number": challan_row.get("number", ""),
        "date": challan_row.get("date", ""),
        "day": challan_row.get("day", ""),
        "time": challan_row.get("time", ""),
        "godown": challan_row.get("godown", ""),
        "subtotal": challan_row.get("subtotal", 0),
        "discount": challan_row.get("discount", 0),
        "freight": challan_row.get("freight", 0),
        "other_charges": challan_row.get("other_charges", 0),
        "total": challan_row.get("total", 0),
        "notes": challan_row.get("notes", ""),
        "gst_mode": "NO_GST",
    }
    return header, items


def _money(v):
    return f"{_safe_float(v):,.2f}"


def _wrap(c, value, x, y, width, size=6.2, max_lines=2, align="left"):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    value = str(value or "").replace("\n", " ").strip()
    words = value.split()
    lines = []
    cur = ""
    for word in words:
        test = word if not cur else cur + " " + word
        if stringWidth(test, "Helvetica", size) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)

    for i, line in enumerate(lines[:max_lines]):
        yy = y - i * (size + 1)
        if align == "center":
            c.drawCentredString(x, yy, line)
        elif align == "right":
            c.drawRightString(x, yy, line)
        else:
            c.drawString(x, yy, line)


def make_challan_25_pdf(header, customer, items, path, copy_label):
    """One A4 challan page with up to 25 product rows."""
    W, H = A4
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(f"Delivery Challan {header.get('number','')} - {copy_label}")
    c.setAuthor(COMPANY.get("name", ""))

    L = 6 * mm
    R = W - 6 * mm
    top = H - 7 * mm

    def line(x1, y1, x2, y2, width=0.45):
        c.setStrokeColor(colors.black)
        c.setLineWidth(width)
        c.line(x1, y1, x2, y2)

    def rect(x, y, w, h, width=0.65):
        c.setStrokeColor(colors.black)
        c.setLineWidth(width)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def txt(x, y, s, size=7, bold=False, align="left"):
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        s = str(s or "")
        if align == "center":
            c.drawCentredString(x, y, s)
        elif align == "right":
            c.drawRightString(x, y, s)
        else:
            c.drawString(x, y, s)

    # Header
    txt(R, top, copy_label, 7.0, True, "right")
    txt(L, top, "DELIVERY CHALLAN", 10, True)
    txt((L+R)/2, top-5.5*mm, COMPANY.get("name",""), 12, True, "center")
    txt((L+R)/2, top-10*mm, COMPANY.get("address",""), 6.2, False, "center")
    line(L, top-12*mm, R, top-12*mm, 0.6)

    # Details
    info_top = top - 13 * mm
    info_bottom = info_top - 17 * mm
    rect(L, info_bottom, R-L, info_top-info_bottom, 0.6)
    mid = L + 128*mm
    line(mid, info_bottom, mid, info_top, 0.45)

    txt(L+2*mm, info_top-4.5*mm, "Customer :", 6.7, True)
    _wrap(c, customer.get("name",""), L+23*mm, info_top-4.5*mm,
          mid-L-25*mm, 6.4, 2)
    txt(L+2*mm, info_top-11*mm, "Godown :", 6.7, True)
    _wrap(c, header.get("godown","") or customer.get("godown",""), L+23*mm,
          info_top-11*mm, mid-L-25*mm, 6.4, 1)

    txt(mid+3*mm, info_top-5*mm, "Challan No. :", 6.7, True)
    txt(mid+31*mm, info_top-5*mm, header.get("number",""), 6.7, True)
    txt(mid+3*mm, info_top-11*mm, "Date :", 6.7, True)
    txt(mid+18*mm, info_top-11*mm, header.get("date",""), 6.5)

    # 25-row table
    table_top = info_bottom
    row_h = 5.35 * mm
    header_h = 8 * mm
    table_bottom = table_top - header_h - 25*row_h

    xs = [
        L,
        L+9*mm,      # Sr
        L+40*mm,     # Godown
        L+94*mm,     # Item
        L+118*mm,    # Qty
        L+141*mm,    # Rate
        L+165*mm,    # Loading
        R,
    ]
    rect(L, table_bottom, R-L, table_top-table_bottom, 0.65)
    for x in xs[1:-1]:
        line(x, table_bottom, x, table_top, 0.35)
    line(L, table_top-header_h, R, table_top-header_h, 0.5)

    headings = ["SR.", "GODOWN", "ITEM", "QTY", "RATE", "LOADING", "TOTAL"]
    for i, h in enumerate(headings):
        txt((xs[i]+xs[i+1])/2, table_top-5.1*mm, h, 6.0, True, "center")

    # Exactly 25 rows, blank rows remain blank.
    for i in range(25):
        y = table_top-header_h-(i+0.5)*row_h
        if i < len(items):
            it = items[i]
            txt((xs[0]+xs[1])/2, y-1.8, str(i+1), 5.8, False, "center")
            _wrap(c, header.get("godown","") or customer.get("godown",""),
                  (xs[1]+xs[2])/2, y+0.8, xs[2]-xs[1]-2*mm, 5.2, 1, "center")
            _wrap(c, it.get("item_name",""), xs[2]+1.5*mm, y+0.8,
                  xs[3]-xs[2]-3*mm, 5.4, 1)
            txt((xs[3]+xs[4])/2, y-1.8, _money(it.get("qty",0)).rstrip("0").rstrip("."),
                5.7, False, "center")
            txt((xs[4]+xs[5])/2, y-1.8, _money(it.get("price",0)),
                5.6, False, "center")
            txt((xs[5]+xs[6])/2, y-1.8, _money(it.get("loading",0)),
                5.6, False, "center")
            amount = it.get("amount")
            if amount is None:
                amount = _safe_float(it.get("qty")) * _safe_float(it.get("price")) + _safe_float(it.get("loading"))
            txt(xs[7]-1.5*mm, y-1.8, _money(amount), 5.8, False, "right")

    # Compact footer
    footer_top = table_bottom
    footer_h = 28*mm
    footer_bottom = max(7*mm, footer_top-footer_h)
    rect(L, footer_bottom, R-L, footer_top-footer_bottom, 0.65)
    split = L + 125*mm
    line(split, footer_bottom, split, footer_top, 0.45)

    subtotal = header.get("subtotal")
    if subtotal is None:
        subtotal = sum(
            _safe_float(it.get("amount"))
            if it.get("amount") is not None
            else _safe_float(it.get("qty"))*_safe_float(it.get("price")) + _safe_float(it.get("loading"))
            for it in items
        )
    txt(L+2*mm, footer_top-5*mm, "TOTAL ITEMS :", 6.4, True)
    txt(L+31*mm, footer_top-5*mm, str(len(items)), 6.4, True)
    txt(L+2*mm, footer_top-10*mm, "Amount :", 6.4, True)
    txt(L+31*mm, footer_top-10*mm, _money(subtotal), 6.4, True)

    notes = header.get("notes","")
    if notes:
        txt(L+2*mm, footer_top-16*mm, "Notes :", 6.2, True)
        _wrap(c, notes, L+20*mm, footer_top-16*mm, split-L-22*mm, 5.7, 2)

    txt(split+2*mm, footer_top-5*mm, "TOTAL", 7.0, True)
    txt(R-2*mm, footer_top-5*mm, _money(header.get("total", subtotal)), 7.0, True, "right")
    txt(split+2*mm, footer_top-12*mm, "Receiver Signature", 6.3, True)
    txt(split+2*mm, footer_bottom+5*mm,
        f"For {COMPANY.get('name','')}", 6.3, True)

    c.showPage()
    c.save()
    return path


def _single_invoice_page(invoice_pdf, out_pdf):
    """Take the ORIGINAL half of the existing invoice PDF and enlarge it to one full A4 page."""
    if PdfReader is None:
        raise RuntimeError("pypdf is required for direct invoice printing.")

    reader = PdfReader(invoice_pdf)
    if not reader.pages:
        raise RuntimeError("Invoice PDF is empty.")

    src = reader.pages[0]
    media = src.mediabox
    W = float(media.width)
    H = float(media.height)

    # Existing invoice layout draws ORIGINAL in the top half and DUPLICATE in bottom half.
    src.cropbox.lower_left = (0, H/2)
    src.cropbox.upper_right = (W, H)

    # Move the cropped top-half invoice down and enlarge vertically to A4.
    src.add_transformation(Transformation().scale(sx=1, sy=2).translate(tx=0, ty=-H))
    # The source crop box was only the top half; after enlargement the output
    # must again expose the complete A4 page.
    src.cropbox.lower_left = (0, 0)
    src.cropbox.upper_right = (W, H)

    writer = PdfWriter()
    writer.add_page(src)
    with open(out_pdf, "wb") as f:
        writer.write(f)
    return out_pdf


def _merge_pdfs(paths, output):
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("pypdf is required for combined direct printing.")
    writer = PdfWriter()
    for path in paths:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
    with open(output, "wb") as f:
        writer.write(f)
    return output


def direct_print_pdf(pdf_path):
    if os.name != "nt":
        raise RuntimeError("Direct default-printer printing is implemented for Windows.")
    pdf_path = os.path.abspath(pdf_path)

    # Windows shell print verb -> default PDF application's printer.
    try:
        os.startfile(pdf_path, "print")
        return
    except Exception:
        pass

    # Fallback using PowerShell's Print verb.
    try:
        subprocess.Popen(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-Command",
                "Start-Process -LiteralPath $args[0] -Verb Print",
                pdf_path,
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    except Exception as e:
        raise RuntimeError(f"Windows direct print could not be started: {e}")


def print_invoice_and_challan_direct(invoice):
    """Create 3 A4 pages and send them as ONE direct print job."""
    invoice_id = invoice.get("id")
    customer = dict(invoice.get("customer") or {})
    customer_id = customer.get("id")

    if not invoice_id:
        raise RuntimeError("Please save the invoice before printing.")

    challan_row = _find_challan_for_invoice(invoice_id, customer_id)
    if not challan_row:
        raise RuntimeError(
            "No challan found for this invoice/customer. Save the challan first."
        )

    challan_header, challan_items = _load_challan_data(challan_row)
    if not challan_items:
        raise RuntimeError("The challan has no products.")

    # Hard limit requested by you: 25 products per challan.
    challan_items = challan_items[:25]

    temp_dir = Path(tempfile.mkdtemp(prefix="invoice_challan_print_"))
    try:
        # 1) Generate existing invoice PDF, then keep ONLY ORIGINAL as one full A4 page.
        raw_invoice = temp_dir / "invoice_raw.pdf"
        make_pdf(
            "invoice",
            invoice["header"],
            customer,
            invoice.get("items") or [],
            path=str(raw_invoice),
            copy_label="ORIGINAL",
        )
        invoice_one = temp_dir / "invoice_one_a4.pdf"
        _single_invoice_page(str(raw_invoice), str(invoice_one))

        # 2) Two independent A4 challan pages: ORIGINAL + DUPLICATE.
        challan_original = temp_dir / "challan_original.pdf"
        challan_duplicate = temp_dir / "challan_duplicate.pdf"
        make_challan_25_pdf(
            challan_header, customer, challan_items,
            str(challan_original), "ORIGINAL"
        )
        make_challan_25_pdf(
            challan_header, customer, challan_items,
            str(challan_duplicate), "DUPLICATE"
        )

        # 3) One combined 3-page PDF = one print job.
        final_pdf = temp_dir / "PRINT_INVOICE_1_CHALLAN_2.pdf"
        _merge_pdfs(
            [str(invoice_one), str(challan_original), str(challan_duplicate)],
            str(final_pdf),
        )

        direct_print_pdf(str(final_pdf))
        return str(final_pdf)
    except Exception:
        # Keep files for troubleshooting if something fails.
        raise


def print_challan_direct(challan_tab):
    """Print the current Challan as two separate A4 pages in one job."""
    items = list(getattr(challan_tab, "items", []) or [])[:25]
    if not items:
        raise RuntimeError("Add at least one product to the Challan first.")

    customer = challan_tab.current_customer() or {}
    header = {
        "number": challan_tab.number.get().strip(),
        "date": challan_tab.dt.get().strip(),
        "day": getattr(challan_tab, "day_var", None).get() if hasattr(challan_tab, "day_var") else "",
        "time": getattr(challan_tab, "time", None).get() if hasattr(challan_tab, "time") else "",
        "godown": challan_tab.c_godown.get().strip(),
        "subtotal": sum(
            _safe_float(it.get("amount"))
            if it.get("amount") is not None
            else _safe_float(it.get("qty")) * _safe_float(it.get("price"))
                 + _safe_float(it.get("loading"))
            for it in items
        ),
        "total": sum(
            _safe_float(it.get("amount"))
            if it.get("amount") is not None
            else _safe_float(it.get("qty")) * _safe_float(it.get("price"))
                 + _safe_float(it.get("loading"))
            for it in items
        ),
        "notes": getattr(challan_tab, "desc", None).get()
                 if hasattr(challan_tab, "desc") else "",
        "gst_mode": "NO_GST",
    }

    temp_dir = Path(tempfile.mkdtemp(prefix="challan_print_"))
    try:
        p1 = temp_dir / "challan_original.pdf"
        p2 = temp_dir / "challan_duplicate.pdf"
        final = temp_dir / "PRINT_CHALLAN_2_COPIES.pdf"

        make_challan_25_pdf(header, customer, items, str(p1), "ORIGINAL")
        make_challan_25_pdf(header, customer, items, str(p2), "DUPLICATE")
        _merge_pdfs([str(p1), str(p2)], str(final))
        direct_print_pdf(str(final))
        return str(final)
    except Exception:
        raise
