import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from config import COMPANY

EXPORT_DIR=os.path.join(os.path.dirname(os.path.dirname(__file__)),'exports')
os.makedirs(EXPORT_DIR,exist_ok=True)

# Ek challan madhye maximum kiti products chalatil.
MAX_CHALLAN_ITEMS = 10


class ChallanItemLimitError(ValueError):
    """10 peksha jast product zale tar ha error yeto."""
    pass


def money(v): return f'{float(v or 0):,.2f}'
def clean(v): return str(v or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def br(v): return clean(v).replace('\n','<br/>')

def generated_stamp():
    now=datetime.now()
    return {
        'generated_date': now.strftime('%d-%m-%Y'),
        'generated_day': now.strftime('%A'),
        'generated_time': now.strftime('%I:%M:%S %p'),
    }

def image_or_blank(path, width_mm=22, height_mm=22):
    if path and os.path.exists(path):
        try:
            return Image(path, width=width_mm*mm, height=height_mm*mm)
        except Exception:
            return ''
    return ''

def amount_words(n):
    try:
        n=int(round(float(n)))
        ones=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen']
        tens=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
        def sub(x):
            s=''
            if x>=100: s+=ones[x//100]+' Hundred '; x%=100
            if x>=20: s+=tens[x//10]+' '; x%=10
            if x: s+=ones[x]+' '
            return s.strip()
        if n==0:return 'Zero Rupees Only'
        parts=[]
        if n>=10000000: parts.append(sub(n//10000000)+' Crore');n%=10000000
        if n>=100000: parts.append(sub(n//100000)+' Lakh');n%=100000
        if n>=1000: parts.append(sub(n//1000)+' Thousand');n%=1000
        if n: parts.append(sub(n))
        return ' '.join(parts)+' Rupees Only'
    except:return ''


def customer_phone(customer):
    """Customer cha phone no. Contact No ani Phone No donhi check karto.
    Donhi bhartil astil ani vegle astil tar donhi dakhavto (a, b)."""
    customer = customer or {}
    nums = []
    for key in ('contact_no', 'phone_no'):
        v = str(customer.get(key) or '').strip()
        if v and v not in nums:
            nums.append(v)
    return ', '.join(nums)


# ---------------------------------------------------------------------------
# Common item-text helper (Invoice + Challan).
# Text max 2 lines madhe basto, font auto lahan hoto, lamb shabd character-wise
# todto, aani text kadhich cell chya baher jaat nahi.
# ---------------------------------------------------------------------------
def _wrap_words(value, max_width, font, size):
    words = str(value or '').replace('\n', ' ').split()
    if not words:
        return ['']
    out, cur = [], ''
    for w in words:
        test = w if not cur else cur + ' ' + w
        if stringWidth(test, font, size) <= max_width:
            cur = test
            continue
        if cur:
            out.append(cur)
            cur = ''
        # khup lamb shabd asel tar character-wise tod
        while stringWidth(w, font, size) > max_width and len(w) > 1:
            k = len(w)
            while k > 1 and stringWidth(w[:k], font, size) > max_width:
                k -= 1
            out.append(w[:k])
            w = w[k:]
        cur = w
    if cur:
        out.append(cur)
    return out

def draw_item_text(c, x, y_mid, value, max_width, bold=False,
                   sizes=(7, 6.5, 6, 5.5, 5, 4.6, 4.2), max_lines=2, semi=False):
    """Item text: max 2 lines, font auto lahan hoto, kadhi baher jaat nahi."""
    font = 'Helvetica-Bold' if bold else 'Helvetica'
    ls, s = [''], sizes[-1]
    found = False
    for s in sizes:
        ls = _wrap_words(value, max_width, font, s)
        if len(ls) <= max_lines:
            found = True
            break
    if not found:
        s = sizes[-1]
        ls = _wrap_words(value, max_width, font, s)[:max_lines]
        t = ls[-1]
        while t and stringWidth(t + '...', font, s) > max_width:
            t = t[:-1]
        ls[-1] = t + '...'
    lead = s + 0.9
    first = y_mid + (len(ls) - 1) * lead / 2 - s * 0.35
    c.setFillColor(colors.black)
    c.setFont(font, s)
    for j, t in enumerate(ls):
        if semi and not bold:
            # slightly bolder than normal: fill + hairline outline
            c.saveState()
            c.setStrokeColor(colors.black)
            c.setLineWidth(0.08)
            to = c.beginText()
            to.setTextRenderMode(2)
            to.setFont(font, s)
            to.setTextOrigin(x, first - j * lead)
            to.textOut(t)
            c.drawText(to)
            c.restoreState()
        else:
            c.drawString(x, first - j * lead, t)


# Default Terms & Conditions shown on every Quotation PDF.
# Edit this list to change the wording — one entry per line on the PDF.
DEFAULT_QUOTATION_TERMS = [
    "Thanks for doing business with us!",
    "Our Quotation No must be mentioned on your Purchase Order. Insurance: Extra in customer's scope",
    "Packaging & Forwarding: Extra at actual.",
    "Payment Terms - 90% Advanced along with PO, 10% after installation within week.",
    "Lead Time - 4-6 weeks after receipt of PO and Advance.",
    "Installation and Training: Rs. 4000 per day, accommodation in customer's scope.",
    "Freight: Extra at actual, on 'to pay' basis.",
    "Taxes: At actual at the time of invoicing/dispatch. Any other Govt. duties, taxes or local levies shall be borne by the customer.",
    "Please seek clarification on system/technical aspects with us before committing to the customer.",
    "Please cross check for completeness of the system before ordering. We will not be responsible for any deviations.",
    "Prices are given considering the BOQ; same discounts may not apply if the BOQ changes.",
    "Validity: Quote is valid for 7 days from date of offer / based on exchange rate fluctuation, whichever is earlier.",
    "Software License: Pre-installed software is valid for 90 days from date of dispatch. Permanent license key is handed over after installation and clearance of all commercial documents.",
    "Orders: All orders are subject to acceptance by us. Order acknowledgement / Proforma Invoice will be sent by email/post to confirm acceptance.",
    "Order Cancellation: A PO once placed can be cancelled/modified only within 24 hours of receipt, since goods are mainly imported and processing starts immediately. Cancellation after that may attract charges up to 20% of order value or more, depending on the stage of processing.",
    "Liability: We (including our Directors and Employees) are not liable for any direct, indirect or consequential damages, loss of business information, business interruption, or any other loss arising from use or inability to use the product/system supplied.",
    "Force Majeure: Delivery period and price are calculated under prevailing conditions. Drastic changes due to flood, fire, storm, war, riot, or change in Government policy may affect delivery time and pricing. We reserve the right to reject an order without assigning any reason.",
    "Intellectual Property: All rights (trademarks, copyrights, design rights and other IP) remain reserved. Text, images, graphics and other content are not to be copied for commercial use or distribution, nor modified.",
    "Dispute Resolution: Governed by the laws of India; disputes are subject to the jurisdiction of the courts in Pune, Maharashtra, India.",
]

def make_quotation_pdf(header, customer, items, path=None):
    """Builds the Quotation PDF in the 'Estimate' layout (matches the
    JAY BHAVANI TRANSPORT reference format: big title, boxed company header,
    Estimate For / Estimate Details box, item table, HSN-wise tax summary +
    totals box, amount in words, terms & conditions, bank details + QR)."""
    no=header.get('number','DOC')
    path=path or os.path.join(EXPORT_DIR,f'quotation_{no}.pdf')
    stamp=generated_stamp()
    # Day is based on the quotation Date; time is the actual generation time.
    try:
        doc_day=datetime.strptime(str(header.get('date','')).strip(), '%d-%m-%Y').strftime('%A')
    except Exception:
        doc_day=stamp['generated_day']
    stamp['generated_day']=doc_day

    styles=getSampleStyleSheet()
    normal=styles['BodyText'].clone('QNormal'); normal.fontSize=8; normal.leading=10.5
    small=styles['BodyText'].clone('QSmall'); small.fontSize=7; small.leading=9
    title_style=styles['Heading1'].clone('QTitle'); title_style.alignment=TA_CENTER; title_style.fontSize=20; title_style.leading=24
    right=styles['BodyText'].clone('QRight'); right.alignment=TA_RIGHT; right.fontSize=8; right.leading=10.5

    d=SimpleDocTemplate(path,pagesize=A4,leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=8*mm)
    story=[]

    # ---- Title ----
    story.append(Paragraph('Quotation', title_style))
    story.append(Spacer(1,4))

    # ---- Company header box (company info, no logo) ----
    company_lines=(f'<b><font size="13">{clean(COMPANY.get("name",""))}</font></b><br/>'
                   f'<font size="7">{br(COMPANY.get("address",""))}</font><br/>'
                   f'<font size="7.5">Phone: <b>{clean(COMPANY.get("phone",""))}</b> &nbsp;&nbsp; '
                   f'Email: <b>{clean(COMPANY.get("email",""))}</b><br/>'
                   f'GSTIN: <b>{clean(COMPANY.get("gstin",""))}</b> &nbsp;&nbsp; '
                   f'State: <b>{clean(COMPANY.get("state",""))}</b></font>')
    head=Table([[Paragraph(company_lines,normal)]],colWidths=[194*mm])
    head.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(head)
    story.append(Spacer(1,4))

    # ---- Estimate For / Estimate Details box ----
    est_for=(f'<b>Estimate For:</b><br/><b>{clean(customer.get("name",""))}</b><br/>'
             f'{br(customer.get("address",""))}<br/>'
             f'Contact No: {clean(customer.get("contact_no",""))}<br/>'
             f'State: {clean(customer.get("state",""))} &nbsp;&nbsp; GSTIN Number: {clean(customer.get("gstin",""))}<br/>'
             f'Contact person name: {clean(customer.get("contact_person",""))}')
    est_details=(f'<b>Estimate Details:</b><br/>'
                 f'No: {clean(no)}<br/>'
                 f'Date: {clean(header.get("date",""))}<br/>'
                 f'Day: {clean(stamp["generated_day"])}<br/>'
                 f'Time: {clean(stamp["generated_time"])}<br/>'
                 f'Place of Supply: {clean(header.get("place_of_supply",customer.get("state","")))}<br/>'
                 f'Contact No.: {clean(customer.get("contact_no",""))}<br/>'
                 f'Email: {clean(customer.get("email",""))}')
    info=Table([[Paragraph(est_for,normal),Paragraph(est_details,normal)]],colWidths=[97*mm,97*mm])
    info.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('LINEBEFORE',(1,0),(1,-1),.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(info)
    story.append(Spacer(1,4))

    # ---- Item table ----
    idata=[['Item name','HSN/ SAC','Quantity','Price/ Unit (Rs.)','Amount(Rs.)']]
    total_qty=0.0
    for it in items:
        total_qty+=float(it.get('qty',0) or 0)
        idata.append([Paragraph(clean(it.get('item_name','')),small),clean(it.get('hsn_sac','')),
                       money(it.get('qty',0)),money(it.get('price',0)),money(it.get('amount',0))])
    while len(idata)<7: idata.append(['','','','',''])
    idata.append(['Total','',money(total_qty),'',money(header.get('subtotal',0))])
    it_table=Table(idata,colWidths=[82*mm,26*mm,26*mm,29*mm,31*mm],repeatRows=1)
    it_table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),.35,colors.black),
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9EEF5')),
        ('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#F6F7F9')),
        ('FONT',(0,0),(-1,-1),'Helvetica',7.5),
        ('FONT',(0,0),(-1,0),'Helvetica-Bold',8),
        ('FONT',(0,-1),(-1,-1),'Helvetica-Bold',8.2),
        ('ALIGN',(2,1),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('SPAN',(0,-1),(1,-1)),
    ]))
    story.append(it_table)
    story.append(Spacer(1,4))

    # ---- HSN-wise Tax Summary (left) + Sub Total/Tax/Shipping/Total + Amount in words (right) ----
    hsn_map={}
    for it in items:
        h=it.get('hsn_sac','') or ''
        hsn_map[h]=hsn_map.get(h,0.0)+float(it.get('amount',0) or 0)
    g=float(header.get('gst_rate') or 0)
    tdata=[['HSN/SAC','Taxable Amt','CGST%','CGST Amt','SGST%','SGST Amt','Total Tax']]
    for h,amt in hsn_map.items():
        cg=amt*g/200; sg=amt*g/200
        tdata.append([clean(h),money(amt),money(g/2),money(cg),money(g/2),money(sg),money(cg+sg)])
    tdata.append(['TOTAL',money(header.get('subtotal',0)),'',money(header.get('cgst',0)),'',money(header.get('sgst',0)),money(float(header.get('cgst',0))+float(header.get('sgst',0)))])
    tax_table=Table(tdata,colWidths=[20*mm,22*mm,13*mm,17*mm,13*mm,17*mm,17*mm])
    tax_table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),.35,colors.black),
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9EEF5')),
        ('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#F6F7F9')),
        ('FONT',(0,0),(-1,-1),'Helvetica',6.6),
        ('FONT',(0,0),(-1,0),'Helvetica-Bold',6.8),
        ('FONT',(0,-1),(-1,-1),'Helvetica-Bold',7),
        ('ALIGN',(1,0),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))
    summary_lines=(f'Sub Total : {money(header.get("subtotal",0))}<br/>'
                    f'Tax ({g:.1f}%) : {money(float(header.get("cgst",0))+float(header.get("sgst",0)))}<br/>'
                    f'Shipping : {money(header.get("shipping",0))}<br/>'
                    f'<b>Total : {money(header.get("total",0))}</b><br/><br/>'
                    f'<b>Estimate Amount In Words:</b><br/>{clean(amount_words(header.get("total",0)))}')
    right_cell=Paragraph(summary_lines,normal)
    combo=Table([[tax_table,right_cell]],colWidths=[119*mm,75*mm])
    combo.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('LINEBEFORE',(1,0),(1,-1),.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),5)]))
    story.append(combo)
    story.append(Spacer(1,4))

    # ---- Terms and Conditions ----
    terms_html='<b>Terms And Conditions:</b><br/>'+'<br/>'.join(clean(t) for t in DEFAULT_QUOTATION_TERMS)
    terms_box=Table([[Paragraph(terms_html,small)]],colWidths=[194*mm])
    terms_box.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('PADDING',(0,0),(-1,-1),6)]))
    story.append(terms_box)
    story.append(Spacer(1,4))

    # ---- Bank Details (with QR/scanner) + Signature ----
    scanner_img=image_or_blank(COMPANY.get('scanner_path'),22,22)
    bank_html='<b>Bank Details:</b><br/>'+br(COMPANY.get('bank',''))
    if scanner_img:
        bank_cell=Table([[scanner_img,Paragraph(bank_html,small)]],colWidths=[24*mm,102*mm])
        bank_cell.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    else:
        bank_cell=Paragraph(bank_html,small)
    sign_cell=Paragraph(f'For <b>{clean(COMPANY.get("name",""))}</b><br/><br/><br/>Authorized Signatory<br/><font size="6">Generated: {stamp["generated_date"]} | {stamp["generated_day"]} | {stamp["generated_time"]}</font>',right)
    footer=Table([[bank_cell,sign_cell]],colWidths=[130*mm,64*mm])
    footer.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('LINEBEFORE',(1,0),(1,-1),.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(1,0),(1,-1),'CENTER'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(footer)

    d.build(story)
    return path


def make_invoice_bill_pdf(header, customer, items, path=None, copy_label='ORIGINAL'):
    """GST / Without-GST invoice - no ORIGINAL / DUPLICATE names.
    header['copies'] = number of identical copies; 2 copies share one A4 sheet.

    * Real sizes - nothing is scaled or stretched (the old 50%/2x trick is removed).
    * Max 8 items per copy. If there are more items the invoice continues on the
      next A4 page (both copies again). Totals, bank and signature are printed
      only on the LAST page.
    * Product description / material text automatically becomes smaller
      (2 lines max) when the text is long.
    * Tax type: header['tax_type'] == 'IGST'  -> one line "IGST x %"
                otherwise (default)           -> "CGST x/2 %" + "SGST x/2 %"
      (IGST only applies to GST invoices; WITHOUT GST shows no tax at all.)

    Columns: SR.NO | PRODUCT DESCRIPTION | MATERIAL | HSN CODE | QTY | LOADING | RATE | TOTAL
    (copy_label is kept only for compatibility - both copies are always printed.)
    """
    from reportlab.pdfgen import canvas

    gst_mode = (header.get('gst_mode') or 'GST').upper() != 'NO_GST'
    # Manual choice made on the Invoice form: 'CGST+SGST' (default) or 'IGST'
    igst_mode = gst_mode and str(header.get('tax_type') or '').strip().upper() == 'IGST'
    no = str(header.get('number', 'DOC'))
    path = path or os.path.join(EXPORT_DIR, f'invoice_{no}_{copy_label}.pdf')
    items = list(items or [])

    # header['copies'] = how many identical copies to print (default 1)
    try:
        copies = max(1, min(int(header.get('copies') or 1), 10))
    except (ValueError, TypeError):
        copies = 1

    W, H = A4
    HH = H / 2                       # one copy = half of the page height
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(f'Invoice {no}')
    c.setAuthor(COMPANY.get('name', ''))

    L = 7 * mm
    R = W - 7 * mm
    BLACK = colors.black
    HEAD_BG = colors.HexColor('#E9EEF5')
    SOFT = colors.HexColor('#C9CED6')

    # ------------------------------------------------------------ helpers
    def line(x1, y1, x2, y2, w=0.6, col=BLACK):
        c.setStrokeColor(col); c.setLineWidth(w); c.line(x1, y1, x2, y2)

    def rect(x, y, w, h, lw=0.8, fill=None):
        c.setStrokeColor(BLACK); c.setLineWidth(lw)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x, y, w, h, stroke=1, fill=1 if fill is not None else 0)

    def txt(x, y, value, size=7, bold=False, align='left', semi=False):
        c.setFillColor(BLACK)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        value = str(value if value is not None else '')
        if semi and not bold:
            # slightly bolder than normal: fill + hairline outline
            w_ = stringWidth(value, 'Helvetica', size)
            ox = x - w_ / 2 if align == 'center' else (x - w_ if align == 'right' else x)
            c.saveState()
            c.setStrokeColor(BLACK)
            c.setLineWidth(0.08)
            to = c.beginText()
            to.setTextRenderMode(2)
            to.setFont('Helvetica', size)
            to.setTextOrigin(ox, y)
            to.textOut(value)
            c.drawText(to)
            c.restoreState()
            return
        if align == 'center':
            c.drawCentredString(x, y, value)
        elif align == 'right':
            c.drawRightString(x, y, value)
        else:
            c.drawString(x, y, value)

    def wrap(value, max_width, font, size):
        words = str(value or '').replace('\n', ' ').split()
        if not words:
            return ['']
        out, cur = [], ''
        for word in words:
            test = word if not cur else cur + ' ' + word
            if stringWidth(test, font, size) <= max_width:
                cur = test
            else:
                if cur:
                    out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        return out

    def fit_line(x, y, value, max_width, base=7.0, minimum=4.5, bold=False, align='left', semi=False):
        """One line of text; font shrinks until it fits the width."""
        value = str(value if value is not None else '')
        font = 'Helvetica-Bold' if bold else 'Helvetica'
        size = base
        while size > minimum and stringWidth(value, font, size) > max_width:
            size -= 0.2
        txt(x, y, value, round(size, 1), bold, align, semi)

    def money2(v):
        return f'{float(v or 0):,.2f}'

    def num(v):
        return money2(v).rstrip('0').rstrip('.') or '0'

    # ------------------------------------------------------------ geometry
    # (all y values are measured inside ONE copy; TOP is near the top of the half page)
    TOP = HH - 5.5 * mm
    HEAD_H = 21 * mm
    INFO_H = 21 * mm
    TH = 6.5 * mm                    # table heading row
    TOTAL_H = 5.5 * mm               # TOTAL row of the table
    FOOT_H = 38 * mm
    BOTTOM = 3 * mm
    ROW_H = 5.5 * mm

    head_bot = TOP - HEAD_H
    info_top = head_bot
    info_bot = info_top - INFO_H
    table_top = info_bot
    body_top = table_top - TH
    foot_top = BOTTOM + FOOT_H
    body_bot = foot_top + TOTAL_H
    rows_per_page = max(1, int((body_top - body_bot + 0.5) // ROW_H))

    chunks = [items[i:i + rows_per_page] for i in range(0, len(items), rows_per_page)] or [[]]
    page_count = len(chunks)

    # column x positions: SR | DESC | MATERIAL | HSN | QTY | LOADING | RATE | TOTAL
    widths = [10, 62, 30, 20, 20, 14, 18, 20]
    xs = [L]
    for w_ in widths:
        xs.append(xs[-1] + w_ * mm)
    xs[-1] = R

    cust_name = customer.get('name', '') or ''
    cust_addr = customer.get('address', '') or ''
    cust_gstin = customer.get('gstin', '') or ''
    cust_state = customer.get('state', '') or ''
    cust_code = cust_gstin[:2] if cust_gstin else ''
    contact = customer_phone(customer) or '-'

    total_qty_all = sum(float(it.get('qty', 0) or 0) for it in items)
    total_loading_all = sum(float(it.get('loading', 0) or 0) for it in items)
    g = float(header.get('gst_rate') or 5.0)

    # ------------------------------------------------------------ one copy
    def draw_copy(label, y0, page_items, page_no):
        is_last = (page_no == page_count)
        mid = (L + R) / 2

        c.saveState()
        c.translate(0, y0)

        # copy label (+ page number)
        txt(R, TOP + 1.8 * mm, label, 7.5, True, 'right')
        if page_count > 1:
            txt(L, TOP + 1.8 * mm, f'Page {page_no} / {page_count}', 7, True)

        # ---------- company header ----------
        rect(L, head_bot, R - L, HEAD_H, 0.9)
        txt(mid, TOP - 3.8 * mm, 'TAX INVOICE' if gst_mode else 'BILL', 8, True, 'center')
        txt(mid, TOP - 7.0 * mm, 'JAI GANESH', 6.3, True, 'center')
        fit_line(mid, TOP - 13.2 * mm, COMPANY.get('name', 'JAY BHAVANI TRANSPORT'),
                 115 * mm, 15, 9, True, 'center')
        for j, s in enumerate(wrap(COMPANY.get('address', ''), 125 * mm, 'Helvetica-Bold', 6.3)[:2]):
            txt(mid, TOP - (16.4 + j * 2.7) * mm, s, 6.3, True, 'center')
        if gst_mode:
            txt(L + 2.5 * mm, TOP - 3.8 * mm, 'CREDIT MEMO', 6.8, True)
        txt(R - 2.5 * mm, TOP - 3.8 * mm, 'Dada Telange', 6.8, True, 'right')
        txt(R - 2.5 * mm, TOP - 7.0 * mm, COMPANY.get('phone', ''), 6.8, True, 'right')

        # ---------- customer + invoice details ----------
        rect(L, info_bot, R - L, INFO_H, 0.8)
        split = L + 128 * mm
        line(split, info_bot, split, info_top, 0.7)
        for off in (5, 12, 16.5):                      # left rows: 5 | 7 | 4.5 | 4.5
            line(L, info_top - off * mm, split, info_top - off * mm, 0.4, SOFT)
        for off in (7, 14):                            # right rows: 7 | 7 | 7
            line(split, info_top - off * mm, R, info_top - off * mm, 0.4, SOFT)

        vx = L + 19 * mm
        txt(L + 2 * mm, info_top - 3.6 * mm, 'Name :', 7, True)
        fit_line(vx, info_top - 3.6 * mm, cust_name, split - vx - 2 * mm, 7.8, 5, True)

        txt(L + 2 * mm, info_top - 8.3 * mm, 'Address :', 7, True)
        for j, s in enumerate(wrap(cust_addr, split - vx - 2 * mm, 'Helvetica', 6.8)[:2]):
            txt(vx, info_top - (8.3 + j * 2.9) * mm, s, 6.8)

        txt(L + 2 * mm, info_top - 15.0 * mm, 'State :', 7, True)
        fit_line(vx, info_top - 15.0 * mm, cust_state, 60 * mm, 7.2, 5)
        txt(L + 90 * mm, info_top - 15.0 * mm, 'Code :', 7, True)
        txt(L + 102 * mm, info_top - 15.0 * mm, cust_code, 7.2)

        # Last row (just below State): GSTIN | Mob. No. | Vehicle (optional)
        vehicle = str(header.get('vehicle') or '').strip()
        if gst_mode:
            txt(L + 2 * mm, info_top - 19.5 * mm, 'GSTIN :', 7, True)
            fit_line(vx, info_top - 19.5 * mm, cust_gstin, 31 * mm, 7.2, 5)
            txt(L + 52 * mm, info_top - 19.5 * mm, 'Mob. No. :', 7, True)
            fit_line(L + 66 * mm, info_top - 19.5 * mm, contact, 22 * mm, 7.2, 4.5)
            if vehicle:
                txt(L + 90 * mm, info_top - 19.5 * mm, 'Vehicle :', 7, True)
                fit_line(L + 102.5 * mm, info_top - 19.5 * mm, vehicle, 24 * mm, 7.2, 4.5, True)
        else:
            if vehicle:
                txt(L + 2 * mm, info_top - 19.5 * mm, 'Vehicle :', 7, True)
                fit_line(vx, info_top - 19.5 * mm, vehicle, 55 * mm, 7.2, 5, True)
            txt(L + 78 * mm, info_top - 19.5 * mm, 'Mob. No. :', 7, True)
            fit_line(L + 95 * mm, info_top - 19.5 * mm, contact, 31 * mm, 7.2, 5)

        rx = split + 2.5 * mm
        vx2 = split + 24 * mm
        if gst_mode:
            txt(rx, info_top - 4.6 * mm, 'GSTIN :', 7, True)
            fit_line(vx2, info_top - 4.6 * mm, COMPANY.get('gstin', ''), R - vx2 - 1.5 * mm, 7.2, 5, True)
        txt(rx, info_top - 11.6 * mm, 'Invoice No. :', 7, True)
        fit_line(vx2, info_top - 11.6 * mm, no, R - vx2 - 1.5 * mm, 8.5, 5, True)
        txt(rx, info_top - 18.6 * mm, 'Date :', 7, True)
        txt(vx2, info_top - 18.6 * mm, header.get('date', ''), 7.8, True)

        # ---------- item table ----------
        rect(L, foot_top, R - L, table_top - foot_top, 0.8)
        rect(L, table_top - TH, R - L, TH, 0.6, HEAD_BG)
        for xx in xs[1:-1]:
            line(xx, foot_top, xx, table_top, 0.5)

        for r_ in range(1, rows_per_page + 1):          # faint row lines
            yy = body_top - r_ * ROW_H
            if yy > body_bot + 0.5:
                line(L, yy, R, yy, 0.25, SOFT)

        hy = table_top - TH / 2 - 2.0
        heads = ['SR.NO', 'PRODUCT DESCRIPTION', 'MATERIAL', 'HSN CODE', 'QTY', 'LOADING', 'RATE', 'TOTAL']
        for k, hname in enumerate(heads):
            fit_line((xs[k] + xs[k + 1]) / 2, hy, hname, xs[k + 1] - xs[k] - 1.2 * mm,
                     6.6, 4.5, True, 'center')

        start_no = (page_no - 1) * rows_per_page
        for i, it in enumerate(page_items):
            row_top = body_top - i * ROW_H
            ym = row_top - ROW_H / 2
            base = ym - 7 * 0.35

            txt((xs[0] + xs[1]) / 2, base, str(start_no + i + 1), 7, False, 'center', semi=True)
            # FIXED: item name + material -> max 2 lines, auto small font, never overflows
            draw_item_text(c, xs[1] + 1.3 * mm, ym, it.get('item_name', '') or '', xs[2] - xs[1] - 2.6 * mm, semi=True)
            draw_item_text(c, xs[2] + 1.3 * mm, ym, it.get('material', '') or '', xs[3] - xs[2] - 2.6 * mm, semi=True)
            fit_line((xs[3] + xs[4]) / 2, base, it.get('hsn_sac', '') or '-', xs[4] - xs[3] - 1.6 * mm,
                     7, 4.5, False, 'center', semi=True)

            qtxt = num(it.get('qty', 0))
            unit = it.get('unit', '') or ''
            if unit:
                qtxt += ' ' + unit
            fit_line((xs[4] + xs[5]) / 2, base, qtxt, xs[5] - xs[4] - 1.6 * mm, 7, 4.5, False, 'center', semi=True)
            fit_line((xs[5] + xs[6]) / 2, base, num(it.get('loading', 0)), xs[6] - xs[5] - 1.6 * mm,
                     7, 4.5, False, 'center', semi=True)
            fit_line(xs[7] - 1.5 * mm, base, money2(it.get('price', 0)), xs[7] - xs[6] - 2.5 * mm,
                     7, 4.5, False, 'right', semi=True)
            fit_line(R - 1.5 * mm, base, money2(it.get('amount', 0)), xs[8] - xs[7] - 2.5 * mm,
                     7, 4.5, False, 'right', semi=True)

        # TOTAL row of the table
        rect(L, foot_top, R - L, TOTAL_H, 0.6, HEAD_BG)
        for xx in xs[1:-1]:
            if xx >= xs[4]:
                line(xx, foot_top, xx, foot_top + TOTAL_H, 0.5)
        ty = foot_top + TOTAL_H / 2 - 7.2 * 0.35
        if is_last:
            txt((xs[0] + xs[4]) / 2, ty, 'TOTAL', 7.4, True, 'center')
            fit_line((xs[4] + xs[5]) / 2, ty, num(total_qty_all), xs[5] - xs[4] - 1.6 * mm, 7.2, 4.5, True, 'center')
            fit_line((xs[5] + xs[6]) / 2, ty, num(total_loading_all), xs[6] - xs[5] - 1.6 * mm, 7.2, 4.5, True, 'center')
            fit_line(R - 1.5 * mm, ty, money2(header.get('subtotal', 0)), xs[8] - xs[7] - 2.5 * mm, 7.4, 4.5, True, 'right')
        else:
            txt((xs[0] + xs[8]) / 2, ty, 'Continued on next page ...', 7.4, True, 'center')

        # ---------- footer ----------
        totals_x = L + 130 * mm
        rect(L, BOTTOM, totals_x - L, FOOT_H, 0.8)
        rect(totals_x, BOTTOM, R - totals_x, FOOT_H, 0.8)
        left_w = totals_x - L

        # left: amount in words (8) | bank (15) | terms (8) | receiver sign (7)
        a_bot = foot_top - 8 * mm
        b_bot = a_bot - 15 * mm
        t_bot = b_bot - 8 * mm
        for yy in (a_bot, b_bot, t_bot):
            line(L, yy, totals_x, yy, 0.5)

        txt(L + 2 * mm, foot_top - 3.5 * mm, 'Amount (in Words) :', 6.8, True)
        if is_last:
            fit_line(L + 29 * mm, foot_top - 3.5 * mm, amount_words(header.get('total', 0)),
                     left_w - 31 * mm, 7, 4.8, True)
        txt(L + 2 * mm, foot_top - 6.8 * mm, '', 6)

        txt(L + 2 * mm, a_bot - 3.4 * mm, 'BANK DETAILS :', 6.8, True)
        txt(L + 27 * mm, a_bot - 3.4 * mm, COMPANY.get('name', ''), 6.8, True)
        bank_lines = [z.strip() for z in str(COMPANY.get('bank', '')).split('\n') if z.strip()]
        for j, bl in enumerate(bank_lines[:3]):
            fit_line(L + 2 * mm, a_bot - (6.8 + j * 2.9) * mm, bl, left_w - 4 * mm, 6.6, 4.8, False)

        txt(L + 2 * mm, b_bot - 3.2 * mm, 'TERMS AND CONDITIONS :', 6.8, True)
        txt(L + 2 * mm, b_bot - 6.4 * mm, '1. CHEQUE RETURN CHARGES RS.200/-', 6.6, False)

        txt(L + left_w / 2, BOTTOM + 1.8 * mm, 'Receiver Signature', 6.8, True, 'center')

        # right: totals
        rows = [('TOTAL', money2(header.get('subtotal', 0))),
                ('DISC.', money2(header.get('discount', 0)))]
        if gst_mode:
            if igst_mode:
                # Different state -> full tax shown as ONE IGST line
                tax_total = float(header.get('cgst', 0) or 0) + float(header.get('sgst', 0) or 0)
                rows += [(f'IGST {g:.1f} %', money2(tax_total))]
            else:
                # Same state -> tax split into CGST + SGST
                rows += [(f'CGST {g / 2:.1f} %', money2(header.get('cgst', 0))),
                         (f'SGST {g / 2:.1f} %', money2(header.get('sgst', 0)))]
        rows += [('Freight Chr.', money2(header.get('freight', 0))),
                 ('Other Chr.', money2(header.get('other_charges', 0)))]

        rh = 4.3 * mm
        if is_last:
            yy = foot_top
            for lab, val in rows:
                txt(totals_x + 2 * mm, yy - rh / 2 - 2.4, lab, 7, True)
                txt(R - 2 * mm, yy - rh / 2 - 2.4, val, 7, True, 'right')
                yy -= rh
                line(totals_x, yy, R, yy, 0.3, SOFT)
            net_top = foot_top - len(rows) * rh
            net_h = 6 * mm
            rect(totals_x, net_top - net_h, R - totals_x, net_h, 0.8, HEAD_BG)
            txt(totals_x + 2 * mm, net_top - net_h / 2 - 2.8, 'NET TOTAL', 8, True)
            fit_line(R - 2 * mm, net_top - net_h / 2 - 2.8, money2(header.get('total', 0)),
                     R - totals_x - 26 * mm, 8.5, 5, True, 'right')
            sign_top = net_top - net_h
        else:
            txt((totals_x + R) / 2, foot_top - 14 * mm, 'Continued on next page ...', 7, True, 'center')
            sign_top = foot_top - 22 * mm

        fit_line(totals_x + 2 * mm, sign_top - 3.6 * mm, f'For {COMPANY.get("name", "")}',
                 R - totals_x - 4 * mm, 6.8, 5, True)
        txt(R - 2 * mm, BOTTOM + 1.8 * mm, 'Authorized Signature', 6.8, False, 'right')

        c.restoreState()

    # Every copy is identical (no ORIGINAL / DUPLICATE name). Pages of the
    # invoice are repeated `copies` times; 2 copies share one A4 sheet
    # (top half + bottom half). An odd last copy sits alone on the top half.
    slots = [(pn, pi) for pn, pi in enumerate(chunks, 1) for _ in range(copies)]
    for s_ in range(0, len(slots), 2):
        pair = slots[s_:s_ + 2]
        for k, (pn, pi) in enumerate(pair):
            draw_copy('', HH if k == 0 else 0, pi, pn)
        if len(pair) == 2:
            # cut line in the middle
            c.setStrokeColor(colors.grey); c.setLineWidth(0.4); c.setDash(3, 3)
            c.line(L, HH, R, HH)
            c.setDash()
        c.showPage()
    c.save()
    return path


def make_challan_bill_pdf(header, customer, items, path=None, copy_label='ORIGINAL'):
    """Delivery Challan - same look & colours as the Invoice PDF.

    header['copies'] = how many identical copies to print (default 1).
    Two copies share one A4 sheet (top half + bottom half, cut line in the
    middle). An odd last copy sits alone on the top half of its sheet.

    One bill shows at most MAX_CHALLAN_ITEMS (10) products. If a challan has
    more products, it continues on the next page(s). Totals / charges / amount
    in words are printed only on the LAST page.

    Item table columns: SR.NO | GODOWN | ITEM | QUANTITY | RATE | LOADING | TOTAL
    """
    from reportlab.pdfgen import canvas

    items = list(items or [])
    chunks = [items[i:i + MAX_CHALLAN_ITEMS]
              for i in range(0, len(items), MAX_CHALLAN_ITEMS)] or [[]]
    page_count = len(chunks)

    try:
        copies = max(1, min(int(header.get('copies') or 1), 10))
    except (ValueError, TypeError):
        copies = 1

    no = str(header.get('number', 'DOC'))
    path = path or os.path.join(EXPORT_DIR, f'challan_{no}.pdf')

    W, H = A4
    HH = H / 2                       # one copy = half of the page height
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(f'Delivery Challan {no}')
    c.setAuthor(COMPANY.get('name', ''))

    L = 7 * mm
    R = W - 7 * mm
    BLACK = colors.black
    HEAD_BG = colors.HexColor('#E9EEF5')
    SOFT = colors.HexColor('#C9CED6')

    gst_mode = (header.get('gst_mode') or 'GST').upper() != 'NO_GST'

    # ------------------------------------------------------------ helpers
    def line(x1, y1, x2, y2, w=0.6, col=BLACK):
        c.setStrokeColor(col); c.setLineWidth(w); c.line(x1, y1, x2, y2)

    def rect(x, y, w, h, lw=0.8, fill=None):
        c.setStrokeColor(BLACK); c.setLineWidth(lw)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x, y, w, h, stroke=1, fill=1 if fill is not None else 0)

    def txt(x, y, value, size=7, bold=False, align='left'):
        c.setFillColor(BLACK)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        value = str(value if value is not None else '')
        if align == 'center':
            c.drawCentredString(x, y, value)
        elif align == 'right':
            c.drawRightString(x, y, value)
        else:
            c.drawString(x, y, value)

    def wrap(value, max_width, font, size):
        words = str(value or '').replace('\n', ' ').split()
        if not words:
            return ['']
        out, cur = [], ''
        for word in words:
            test = word if not cur else cur + ' ' + word
            if stringWidth(test, font, size) <= max_width:
                cur = test
            else:
                if cur:
                    out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        return out

    def fit_line(x, y, value, max_width, base=7.0, minimum=4.5, bold=False, align='left'):
        """One line of text; font shrinks until it fits the width."""
        value = str(value if value is not None else '')
        font = 'Helvetica-Bold' if bold else 'Helvetica'
        size = base
        while size > minimum and stringWidth(value, font, size) > max_width:
            size -= 0.2
        txt(x, y, value, round(size, 1), bold, align)

    def money2(v):
        return f'{float(v or 0):,.2f}'

    def num(v):
        return money2(v).rstrip('0').rstrip('.') or '0'

    def item_amount(it):
        a = it.get('amount')
        if a is None:
            a = (float(it.get('qty', 0) or 0) * float(it.get('price', 0) or 0)
                 + float(it.get('loading', 0) or 0))
        return float(a)

    # ------------------------------------------------------------ totals
    all_sum = sum(item_amount(it) for it in items)
    header_total = header.get('total')
    if header_total is None:
        header_total = all_sum
    header_subtotal = header.get('subtotal')
    if header_subtotal is None:
        header_subtotal = all_sum
    net_val = float(header_total)
    sub_val = float(header_subtotal)
    total_qty_all = sum(float(it.get('qty', 0) or 0) for it in items)
    total_loading_all = sum(float(it.get('loading', 0) or 0) for it in items)

    # ------------------------------------------------------------ geometry
    TOP = HH - 5.5 * mm
    HEAD_H = 21 * mm
    INFO_H = 21 * mm
    TH = 6 * mm                      # table heading row
    TOTAL_H = 5.5 * mm               # TOTAL row of the table
    FOOT_H = 38 * mm
    BOTTOM = 3 * mm

    head_bot = TOP - HEAD_H
    info_top = head_bot
    info_bot = info_top - INFO_H
    table_top = info_bot
    body_top = table_top - TH
    foot_top = BOTTOM + FOOT_H
    body_bot = foot_top + TOTAL_H
    ROW_H = (body_top - body_bot) / MAX_CHALLAN_ITEMS   # exactly 10 rows fit

    # columns: SR.NO | GODOWN | ITEM | QUANTITY | RATE | LOADING | TOTAL
    widths = [10, 24, 57, 25, 25, 23, 32]
    xs = [L]
    for w_ in widths:
        xs.append(xs[-1] + w_ * mm)
    xs[-1] = R

    cust_name = customer.get('name', '') or ''
    cust_addr = customer.get('address', '') or ''
    cust_gstin = customer.get('gstin', '') or ''
    cust_state = customer.get('state', '') or ''
    cust_code = cust_gstin[:2] if cust_gstin else ''
    contact = customer_phone(customer) or '-'

    # ------------------------------------------------------------ one copy
    def draw_copy(label, y0, page_items, page_no):
        is_last = (page_no == page_count)
        mid = (L + R) / 2

        c.saveState()
        c.translate(0, y0)

        if page_count > 1:
            txt(L, TOP + 1.8 * mm, f'Page {page_no} / {page_count}', 7, True)

        # ---------- company header ----------
        rect(L, head_bot, R - L, HEAD_H, 0.9)
        txt(mid, TOP - 3.8 * mm, 'DELIVERY CHALLAN', 8, True, 'center')
        txt(mid, TOP - 7.0 * mm, 'JAI GANESH', 6.3, True, 'center')
        fit_line(mid, TOP - 13.2 * mm, COMPANY.get('name', 'JAY BHAVANI TRANSPORT'),
                 115 * mm, 15, 9, True, 'center')
        for j, s in enumerate(wrap(COMPANY.get('address', ''), 125 * mm, 'Helvetica-Bold', 6.3)[:2]):
            txt(mid, TOP - (16.4 + j * 2.7) * mm, s, 6.3, True, 'center')
        txt(R - 2.5 * mm, TOP - 3.8 * mm, 'Dada Telange', 6.8, True, 'right')
        txt(R - 2.5 * mm, TOP - 7.0 * mm, COMPANY.get('phone', ''), 6.8, True, 'right')

        # ---------- customer + challan details ----------
        rect(L, info_bot, R - L, INFO_H, 0.8)
        split = L + 128 * mm
        line(split, info_bot, split, info_top, 0.7)
        for off in (5, 12, 16.5):
            line(L, info_top - off * mm, split, info_top - off * mm, 0.4, SOFT)
        for off in (7, 14):
            line(split, info_top - off * mm, R, info_top - off * mm, 0.4, SOFT)

        vx = L + 19 * mm
        txt(L + 2 * mm, info_top - 3.6 * mm, 'Name :', 7, True)
        fit_line(vx, info_top - 3.6 * mm, cust_name, split - vx - 2 * mm, 7.8, 5, True)

        txt(L + 2 * mm, info_top - 8.3 * mm, 'Address :', 7, True)
        for j, s in enumerate(wrap(cust_addr, split - vx - 2 * mm, 'Helvetica', 6.8)[:2]):
            txt(vx, info_top - (8.3 + j * 2.9) * mm, s, 6.8)

        txt(L + 2 * mm, info_top - 15.0 * mm, 'State :', 7, True)
        fit_line(vx, info_top - 15.0 * mm, cust_state, 60 * mm, 7.2, 5)
        txt(L + 90 * mm, info_top - 15.0 * mm, 'Code :', 7, True)
        txt(L + 102 * mm, info_top - 15.0 * mm, cust_code, 7.2)

        # Last row (just below State): GSTIN | Mob. No. | Vehicle (optional)
        vehicle = str(header.get('vehicle') or '').strip()
        if gst_mode:
            txt(L + 2 * mm, info_top - 19.5 * mm, 'GSTIN :', 7, True)
            fit_line(vx, info_top - 19.5 * mm, cust_gstin, 31 * mm, 7.2, 5)
            txt(L + 52 * mm, info_top - 19.5 * mm, 'Mob. No. :', 7, True)
            fit_line(L + 66 * mm, info_top - 19.5 * mm, contact, 22 * mm, 7.2, 4.5)
            if vehicle:
                txt(L + 90 * mm, info_top - 19.5 * mm, 'Vehicle :', 7, True)
                fit_line(L + 102.5 * mm, info_top - 19.5 * mm, vehicle, 24 * mm, 7.2, 4.5, True)
        else:
            if vehicle:
                txt(L + 2 * mm, info_top - 19.5 * mm, 'Vehicle :', 7, True)
                fit_line(vx, info_top - 19.5 * mm, vehicle, 55 * mm, 7.2, 5, True)
            txt(L + 78 * mm, info_top - 19.5 * mm, 'Mob. No. :', 7, True)
            fit_line(L + 95 * mm, info_top - 19.5 * mm, contact, 31 * mm, 7.2, 5)

        rx = split + 2.5 * mm
        vx2 = split + 24 * mm
        if gst_mode:
            txt(rx, info_top - 4.6 * mm, 'GSTIN :', 7, True)
            fit_line(vx2, info_top - 4.6 * mm, COMPANY.get('gstin', ''), R - vx2 - 1.5 * mm, 7.2, 5, True)
        txt(rx, info_top - 11.6 * mm, 'Challan No. :', 7, True)
        fit_line(vx2, info_top - 11.6 * mm, no, R - vx2 - 1.5 * mm, 8.5, 5, True)
        txt(rx, info_top - 18.6 * mm, 'Date :', 7, True)
        txt(vx2, info_top - 18.6 * mm, header.get('date', ''), 7.8, True)

        # ---------- item table ----------
        rect(L, foot_top, R - L, table_top - foot_top, 0.8)
        rect(L, table_top - TH, R - L, TH, 0.6, HEAD_BG)
        for xx in xs[1:-1]:
            line(xx, foot_top, xx, table_top, 0.5)

        for r_ in range(1, MAX_CHALLAN_ITEMS + 1):          # faint row lines
            yy = body_top - r_ * ROW_H
            if yy > body_bot + 0.5:
                line(L, yy, R, yy, 0.25, SOFT)

        hy = table_top - TH / 2 - 2.0
        heads = ['SR.NO', 'GODOWN', 'ITEM', 'QUANTITY', 'RATE', 'LOADING', 'TOTAL']
        for k, hname in enumerate(heads):
            fit_line((xs[k] + xs[k + 1]) / 2, hy, hname, xs[k + 1] - xs[k] - 1.2 * mm,
                     6.6, 4.5, True, 'center')

        item_sizes = (6.5, 6, 5.5, 5, 4.6, 4.2)
        start_no = (page_no - 1) * MAX_CHALLAN_ITEMS
        for i, it in enumerate(page_items):
            row_top = body_top - i * ROW_H
            ym = row_top - ROW_H / 2
            base = ym - 7 * 0.35

            txt((xs[0] + xs[1]) / 2, base, str(start_no + i + 1), 7, True, 'center')
            draw_item_text(c, xs[1] + 1.3 * mm, ym, it.get('godown', '') or '-',
                           xs[2] - xs[1] - 2.6 * mm, sizes=item_sizes, bold=True)
            draw_item_text(c, xs[2] + 1.3 * mm, ym, it.get('item_name', '') or '-',
                           xs[3] - xs[2] - 2.6 * mm, sizes=item_sizes, bold=True)

            qtxt = num(it.get('qty', 0))
            unit = it.get('unit', '') or ''
            if unit:
                qtxt += ' ' + unit
            fit_line((xs[3] + xs[4]) / 2, base, qtxt, xs[4] - xs[3] - 1.6 * mm, 7, 4.5, True, 'center')
            fit_line(xs[5] - 1.5 * mm, base, money2(it.get('price', 0)), xs[5] - xs[4] - 2.5 * mm,
                     7, 4.5, True, 'right')
            fit_line((xs[5] + xs[6]) / 2, base, num(it.get('loading', 0)), xs[6] - xs[5] - 1.6 * mm,
                     7, 4.5, True, 'center')
            fit_line(R - 1.5 * mm, base, money2(item_amount(it)), xs[7] - xs[6] - 2.5 * mm,
                     7, 4.5, True, 'right')

        # TOTAL row of the table
        rect(L, foot_top, R - L, TOTAL_H, 0.6, HEAD_BG)
        for xx in xs[1:-1]:
            if xx >= xs[3]:
                line(xx, foot_top, xx, foot_top + TOTAL_H, 0.5)
        ty = foot_top + TOTAL_H / 2 - 7.2 * 0.35
        if is_last:
            txt((xs[0] + xs[3]) / 2, ty, 'TOTAL', 7.4, True, 'center')
            fit_line((xs[3] + xs[4]) / 2, ty, num(total_qty_all), xs[4] - xs[3] - 1.6 * mm, 7.2, 4.5, True, 'center')
            fit_line((xs[5] + xs[6]) / 2, ty, num(total_loading_all), xs[6] - xs[5] - 1.6 * mm, 7.2, 4.5, True, 'center')
            fit_line(R - 1.5 * mm, ty, money2(net_val), xs[7] - xs[6] - 2.5 * mm, 7.4, 4.5, True, 'right')
        else:
            txt((xs[0] + xs[7]) / 2, ty, 'Continued on next page ...', 7.4, True, 'center')

        # ---------- footer ----------
        totals_x = L + 130 * mm
        rect(L, BOTTOM, totals_x - L, FOOT_H, 0.8)
        rect(totals_x, BOTTOM, R - totals_x, FOOT_H, 0.8)
        left_w = totals_x - L

        a_bot = foot_top - 8 * mm
        b_bot = a_bot - 15 * mm
        t_bot = b_bot - 8 * mm
        for yy in (a_bot, b_bot, t_bot):
            line(L, yy, totals_x, yy, 0.5)

        txt(L + 2 * mm, foot_top - 3.5 * mm, 'Amount (in Words) :', 6.8, True)
        if is_last:
            fit_line(L + 29 * mm, foot_top - 3.5 * mm, amount_words(net_val),
                     left_w - 31 * mm, 7, 4.8, True)

        txt(L + 2 * mm, a_bot - 3.4 * mm, 'BANK DETAILS :', 6.8, True)
        txt(L + 27 * mm, a_bot - 3.4 * mm, COMPANY.get('name', ''), 6.8, True)
        bank_lines = [z.strip() for z in str(COMPANY.get('bank', '')).split('\n') if z.strip()]
        for j, bl in enumerate(bank_lines[:3]):
            fit_line(L + 2 * mm, a_bot - (6.8 + j * 2.9) * mm, bl, left_w - 4 * mm, 6.6, 4.8, False)

        txt(L + 2 * mm, b_bot - 3.2 * mm, 'TERMS AND CONDITIONS :', 6.8, True)
        txt(L + 2 * mm, b_bot - 6.4 * mm, '1. CHEQUE RETURN CHARGES RS.200/-', 6.6, False)

        txt(L + left_w / 2, BOTTOM + 1.8 * mm, 'Receiver Signature', 6.8, True, 'center')

        # right: totals (only on the last page)
        rows = [('TOTAL', money2(sub_val)),
                ('DISC.', money2(header.get('discount', 0))),
                ('Freight Chr.', money2(header.get('freight', 0))),
                ('Other Chr.', money2(header.get('other_charges', 0)))]

        rh = 4.3 * mm
        if is_last:
            yy = foot_top
            for lab, val in rows:
                txt(totals_x + 2 * mm, yy - rh / 2 - 2.4, lab, 7, True)
                txt(R - 2 * mm, yy - rh / 2 - 2.4, val, 7, True, 'right')
                yy -= rh
                line(totals_x, yy, R, yy, 0.3, SOFT)
            net_top = foot_top - len(rows) * rh
            net_h = 6 * mm
            rect(totals_x, net_top - net_h, R - totals_x, net_h, 0.8, HEAD_BG)
            txt(totals_x + 2 * mm, net_top - net_h / 2 - 2.8, 'NET TOTAL', 8, True)
            fit_line(R - 2 * mm, net_top - net_h / 2 - 2.8, money2(net_val),
                     R - totals_x - 26 * mm, 8.5, 5, True, 'right')
            sign_top = net_top - net_h
        else:
            txt((totals_x + R) / 2, foot_top - 14 * mm, 'Continued on next page ...', 7, True, 'center')
            sign_top = foot_top - 22 * mm

        fit_line(totals_x + 2 * mm, sign_top - 3.6 * mm, f'For {COMPANY.get("name", "")}',
                 R - totals_x - 4 * mm, 6.8, 5, True)
        txt(R - 2 * mm, BOTTOM + 1.8 * mm, 'Authorized Signature', 6.8, False, 'right')

        c.restoreState()

    # Every copy is identical. Pages of the bill are repeated `copies` times,
    # and 2 copies are packed on one A4 sheet (top + bottom).
    slots = [(pn, pi) for pn, pi in enumerate(chunks, 1) for _ in range(copies)]
    for s_ in range(0, len(slots), 2):
        pair = slots[s_:s_ + 2]
        for k, (pn, pi) in enumerate(pair):
            draw_copy('', HH if k == 0 else 0, pi, pn)
        if len(pair) == 2:
            # cut line in the middle
            c.setStrokeColor(colors.grey); c.setLineWidth(0.4); c.setDash(3, 3)
            c.line(L, HH, R, HH)
            c.setDash()
        c.showPage()

    c.save()
    return path

def make_pdf(doc_type, header, customer, items, path=None, copy_label='ORIGINAL'):
    if doc_type=='quotation':
        return make_quotation_pdf(header, customer, items, path=path)
    if doc_type=='invoice':
        return make_invoice_bill_pdf(header, customer, items, path=path, copy_label=copy_label)
    if doc_type=='challan':
        return make_challan_bill_pdf(header, customer, items, path=path, copy_label=copy_label)
    no=header.get('number','DOC')
    path=path or os.path.join(EXPORT_DIR,f'{doc_type}_{no}_{copy_label}.pdf')
    stamp=generated_stamp()
    styles=getSampleStyleSheet(); normal=styles['BodyText']; normal.fontSize=8; normal.leading=10
    small=styles['BodyText'].clone('Small'); small.fontSize=7; small.leading=8.5
    center=styles['Heading1']; center.alignment=TA_CENTER; center.fontSize=14; center.leading=16
    right=styles['BodyText'].clone('Right'); right.alignment=TA_RIGHT; right.fontSize=8; right.leading=10
    d=SimpleDocTemplate(path,pagesize=A4,leftMargin=7*mm,rightMargin=7*mm,topMargin=7*mm,bottomMargin=7*mm)
    title={'invoice':'TAX INVOICE','challan':'DELIVERY CHALLAN','quotation':'QUOTATION'}.get(doc_type,doc_type.upper())
    story=[]
    scanner_img=image_or_blank(COMPANY.get('scanner_path'),24,24)
    company_lines=f'<b><font size="16">{clean(COMPANY["name"])}</font></b><br/>{clean(COMPANY["address"])}<br/>GSTIN: {clean(COMPANY["gstin"])} | PAN: {clean(COMPANY.get("pan",""))}<br/>Ph: {clean(COMPANY["phone"])} | {clean(COMPANY["email"])}'
    head=Table([
        [Paragraph(company_lines,center),Paragraph(f'<b>{copy_label}</b><br/><br/><font size="13"><b>{title}</b></font>',right),scanner_img]
    ],colWidths=[144*mm,34*mm,18*mm])
    head.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(head)
    info_left=f'<b>Bill To / Party</b><br/>{clean(customer.get("name",""))}<br/>{clean(customer.get("address",""))}<br/>GSTIN: {clean(customer.get("gstin",""))}<br/>State: {clean(customer.get("state",""))}<br/>Contact: {clean(customer.get("contact_no",""))}'
    info_right=f'<b>{title} No:</b> {clean(no)}<br/><b>Date:</b> {clean(header.get("date",""))}<br/><b>Day:</b> {clean(stamp["generated_day"])}<br/><b>Time:</b> {clean(stamp["generated_time"])}<br/><b>Place of Supply:</b> {clean(header.get("place_of_supply",customer.get("state","")))}<br/><b>Email:</b> {clean(customer.get("email",""))}<br/><b>Contact Person:</b> {clean(customer.get("contact_person",""))}'
    info=Table([[Paragraph(info_left,normal),Paragraph(info_right,normal)]],colWidths=[105*mm,91*mm])
    info.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('LINEBEFORE',(1,0),(1,-1),.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(info)
    data=[['Sr','Description of Goods / Services','HSN/SAC','Qty','Unit','Rate','Amount']]
    for i,it in enumerate(items,1): data.append([i,Paragraph(clean(it.get('item_name','')),small),clean(it.get('hsn_sac','')),money(it.get('qty',0)),clean(it.get('unit','')),money(it.get('price',0)),money(it.get('amount',0))])
    while len(data)<12:data.append(['','','','','','',''])
    data.append(['','','','','','Subtotal',money(header.get('subtotal',0))]);data.append(['','','','','','CGST',money(header.get('cgst',0))]);data.append(['','','','','','SGST',money(header.get('sgst',0))])
    if float(header.get('freight',0) or 0): data.append(['','','','','','Freight',money(header.get('freight',0))])
    data.append(['','','','','','Grand Total',money(header.get('total',0))])
    ti=Table(data,colWidths=[10*mm,78*mm,22*mm,18*mm,16*mm,25*mm,27*mm],repeatRows=1)
    ti.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.black),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9EEF5')),('FONT',(0,0),(-1,-1),'Helvetica',7.2),('FONT',(0,0),(-1,0),'Helvetica-Bold',7.5),('ALIGN',(0,0),(0,-1),'CENTER'),('ALIGN',(3,1),(-1,-1),'RIGHT'),('ALIGN',(2,1),(2,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('SPAN',(0,-1),(4,-1)),('FONT',(5,-1),(-1,-1),'Helvetica-Bold',8.5),('BACKGROUND',(5,-1),(-1,-1),colors.HexColor('#F6F7F9'))]))
    story.append(ti)
    story.append(Spacer(1,5))
    story.append(Paragraph('<b>Amount in words:</b> '+clean(amount_words(header.get('total',0))),normal))
    desc=header.get('description') or header.get('notes') or ''
    if desc: story.append(Paragraph('<b>Remarks:</b> '+clean(desc),normal))
    if doc_type=='invoice': story.append(Paragraph(f'<b>Payment Mode:</b> {clean(header.get("payment_mode",""))} &nbsp;&nbsp; <b>Received:</b> {money(header.get("received",0))} &nbsp;&nbsp; <b>Balance:</b> {money(header.get("balance",0))}',normal))
    footer=Table([[Paragraph('<b>Bank Details</b><br/>'+br(COMPANY['bank']),normal),Paragraph('<b>Terms & Conditions</b><br/>Goods once sold will not be taken back.<br/>Subject to local jurisdiction.',small),Paragraph(f'For <b>{clean(COMPANY["name"])}</b><br/><br/>Authorized Signatory<br/><font size="6">Generated: {stamp["generated_date"]}<br/>{stamp["generated_day"]} | {stamp["generated_time"]}</font>',normal)]],colWidths=[68*mm,62*mm,66*mm])
    footer.setStyle(TableStyle([('BOX',(0,0),(-1,-1),.8,colors.black),('LINEBEFORE',(1,0),(-1,-1),.35,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(2,0),(2,0),'CENTER'),('PADDING',(0,0),(-1,-1),6)]))
    story.append(footer)
    d.build(story);return path

def make_report_pdf(title, columns, rows, path):
    styles=getSampleStyleSheet(); normal=styles['BodyText']; normal.fontSize=7; normal.leading=9
    center=styles['Heading1']; center.alignment=TA_CENTER; center.fontSize=14
    d=SimpleDocTemplate(path,pagesize=A4,leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=8*mm)
    story=[Paragraph(f'<b>{COMPANY["name"]}</b>',center),Paragraph(f'<b>{title}</b>',center),Spacer(1,6)]
    data=[columns]+[[str(r.get(c,'')) for c in columns] for r in rows]
    widths=[(194/len(columns))*mm for _ in columns]
    table=Table(data,colWidths=widths,repeatRows=1)
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONT',(0,0),(-1,-1),'Helvetica',6.5),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(table);d.build(story);return path