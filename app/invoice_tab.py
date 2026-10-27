import csv, os, shutil, re, tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date, datetime
from database import conn, next_number
from config import DEFAULT_GST_RATE, COMPANY
from services.pdf_service import make_pdf
from services.send_service import open_whatsapp, send_email_or_compose
from app.document_editor import DocEditor
# NEW: Customer Master / Product Master  forms (shared file)
from app.master_popups import open_customer_form, open_product_form


# Keys that must NOT re-run the search while typing (navigation keys)
_NAV_KEYS = ('Return', 'Tab', 'Up', 'Down', 'Left', 'Right', 'Escape',
             'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
             'Caps_Lock', 'Home', 'End')


def _search_names(names, typed):
    """Names STARTING with the typed text come first, then names that merely
    CONTAIN it (case-insensitive). Empty text = the full sorted list."""
    typed = (typed or '').strip().lower()
    names = [str(n) for n in names if str(n).strip()]
    if not typed:
        return sorted(names, key=str.lower)
    starts = [n for n in names if n.lower().startswith(typed)]
    contains = [n for n in names if typed in n.lower() and not n.lower().startswith(typed)]
    return sorted(starts, key=str.lower) + sorted(contains, key=str.lower)


class _SuggestPopup:
    """Small list that appears right under a Combobox WHILE the person is
    typing, showing the matching names. Focus stays in the box, so typing
    is never interrupted. Click a name (or use Up/Down + Enter) to pick it."""
    MAX_ROWS = 8

    def __init__(self, combo, get_matches, on_pick):
        self.combo = combo
        self.get_matches = get_matches   # () -> list of matching keys
        self.on_pick = on_pick           # (key) -> None
        self.top = None
        self.lb = None
        self._hide_job = None
        combo.bind('<Down>', self._on_down, add='+')
        combo.bind('<Up>', self._on_up, add='+')
        combo.bind('<Return>', self._on_return, add='+')
        combo.bind('<Escape>', lambda e: self.hide(), add='+')
        combo.bind('<FocusOut>', lambda e: self._schedule_hide(), add='+')
        combo.bind('<Destroy>', lambda e: self.hide(), add='+')

    def refresh(self):
        try:
            matches = self.get_matches()
        except Exception:
            matches = []
        if not matches:
            self.hide()
            return
        self._build(matches)

    def visible(self):
        return self.top is not None and self.lb is not None

    def _build(self, matches):
        self.hide()
        try:
            top = tk.Toplevel(self.combo)
            top.wm_overrideredirect(True)
            try:
                top.attributes('-topmost', True)
            except Exception:
                pass
            frame = tk.Frame(top, borderwidth=1, relief='solid')
            frame.pack(fill='both', expand=True)
            rows = min(len(matches), self.MAX_ROWS)
            lb = tk.Listbox(frame, height=rows, width=1, activestyle='none',
                            exportselection=False, takefocus=0)
            if len(matches) > rows:
                sb = ttk.Scrollbar(frame, orient='vertical', command=lb.yview)
                lb.configure(yscrollcommand=sb.set)
                sb.pack(side='right', fill='y')
            lb.pack(side='left', fill='both', expand=True)
            for m in matches:
                lb.insert('end', m)
            lb.bind('<ButtonPress-1>', self._on_click)
            top.update_idletasks()
            x = self.combo.winfo_rootx()
            y = self.combo.winfo_rooty() + self.combo.winfo_height()
            w = max(self.combo.winfo_width(), 320)
            h = lb.winfo_reqheight() + 4
            top.geometry(f'{w}x{h}+{x}+{y}')
            self.top, self.lb = top, lb
        except Exception:
            self.hide()

    def hide(self):
        if self._hide_job is not None:
            try:
                self.combo.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self.lb = None

    def _schedule_hide(self):
        # small delay so a click on the list is still received
        try:
            self._hide_job = self.combo.after(200, self.hide)
        except Exception:
            self.hide()

    def _pick(self, key):
        self.hide()
        try:
            self.on_pick(key)
        except Exception:
            pass

    def _on_click(self, event):
        if not self.visible():
            return 'break'
        try:
            i = self.lb.nearest(event.y)
            self._pick(self.lb.get(i))
        except Exception:
            self.hide()
        return 'break'

    def _on_down(self, event=None):
        if not self.visible():
            return None
        cur = self.lb.curselection()
        i = 0 if not cur else min(cur[0] + 1, self.lb.size() - 1)
        self.lb.selection_clear(0, 'end')
        self.lb.selection_set(i)
        self.lb.see(i)
        return 'break'

    def _on_up(self, event=None):
        if not self.visible():
            return None
        cur = self.lb.curselection()
        if cur:
            i = max(cur[0] - 1, 0)
            self.lb.selection_clear(0, 'end')
            self.lb.selection_set(i)
            self.lb.see(i)
        return 'break'

    def _on_return(self, event=None):
        if self.visible():
            cur = self.lb.curselection()
            if cur:
                self._pick(self.lb.get(cur[0]))
                return 'break'
            self.hide()
        return None



class InvoiceTab(ttk.Frame):
    # Saved Invoices table kept to just the essentials so every column has
    # room to breathe instead of 17+ columns squeezing into unreadable
    # 1-2 letter headers.
    ILIST_COLS=[('number','Bill No.'),('date','Date'),
                ('item','Item'),('material','Material'),('hsn','HSN'),('qty','Qty'),('rate','Rate'),
                ('loading','Loading'),('customer','Customer'),('payment_mode','Payment Mode'),('vehicle','Vehicle'),
                ('total','Total'),('gstin','GSTIN'),('format','Format')]
    ILIST_ACTIONS=[('dl','Download'),('print','Print'),('edit','Edit'),('delete','Delete')]
    # Allowed Payment Mode values (dropdown)
    PAYMENT_MODES=('Cash','Credit','NEFT')
    # Allowed GST Type values (dropdown): same state = CGST+SGST, other state = IGST
    TAX_TYPES=('CGST+SGST','IGST')
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.selected=[];self.last_invoice_pdf='';self.last_invoice=None;self.invoice_map={};self.customer_map={};self.customer_by_name={};self.product_by_name={};self.customer=tk.StringVar();self.existing_invoice=tk.StringVar();self.ilist_invoice_of={};self.ilist_item_of={};self.gst_mode=tk.StringVar(value='GST')
        # 'Saved Invoices' 
        self.editing_invoice_item_id=None
        # NEW: shevatcha save kelela invoice id (Print/WhatsApp/Email sathi vaparto)
        self.last_saved_id=None
        # Godown-name -> global godowns.id. Customer and Godown are separate
        # masters; only Godown -> Product is fixed.
        self.godown_id_map={}
        self._ensure_customer_columns();self._ensure_invoice_gst_column();self._ensure_invoice_extra_columns();self._ensure_godown_products_table();self._ensure_product_names_table();self._ensure_invoice_settled_column();self._ensure_invoice_tax_type_column()
        self.build();self.load_customers();self.load_products();self.load_invoices()
    def _ensure_invoice_extra_columns(self):
        with conn() as c:
            icols=[r['name'] for r in c.execute('PRAGMA table_info(invoices)')]
            if 'discount' not in icols:c.execute("ALTER TABLE invoices ADD COLUMN discount REAL DEFAULT 0")
            if 'other_charges' not in icols:c.execute("ALTER TABLE invoices ADD COLUMN other_charges REAL DEFAULT 0")
            if 'payment_mode' not in icols:c.execute("ALTER TABLE invoices ADD COLUMN payment_mode TEXT")
            if 'vehicle' not in icols:c.execute("ALTER TABLE invoices ADD COLUMN vehicle TEXT")
            iicols=[r['name'] for r in c.execute('PRAGMA table_info(invoice_items)')]
            if 'loading' not in iicols:c.execute("ALTER TABLE invoice_items ADD COLUMN loading REAL DEFAULT 0")
            # NEW: free-text "Material" (Maal) for each item
            if 'material' not in iicols:c.execute("ALTER TABLE invoice_items ADD COLUMN material TEXT")
            if 'date' not in iicols:
                c.execute("ALTER TABLE invoice_items ADD COLUMN date TEXT")
                # Backfill: juna items na parent invoice chi date dya, itihaas rikama rahu naye
                c.execute('''UPDATE invoice_items
                             SET date=(SELECT date FROM invoices WHERE invoices.id=invoice_items.invoice_id)
                             WHERE date IS NULL''')
    def _vehicle_names(self):
        # Previously used vehicle names (Invoices + Challans) for the dropdown.
        names=set()
        try:
            with conn() as c:
                for tbl in ('invoices','challans'):
                    try:
                        for r in c.execute(f"SELECT DISTINCT TRIM(vehicle) FROM {tbl} WHERE vehicle IS NOT NULL AND TRIM(vehicle)!=''"):
                            names.add(r[0])
                    except Exception:
                        pass
        except Exception:
            pass
        return sorted(names,key=str.lower)
    def _ensure_invoice_gst_column(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(invoices)')]
            if 'gst_mode' not in cols:
                c.execute("ALTER TABLE invoices ADD COLUMN gst_mode TEXT DEFAULT 'GST'")
    def _ensure_invoice_settled_column(self):
        # 'settled' marks an invoice as "already applied/saved" from the
        # Customer Statement window (Apply Payment Mode button). A settled
        # invoice's rows there get LOCKED. Editing/saving the invoice again
        # (save_manual_invoice / update_loaded_invoice) resets this to 0.
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(invoices)')]
            if 'settled' not in cols:
                c.execute("ALTER TABLE invoices ADD COLUMN settled INTEGER DEFAULT 0")
    def _ensure_invoice_tax_type_column(self):
        # 'CGST+SGST' (same state) kinva 'IGST' (different state)
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(invoices)')]
            if 'tax_type' not in cols:
                c.execute("ALTER TABLE invoices ADD COLUMN tax_type TEXT DEFAULT 'CGST+SGST'")
    def _ensure_customer_columns(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(customers)')]
            for col in ('district','pincode','phone_no'):
                if col not in cols:
                    c.execute(f'ALTER TABLE customers ADD COLUMN {col} TEXT')
    def _ensure_godown_products_table(self):
        with conn() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS godowns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS godown_products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                godown_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                UNIQUE(godown_id, product_id),
                FOREIGN KEY(godown_id) REFERENCES godowns(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )''')
    # Product Description chi permanent yadi. Invoice delete kela tari
    # product naave delete hot nahit. Juney invoices madhle naave pan ithe copy hotat.
    def _ensure_product_names_table(self):
        with conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS product_names(name TEXT PRIMARY KEY COLLATE NOCASE)')
            c.execute("INSERT OR IGNORE INTO product_names(name) "
                      "SELECT DISTINCT TRIM(item_name) FROM invoice_items "
                      "WHERE item_name IS NOT NULL AND TRIM(item_name)!=''")
    def _remember_product_name(self, c, name):
        name=str(name or '').strip()
        if name:
            c.execute('INSERT OR IGNORE INTO product_names(name) VALUES(?)',(name,))
    def next_format_bill_no(self, mode):
        prefix = 'GST' if str(mode).upper() == 'GST' else 'NO_GST'
        with conn() as c:
            rows = c.execute('SELECT number,gst_mode FROM invoices').fetchall()
        nums_this_format = []
        all_numbers = set()
        for r in rows:
            num_text = str(r['number'] or '').strip()
            if num_text:
                all_numbers.add(num_text)
            if str(r['gst_mode'] or 'GST').upper() != prefix:
                continue
            m = re.search(r'(\d+)\s*$', num_text)
            if m:
                nums_this_format.append(int(m.group(1)))
        candidate = max(nums_this_format, default=0) + 1
        while str(candidate) in all_numbers:
            candidate += 1
        return str(candidate)

    def _unique_invoice_number(self, number, exclude_id=None):
        number = str(number).strip()
        if not number:
            return number
        with conn() as c:
            if exclude_id:
                rows = c.execute('SELECT number FROM invoices WHERE id != ?', (exclude_id,)).fetchall()
            else:
                rows = c.execute('SELECT number FROM invoices').fetchall()
        existing = {str(r['number'] or '').strip() for r in rows}
        if number not in existing:
            return number
        m = re.match(r'^(.*?)(\d+)$', number)
        if m:
            base, digits = m.group(1), m.group(2)
            width = len(digits)
            n = int(digits)
            while True:
                n += 1
                candidate = f'{base}{str(n).zfill(width)}'
                if candidate not in existing:
                    return candidate
        suffix = 2
        while f'{number}-{suffix}' in existing:
            suffix += 1
        return f'{number}-{suffix}'

    # Jar tyach Bill No. var tach Customer chi aadhichi invoice DB madhe
    # asel, tar navin invoice na banavta junyach invoice madhye item add karnyasathi
    # (merge) ti invoice shodhun ticha id parat karte. Customer vegla asel tar None.
    def _find_matching_invoice(self, number, customer_name, exclude_id=None):
        number = str(number or '').strip()
        customer_name = str(customer_name or '').strip()
        if not number or not customer_name:
            return None
        with conn() as c:
            if exclude_id:
                row = c.execute(
                    'SELECT i.id FROM invoices i JOIN customers c ON c.id=i.customer_id '
                    'WHERE i.number=? AND lower(c.name)=lower(?) AND i.id!=? LIMIT 1',
                    (number, customer_name, exclude_id)
                ).fetchone()
            else:
                row = c.execute(
                    'SELECT i.id FROM invoices i JOIN customers c ON c.id=i.customer_id '
                    'WHERE i.number=? AND lower(c.name)=lower(?) LIMIT 1',
                    (number, customer_name)
                ).fetchone()
        return row['id'] if row else None

    def set_invoice_format(self, mode):
        mode = 'GST' if str(mode).upper() == 'GST' else 'NO_GST'
        old_mode = (self.gst_mode.get() or 'GST').upper()
        self.gst_mode.set(mode)
        if not self.last_invoice or not self.last_invoice.get('id'):
            self.inv_no.set(self.next_format_bill_no(mode))
        self._apply_gst_visibility()
        if self.current_items():
            items = self.current_items()
            self.last_invoice = {
                'header': self.manual_header(items),
                'customer': self.manual_customer(),
                'items': items,
                'id': (self.last_invoice or {}).get('id')
            }
            self.show_invoice_items(items)

    def _sync_format_buttons(self):
        if not hasattr(self, 'gst_format_btn'):
            return
        self.gst_format_btn.configure(text='GST')
        self.no_gst_format_btn.configure(text='WITHOUT GST')

    def _apply_gst_visibility(self):
        show_gst=(self.gst_mode.get() or 'GST').upper()=='GST'
        for w in getattr(self, '_gst_only_widgets', []):
            if show_gst:
                w.grid()
            else:
                w.grid_remove()
        self._sync_format_buttons()

    # Invoice save zalyavar aapoaap NAVIN invoice suru karto.
    # Navin Bill No. yeto, items/amount/discount/freight/other/received/notes
    # rikame hotat. Customer, Godown, GST format, GST Type ani Payment Mode tasech rahtat.
    def _start_fresh_invoice(self):
        mode=(self.gst_mode.get() or 'GST').upper()
        self.last_invoice=None;self.last_invoice_pdf=''
        self.editing_invoice_item_id=None;self._set_item_edit_status('')
        self.inv_no.set(self.next_format_bill_no(mode))
        self.inv_date.set(datetime.now().strftime('%d-%m-%Y'))
        self.inv_time.set(datetime.now().strftime('%I:%M %p'))
        self.inv_discount.set('0');self.inv_freight.set('0');self.inv_other.set('0');self.inv_notes.set('');self.received.set('0');self.inv_vehicle.set('')
        self.item_name.set('');self.item_material.set('');self.item_hsn.set('');self.item_qty.set('1');self.item_unit.set('Nos');self.item_loading.set('0');self.item_price.set('0');self.item_weight.set('0')
        self.show_invoice_items([])

    # Save nantar form 'navin invoice' state madhe asto (last_invoice nahi).
    # Print / WhatsApp / Email sathi shevatcha saved invoice load karto.
    # True = load kela (kaam zalyavar _start_fresh_invoice() parat kara).
    def _load_latest_saved_for_send(self):
        if self.last_invoice and self.last_invoice_pdf:
            return False
        iid=self.last_saved_id or self.invoice_map.get(self.existing_invoice.get())
        if not iid:
            try:
                with conn() as c:
                    row=c.execute('SELECT id FROM invoices ORDER BY id DESC LIMIT 1').fetchone()
                    iid=row['id'] if row else None
            except Exception:
                iid=None
        if not iid:
            return False
        self.load_invoice_by_id(iid, silent=True)
        return True

    def build(self):
        # --- Scrollable wrapper so long content is never hidden ---
        outer = tk.Frame(self, bg=self.app.COLORS['page'])
        outer.pack(fill='both', expand=True)

        canvas = tk.Canvas(
            outer,
            bg=self.app.COLORS['page'],
            highlightthickness=0
        )
        vscroll = ttk.Scrollbar(
            outer,
            orient='vertical',
            command=canvas.yview
        )
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')

        page = tk.Frame(
            canvas,
            bg=self.app.COLORS['page']
        )
        page_window = canvas.create_window(
            (0, 0),
            window=page,
            anchor='nw'
        )

        def _on_page_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        page.bind('<Configure>', _on_page_configure)

        def _on_canvas_configure(event):
            # keep the inner page the same width as the visible canvas
            canvas.itemconfig(page_window, width=event.width)

        canvas.bind('<Configure>', _on_canvas_configure)

        def _on_mousewheel(event):
            delta = -1 * (event.delta // 120) if event.delta else 0
            if delta == 0:
                delta = -1 if getattr(event, 'num', None) == 4 else 1
            canvas.yview_scroll(delta, 'units')

        def _bind_mousewheel(_):
            canvas.bind_all('<MouseWheel>', _on_mousewheel)
            canvas.bind_all('<Button-4>', _on_mousewheel)
            canvas.bind_all('<Button-5>', _on_mousewheel)

        def _unbind_mousewheel(_):
            canvas.unbind_all('<MouseWheel>')
            canvas.unbind_all('<Button-4>')
            canvas.unbind_all('<Button-5>')

        canvas.bind('<Enter>', _bind_mousewheel)
        canvas.bind('<Leave>', _unbind_mousewheel)

        # Keep the existing Invoice UI code unchanged below.
        # `container` points to the same `page` used by the requested
        # scrolling function.
        container = page

        form=ttk.LabelFrame(container,text='Fill Invoice Data');form.pack(fill='x',padx=8,pady=6)
        # Payment Mode (Cash / Credit / NEFT) - used by the dropdown in the form below
        self.mode=tk.StringVar(value='Cash')
        self._gst_only_widgets=[];self.inv_no=tk.StringVar(value=self.next_format_bill_no('GST'));self.inv_date=tk.StringVar(value=datetime.now().strftime('%d-%m-%Y'));self.inv_day=tk.StringVar();self.inv_time=tk.StringVar(value=datetime.now().strftime('%I:%M %p'));self.cust_name=tk.StringVar();self.cust_total=tk.StringVar(value='0.00');self.today_total=tk.StringVar(value='0.00');self.cust_addr=tk.StringVar();self.cust_phone=tk.StringVar();self.cust_email=tk.StringVar();self.cust_state=tk.StringVar(value=COMPANY.get('state','Maharashtra'));self.cust_godown=tk.StringVar();self.cust_godown_values=[];self.cust_gstin=tk.StringVar();self.cust_person=tk.StringVar();self.cust_district=tk.StringVar();self.cust_pincode=tk.StringVar();self.cust_phone_no=tk.StringVar();self.inv_gst=tk.StringVar(value=str(DEFAULT_GST_RATE));self.inv_freight=tk.StringVar(value='0');self.inv_discount=tk.StringVar(value='0');self.inv_other=tk.StringVar(value='0');self.inv_notes=tk.StringVar();self.tax_type=tk.StringVar(value='CGST+SGST');self.inv_vehicle=tk.StringVar()
        # NOTE: Address/Phone/Email/State/District/PinCode/GSTIN/ContactPerson/PhoneNo
        # 
        fields=[('Bill No.',self.inv_no,14),('Date',self.inv_date,12),('Day',self.inv_day,12),('Time',self.inv_time,12),
                ('Customer Name',self.cust_name,24),('Customer GSTIN',self.cust_gstin,22),('GST %',self.inv_gst,8),
                ('Other Chr.',self.inv_other,9),('Notes',self.inv_notes,24),('Payment Mode',self.mode,14),('GST Type',self.tax_type,14),('Vehicle (optional)',self.inv_vehicle,22)]
        for i,(lab,var,w) in enumerate(fields):
            r=(i//4)*2;c=i%4
            lab_widget=ttk.Label(form,text=lab)
            lab_widget.grid(row=r,column=c,padx=4,sticky='w')
            if lab=='Godown':
                cell=ttk.Frame(form)
                self.cust_godown_cb=ttk.Combobox(cell,textvariable=var,width=w-5,state='readonly')
                self.cust_godown_cb.pack(side='left')
                # Godown 
                ttk.Button(cell,text='+',width=2,command=self.add_new_godown).pack(side='left',padx=(4,0))
                cell.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
                continue
            if lab=='Customer Name':
                cell=ttk.Frame(form)
                self.cust_name_cb=ttk.Combobox(cell,textvariable=var,width=w-5,state='normal')
                self.cust_name_cb.pack(side='left')
                self.cust_name_cb.bind('<<ComboboxSelected>>',self.on_customer_name_selected)
                self.cust_name_cb.bind('<KeyRelease>',self.filter_customers)
                self.cust_name_cb.bind('<FocusIn>',self.refresh_customer_dropdown)
                # live suggestion list under the box while typing
                self._cust_popup=_SuggestPopup(self.cust_name_cb,self._customer_matches,self._pick_customer_from_popup)
                # "+" -> Customer Master 
                ttk.Button(cell,text='+',width=2,command=self.add_customer_popup).pack(side='left',padx=(4,0))
                # Customer 
                ttk.Label(cell,text='  Customer Total:').pack(side='left',padx=(8,2))
                ttk.Entry(cell,textvariable=self.cust_total,width=13,state='readonly').pack(side='left')
                # Today Total - selected customer's invoice items of TODAY
                ttk.Label(cell,text='  Today Total:').pack(side='left',padx=(8,2))
                ttk.Entry(cell,textvariable=self.today_total,width=13,state='readonly').pack(side='left')
                cell.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
                continue
            if lab=='Vehicle (optional)':
                self.vehicle_cb=ttk.Combobox(form,textvariable=var,values=self._vehicle_names(),width=w,state='normal')
                self.vehicle_cb.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
                self.vehicle_cb.bind('<FocusIn>',lambda e:self.vehicle_cb.configure(values=self._vehicle_names()))
                continue
            if lab=='Payment Mode':
                self.pay_mode_cb=ttk.Combobox(form,textvariable=var,values=self.PAYMENT_MODES,width=w,state='readonly')
                self.pay_mode_cb.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
                continue
            if lab=='GST Type':
                # CGST+SGST (same state) / IGST (different state)
                self.tax_type_cb=ttk.Combobox(form,textvariable=var,values=self.TAX_TYPES,width=w,state='readonly')
                self.tax_type_cb.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
                # WITHOUT GST madhye hide hoto
                self._gst_only_widgets.extend([lab_widget,self.tax_type_cb])
                continue
            state='readonly' if lab in ('Day','Time') else 'normal'
            ent=ttk.Entry(form,textvariable=var,width=w,state=state)
            ent.grid(row=r+1,column=c,padx=4,pady=3,sticky='w')
            if lab in ('GST %','Customer GSTIN'):
                self._gst_only_widgets.extend([lab_widget,ent])
        self.inv_date.trace_add('write',self._update_day)
        self._update_day()
        gstf=ttk.LabelFrame(container,text='Invoice Format')
        gstf.pack(fill='x',padx=8,pady=4)
        ttk.Label(gstf,text='Invoice Format:').pack(side='left',padx=(6,4),pady=6)
        self.gst_format_btn=ttk.Button(
            gstf,text='GST',
            command=lambda:self.set_invoice_format('GST')
        )
        self.gst_format_btn.pack(side='left',padx=5,pady=5)
        self.no_gst_format_btn=ttk.Button(
            gstf,text='WITHOUT GST',
            command=lambda:self.set_invoice_format('NO_GST')
        )
        self.no_gst_format_btn.pack(side='left',padx=5,pady=5)
        ttk.Label(
            gstf,text='Select GST or WITHOUT GST. Each format has its own Bill No. sequence.'
        ).pack(side='left',padx=8,pady=6)
        itemf=ttk.LabelFrame(container,text='Fill Material / Item');itemf.pack(fill='x',padx=8,pady=6)
        
        self.item_name=tk.StringVar();self.item_material=tk.StringVar();self.item_hsn=tk.StringVar();self.item_qty=tk.StringVar(value='1');self.item_unit=tk.StringVar(value='Nos');self.item_loading=tk.StringVar(value='0');self.item_price=tk.StringVar(value='0');self.item_weight=tk.StringVar(value='0');self.item_total=tk.StringVar(value='0.00')
        
        self.item_edit_status=tk.StringVar(value='')
        for i,(lab,var,w) in enumerate([('Product Description',self.item_name,28),('Material',self.item_material,18),('HSN/SAC',self.item_hsn,12),('Qty',self.item_qty,8),('Rate',self.item_price,10),('Loading',self.item_loading,9),('Total',self.item_total,10)]):
            ttk.Label(itemf,text=lab).grid(row=0,column=i,padx=4,sticky='w')
            if lab=='Product Description':
                cell=ttk.Frame(itemf)
                self.item_name_cb=ttk.Combobox(cell,textvariable=var,width=w-5)
                self.item_name_cb.pack(side='left')
                self.item_name_cb.bind('<<ComboboxSelected>>',self.on_item_name_selected)
                self.item_name_cb.bind('<KeyRelease>',self.filter_products)
                self.item_name_cb.bind('<FocusIn>',self.refresh_product_dropdown)
              
                self.item_name_cb.bind('<FocusOut>',self._add_typed_product_to_dropdown)
                # live suggestion list under the box while typing
                self._item_popup=_SuggestPopup(self.item_name_cb,self._product_matches,self._pick_product_from_popup)
                
                ttk.Button(cell,text='+',width=2,command=self.add_new_product_quick).pack(side='left',padx=(4,0))
                cell.grid(row=1,column=i,padx=4,pady=3)
                continue
            if lab=='Total':
                
                ttk.Entry(itemf,textvariable=var,width=w,state='readonly').grid(row=1,column=i,padx=4,pady=3)
                continue
            ttk.Entry(itemf,textvariable=var,width=w).grid(row=1,column=i,padx=4,pady=3)
        self.item_add_btn=ttk.Button(itemf,text='ADD (Save Item + Invoice)',command=self.save_manual_invoice)
        self.item_add_btn.grid(row=1,column=7,padx=5)
        ttk.Button(itemf,text='Remove Item',command=self.remove_manual_item).grid(row=1,column=8,padx=5)
        ttk.Button(itemf,text='Cancel Edit Item',command=self.cancel_item_edit).grid(row=1,column=9,padx=5)
        self.invoice_items_lbl=ttk.Label(itemf,text='Items: 0 | Total: 0.00',font=('Segoe UI',9,'bold'));self.invoice_items_lbl.grid(row=0,column=10,rowspan=2,padx=8)
        # Qty / Rate / Loading 
        self.item_qty.trace_add('write',self._update_item_total)
        self.item_price.trace_add('write',self._update_item_total)
        self.item_loading.trace_add('write',self._update_item_total)
        # ---- Godown -> Item dropdown filter ----
        self.cust_godown.trace_add('write', self._on_godown_changed)
        self._on_godown_changed()
        sendbar=ttk.LabelFrame(container,text='Print / WhatsApp / Email')
        sendbar.pack(fill='x',padx=8,pady=4)
        ttk.Button(sendbar,text='Print',command=self.print_current).pack(side='left',padx=6,pady=6)
        ttk.Button(sendbar,text='WhatsApp',command=self.whatsapp_current).pack(side='left',padx=6,pady=6)
        ttk.Button(sendbar,text='Email',command=self.email_current).pack(side='left',padx=6,pady=6)
        # ---- Customer Statement: pick a customer, see all their invoices,
        # select any number of them, see the total of what's selected. ----
        stmt_bar=ttk.Frame(container)
        stmt_bar.pack(fill='x',padx=8,pady=(0,4))
        ttk.Button(stmt_bar,text='📄 Customer Statement',command=self.open_customer_statement).pack(side='left')
        listf=ttk.LabelFrame(container,text='Saved Invoices')
        listf.pack(fill='both',expand=True,padx=8,pady=(4,6))
        self.icols=[k for k,_ in self.ILIST_COLS]+[k for k,_ in self.ILIST_ACTIONS]

        # Saved Invoices table: vertical + horizontal scrollbars, and mouse
        # wheel scrolling bound directly to the table.
        table_area = ttk.Frame(listf)
        table_area.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        self.ilist=ttk.Treeview(table_area,columns=self.icols,show='headings',height=10)
        ILIST_WIDTHS={
            'number':95,'date':95,'item':210,'material':140,'hsn':105,'qty':65,
            'rate':85,'loading':85,'customer':170,'payment_mode':115,'vehicle':120,'total':105,'gstin':180,'format':105
        }
        for k,l in self.ILIST_COLS:
            self.ilist.heading(k,text=l)
            self.ilist.column(k,width=ILIST_WIDTHS.get(k,100),anchor='center' if k in ('number','date','hsn','qty','rate','loading','payment_mode','format') else 'w',stretch=False)
        for k,l in self.ILIST_ACTIONS:
            self.ilist.heading(k,text=l)
            self.ilist.column(k,width=88,anchor='center',stretch=False)

        # RIGHT vertical scrollbar
        yscroll=ttk.Scrollbar(table_area,orient='vertical',command=self.ilist.yview)
        self.ilist.configure(yscrollcommand=yscroll.set)

        # BOTTOM horizontal scrollbar
        xscroll=ttk.Scrollbar(listf,orient='horizontal',command=self.ilist.xview)
        self.ilist.configure(xscrollcommand=xscroll.set)

        # IMPORTANT: pack the vertical scrollbar FIRST, otherwise the wide
        # table squeezes it out (invisible).
        yscroll.pack(side='right',fill='y')
        self.ilist.pack(side='left',fill='both',expand=True)
        xscroll.pack(fill='x',padx=6,pady=(0,6))

        # Mouse wheel scrolling - bound directly to the table itself, so
        # while the pointer is over the Saved Invoices table it scrolls
        # THIS table (not the whole page behind it).
        def _on_ilist_vwheel(event):
            num=getattr(event,'num',None)
            if num==4:
                self.ilist.yview_scroll(-1,'units')
            elif num==5:
                self.ilist.yview_scroll(1,'units')
            else:
                self.ilist.yview_scroll(-1 if getattr(event,'delta',0)>0 else 1,'units')
            return 'break'

        def _on_ilist_hwheel(event):
            num=getattr(event,'num',None)
            if num==4:
                self.ilist.xview_scroll(-1,'units')
            elif num==5:
                self.ilist.xview_scroll(1,'units')
            else:
                self.ilist.xview_scroll(-1 if getattr(event,'delta',0)>0 else 1,'units')
            return 'break'

        self.ilist.bind('<MouseWheel>',_on_ilist_vwheel)
        self.ilist.bind('<Button-4>',_on_ilist_vwheel)
        self.ilist.bind('<Button-5>',_on_ilist_vwheel)
        self.ilist.bind('<Shift-MouseWheel>',_on_ilist_hwheel)
        self.ilist.bind('<Shift-Button-4>',_on_ilist_hwheel)
        self.ilist.bind('<Shift-Button-5>',_on_ilist_hwheel)

        self.ilist.bind('<Button-1>',self.on_ilist_click)
        b=ttk.Frame(container);b.pack(fill='x',padx=8,pady=6);self.received=tk.StringVar(value='0')
        ttk.Label(b,text='Received').pack(side='left');ttk.Entry(b,textvariable=self.received,width=12).pack(side='left',padx=5)
        self._apply_gst_visibility()
        ttk.Button(b,text='Import CSV Invoice',command=self.import_csv_invoice).pack(side='left',padx=4);ttk.Button(b,text='Save PDF As',command=self.save_pdf_as).pack(side='left',padx=4);ttk.Button(b,text='Refresh',command=self.refresh_all).pack(side='left')
    def _update_item_total(self,*args):
        # Product entry row
        try:
            qty=float(self.item_qty.get() or 0);price=float(self.item_price.get() or 0);loading=float(self.item_loading.get() or 0)
            self.item_total.set(f'{qty*price+loading:,.2f}')
        except Exception:
            self.item_total.set('0.00')
    def _update_day(self,*args):
        ds=self.inv_date.get().strip();day=''
        for fmt in ('%d-%m-%Y','%Y-%m-%d','%d/%m/%Y'):
            try:day=datetime.strptime(ds,fmt).strftime('%A');break
            except Exception:continue
        self.inv_day.set(day)

    # ---------- Type-to-search: Customer ----------
    def refresh_customer_dropdown(self, event=None):
        self.load_customers()
        if hasattr(self, 'cust_name_cb'):
            self.cust_name_cb['values'] = sorted(self.customer_by_name)

    def filter_customers(self, event=None):
        if not hasattr(self, 'cust_name_cb'):
            return
        if event is not None and getattr(event, 'keysym', '') in _NAV_KEYS:
            return
        typed = self.cust_name.get().strip()
        self.cust_name_cb['values'] = _search_names(self.customer_by_name, typed)
        pp = getattr(self, '_cust_popup', None)
        if pp is not None:
            pp.refresh()

    def _customer_matches(self):
        typed = self.cust_name.get().strip()
        if not typed or typed in self.customer_by_name:
            return []
        return _search_names(self.customer_by_name, typed)

    def _pick_customer_from_popup(self, name):
        self.cust_name.set(name)
        if hasattr(self, 'cust_name_cb'):
            self.cust_name_cb['values'] = sorted(self.customer_by_name)
        self.on_customer_name_selected()

    # ---------- Type-to-search: Product ----------
    def refresh_product_dropdown(self, event=None):
        if hasattr(self, 'item_name_cb'):
            self.item_name_cb['values'] = self._godown_filtered_product_names()

    def filter_products(self, event=None):
        if not hasattr(self, 'item_name_cb'):
            return
        if event is not None and getattr(event, 'keysym', '') in _NAV_KEYS:
            return
        typed = self.item_name.get().strip()
        self.item_name_cb['values'] = _search_names(self._godown_filtered_product_names(), typed)
        pp = getattr(self, '_item_popup', None)
        if pp is not None:
            pp.refresh()

    def _product_matches(self):
        typed = self.item_name.get().strip()
        if not typed:
            return []
        names = self._godown_filtered_product_names()
        if typed in names:
            return []
        return _search_names(names, typed)

    def _pick_product_from_popup(self, name):
        self.item_name.set(name)
        if hasattr(self, 'item_name_cb'):
            self.item_name_cb['values'] = self._godown_filtered_product_names()
        self.on_item_name_selected()

    def _godown_filtered_product_names(self):
        
        with conn() as c:
            rows = c.execute(
                "SELECT name FROM product_names "
                "UNION SELECT TRIM(item_name) FROM invoice_items "
                "WHERE item_name IS NOT NULL AND TRIM(item_name)!='' ORDER BY 1"
            ).fetchall()
        return [r[0] for r in rows]

    def _on_godown_changed(self, *args):
        
        if hasattr(self, 'item_name_cb'):
            self.item_name_cb['values'] = self._godown_filtered_product_names()

    def _all_godowns(self):
        with conn() as c:
            rows=c.execute('SELECT id,name FROM godowns ORDER BY name').fetchall()
        self.godown_id_map={r['name']:r['id'] for r in rows}
        return [r['name'] for r in rows]

    def add_new_godown(self):
        name=simpledialog.askstring('Add Godown','Enter Godown name:',parent=self)
        if not name:return
        name=name.strip()
        if not name:return
        with conn() as c:
            c.execute('INSERT OR IGNORE INTO godowns(name) VALUES(?)',(name,))
        vals=self._all_godowns()
        self.cust_godown_cb['values']=vals
        self.cust_godown.set(name)

    # ---------- "+" Customer: Customer Master  form ----------
    def add_customer_popup(self):
        open_customer_form(self, on_saved=self._after_customer_saved)

    def _after_customer_saved(self, name):
        self.load_customers()
        self.cust_name.set(name)
        self.on_customer_name_selected()

    # ---------- "+" Product:  add ----------
    def add_new_product_quick(self):
        
        name = simpledialog.askstring('Add Product', 'Enter Product Name:', parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.item_name.set(name)
        with conn() as c:
            self._remember_product_name(c, name)
        if hasattr(self, 'item_name_cb'):
            current = list(self.item_name_cb['values'])
            if name not in current:
                current.append(name)
                current.sort()
                self.item_name_cb['values'] = current
        # NOTE:

    def _add_typed_product_to_dropdown(self, event=None):
       
        if not hasattr(self, 'item_name_cb'):
            return
        name = self.item_name.get().strip()
        if not name:
            return
        current = list(self.item_name_cb['values'])
        if name not in current:
            current.append(name)
            current.sort()
            self.item_name_cb['values'] = current

   
    def add_product_popup(self):
        
        open_product_form(self, godown_name=self.cust_godown.get().strip(),
                          on_saved=self._after_product_saved)

    def _after_product_saved(self, name):
        self.load_products()          # item dropdown  godown-filtered refresh 
        self.item_name.set(name)
        self.on_item_name_selected()  # HSN/Unit/Rate/Weight auto-fill

    def open_godown_item_picker(self):
        godown=self.cust_godown.get().strip()
        if not godown or getattr(self,'_godown_picker_open',False):return
        names=self._godown_filtered_product_names()
        win=tk.Toplevel(self);self._godown_picker_open=True;win.title(f'{godown} Items');win.transient(self)
        def close():
            self._godown_picker_open=False;win.destroy()
        win.protocol('WM_DELETE_WINDOW',close)
        lb=tk.Listbox(win,width=48,height=12)
        lb.pack(fill='both',expand=True,padx=10,pady=8)
        for n in names:lb.insert('end',n)
        if not names:lb.insert('end','No products fixed for this godown')
        def pick(event=None):
            sel=lb.curselection()
            if not sel or not names:return
            self.item_name.set(lb.get(sel[0]));self.on_item_name_selected();close()
        lb.bind('<Double-1>',pick)
        ttk.Button(win,text='Select',command=pick).pack(side='left',padx=10,pady=(0,10))
        ttk.Button(win,text='Add Product',command=lambda:(close(),self.add_new_product_quick())).pack(side='left',padx=4,pady=(0,10))

    def load_customers(self):
        with conn() as c:
            rows=c.execute('SELECT * FROM customers ORDER BY name').fetchall()
        self.customer_map={f"{r['id']} - {r['name']}":dict(r) for r in rows}
        self.customer_by_name={dict(r)['name']:dict(r) for r in rows}
        if hasattr(self,'customer_cb'):self.customer_cb['values']=list(self.customer_map)
        if hasattr(self,'cust_name_cb'):self.cust_name_cb['values']=sorted(self.customer_by_name)
    def load_products(self):
        with conn() as c:
            rows=c.execute('SELECT * FROM products ORDER BY item_name').fetchall()
        self.product_by_name={dict(r)['item_name']:dict(r) for r in rows}
     
        gvals=self._all_godowns()
        if hasattr(self,'cust_godown_cb'):self.cust_godown_cb['values']=gvals
        if hasattr(self,'item_name_cb'):self.item_name_cb['values']=self._godown_filtered_product_names()
    def load_customer_godowns(self, customer_id=None, selected=''):
       
        vals=self._all_godowns()
        self.cust_godown_values=vals
        if hasattr(self,'cust_godown_cb'):
            self.cust_godown_cb['values']=vals
            keep=selected or self.cust_godown.get().strip()
            self.cust_godown.set(keep if keep in vals else '')

    def _update_today_total(self, customer_id=None):
        # 'Today Total' = selected customer cha AAJCHYA tarkhecha total:
        # tyachya sarva invoices madhle jya items chi swatachi date aaj
        # (system chi aajchi tarikh) aahe, tya items chi rakkam (amount) jodto.
        # Payment Mode ani settled/unsettled kahi pan asu dya - sagle mojle jatat.
        try:
            if not hasattr(self,'today_total'):
                return
            if customer_id is None:
                cust=self.customer_by_name.get(self.cust_name.get().strip())
                customer_id=cust.get('id') if cust else None
            if not customer_id:
                self.today_total.set('0.00')
                return
            today=datetime.now().strftime('%d-%m-%Y')
            with conn() as c:
                row=c.execute(
                    "SELECT COALESCE(SUM(ii.amount),0) AS t "
                    "FROM invoices i JOIN invoice_items ii ON ii.invoice_id=i.id "
                    "WHERE i.customer_id=? AND COALESCE(ii.date,i.date)=?",
                    (customer_id,today)
                ).fetchone()
            self.today_total.set(f"{float(row['t'] or 0):,.2f}")
        except Exception:
            self.today_total.set('0.00')

    def _update_customer_total(self, customer_id=None):
        # 'Customer Total' FAKT ajun 'settle' na zalelya (settled=0)
        # invoices chi bereej dakhavto. Customer Statement window madhun
        # invoice settle kela (settled=1) ki tyachi rakkam ithun kami hote.
        # Hi function 'Today Total' pan sobat refresh karte.
        try:
            if customer_id is None:
                cust=self.customer_by_name.get(self.cust_name.get().strip())
                customer_id=cust.get('id') if cust else None
            self._update_today_total(customer_id)
            if not customer_id:
                self.cust_total.set('0.00')
                return
            with conn() as c:
                row=c.execute(
                    "SELECT COALESCE(SUM(total),0) AS total FROM invoices "
                    "WHERE customer_id=? AND COALESCE(settled,0)=0",
                    (customer_id,)
                ).fetchone()
            self.cust_total.set(f"{float(row['total'] or 0):,.2f}")
        except Exception:
            self.cust_total.set('0.00')

    def _start_new_invoice_after_customer_select(self):
        
        if getattr(self,'_loading_invoice_form',False):
            return
        if getattr(self,'editing_invoice_item_id',None) is not None:
            return
        if self.last_invoice and self.last_invoice.get('id'):
            self.last_invoice = None
            self.last_invoice_pdf = ''
            self.inv_no.set(self.next_format_bill_no(self.gst_mode.get() or 'GST'))
            self.inv_date.set(datetime.now().strftime('%d-%m-%Y'))
            self.inv_time.set(datetime.now().strftime('%I:%M %p'))
            self.inv_other.set('0')
            self.received.set('0')
            self.item_name.set('')
            self.item_material.set('')
            self.item_hsn.set('')
            self.item_qty.set('1')
            self.item_unit.set('Nos')
            self.item_loading.set('0')
            self.item_price.set('0')
            self.item_weight.set('0')
            self.item_total.set('0.00')
            self.show_invoice_items([])

    def on_customer_name_selected(self,event=None):
       
        self._start_new_invoice_after_customer_select()
        cust=self.customer_by_name.get(self.cust_name.get().strip())
        if not cust:
            self.cust_total.set('0.00')
            self.today_total.set('0.00')
            return
        self.cust_addr.set(cust.get('address','') or '');self.cust_phone.set(cust.get('contact_no','') or '');self.cust_email.set(cust.get('email','') or '');self.cust_state.set(cust.get('state','') or '')
        self.cust_gstin.set(cust.get('gstin','') or '')
        self.cust_person.set(cust.get('contact_person','') or '');self.load_customer_godowns(cust['id'], '')
        self.cust_district.set(cust.get('district','') or '');self.cust_pincode.set(cust.get('pincode','') or '');self.cust_phone_no.set(cust.get('phone_no','') or '')
        self._update_customer_total(cust['id'])
        self._prefill_latest_challan(cust['id'])
    def _prefill_latest_challan(self, customer_id):
        
        if self.editing_invoice_item_id is not None:
            return
        try:
            with conn() as c:
                row=c.execute(
                    'SELECT number,total FROM challans WHERE customer_id=? ORDER BY id DESC LIMIT 1',
                    (customer_id,)
                ).fetchone()
        except Exception:
            row=None
        if not row:
            return
        total=float(row['total'] or 0)
        if total<=0:
            return
        self.item_qty.set('1')
        self.item_price.set(f'{total:.2f}')
        self.item_loading.set('0')
    def on_item_name_selected(self,event=None):
        
        pass
    def customer_key(self,cid):
        for k,v in self.customer_map.items():
            if v.get('id')==cid:return k
        return ''
    def refresh_all(self):
        self.load_customers();self.load_products();self.load_invoices()
    def show_invoice_items(self,items):
        if hasattr(self,'invoice_items_lbl'):
            total=sum(float(it.get('amount') or 0) for it in items)
            self.invoice_items_lbl.config(text=f'Items: {len(items)} | Total: {total:,.2f}')
    def current_items(self):
        if self.last_invoice:return self.last_invoice.get('items',[])
        return []

    # ---------- Item-level EDIT support (Saved Invoices -> Edit) ----------
    def _set_item_edit_status(self,text):
        if hasattr(self,'item_edit_status'):
            self.item_edit_status.set(text)
        if hasattr(self,'item_add_btn'):
            self.item_add_btn.configure(text='UPDATE ITEM' if text else 'ADD (Save Item + Invoice)')

    def _load_item_into_fields(self,item):
       
        qty=float(item.get('qty') or 0)
        weight_kg=float(item.get('weight_kg') or 0)
        self.item_name.set(item.get('item_name','') or '')
        self.item_material.set(item.get('material','') or '')
        self.item_hsn.set(item.get('hsn_sac','') or '')
        self.item_qty.set(str(qty if qty else 0))
        self.item_unit.set(item.get('unit','') or 'Nos')
        self.item_price.set(str(item.get('price') or 0))
        self.item_loading.set(str(item.get('loading') or 0))
        self.item_weight.set(str(weight_kg/qty) if qty else '0')
        self.editing_invoice_item_id=item.get('id')
        # ha item jya date la add zala hota, tich date Date box madhye parat
        # dakhva - navhe tar invoice cha (header) date dakhat rahila asta.
        if item.get('date'):
            self.inv_date.set(item.get('date'))
            self._update_day()
        self._set_item_edit_status(f"Editing: {item.get('item_name','') or ''} (update करून वर ADD/UPDATE दाबा)")

    def cancel_item_edit(self):
        
        self.editing_invoice_item_id=None
        self._set_item_edit_status('')
        self.item_name.set('');self.item_material.set('');self.item_hsn.set('');self.item_qty.set('1');self.item_unit.set('Nos');self.item_loading.set('0');self.item_price.set('0');self.item_weight.set('0')

    def add_manual_item(self):
        name=self.item_name.get().strip()
        if not name:return messagebox.showerror('Item','Enter item name')
        try:
            qty=float(self.item_qty.get() or 0);price=float(self.item_price.get() or 0);weight=float(self.item_weight.get() or 0);loading=float(self.item_loading.get() or 0)
        except:
            return messagebox.showerror('Item','Qty, rate, and loading must be numbers')
       
        items=list(self.current_items())
        new_item={'product_id':None,'item_name':name,'material':self.item_material.get().strip(),'hsn_sac':self.item_hsn.get().strip(),'qty':qty,'unit':self.item_unit.get().strip() or 'Nos','price':price,'loading':loading,'amount':qty*price+loading,'weight_kg':weight*qty}
        if self.editing_invoice_item_id is not None:
           
            updated=False
            for idx,it in enumerate(items):
                if it.get('id')==self.editing_invoice_item_id:
                    new_item['id']=it.get('id')
                    # item EDIT karatana junich date kayam thevaa (navin date deu naye)
                    new_item['date']=it.get('date')
                    items[idx]=new_item
                    updated=True
                    break
            if not updated:
                items.append(new_item)
            self.editing_invoice_item_id=None
            self._set_item_edit_status('')
        else:
            items.append(new_item)
        self.last_invoice={'header':self.manual_header(items),'customer':self.manual_customer(),'items':items,'id':(self.last_invoice or {}).get('id')}
        self.show_invoice_items(items);self.item_name.set('');self.item_material.set('');self.item_hsn.set('');self.item_qty.set('1');self.item_unit.set('Nos');self.item_loading.set('0');self.item_price.set('0');self.item_weight.set('0')
    def remove_manual_item(self):
        items=list(self.current_items())
        if not items:return messagebox.showerror('Item','No items to remove yet')
        items.pop()
        self.last_invoice={'header':self.manual_header(items),'customer':self.manual_customer(),'items':items,'id':(self.last_invoice or {}).get('id')}
        self.show_invoice_items(items)
    def manual_customer(self):
        return {'name':self.cust_name.get().strip(),'address':self.cust_addr.get().strip(),'contact_no':self.cust_phone.get().strip(),'email':self.cust_email.get().strip(),'state':self.cust_state.get().strip(),'gstin':self.cust_gstin.get().strip(),'contact_person':self.cust_person.get().strip(),'district':self.cust_district.get().strip(),'pincode':self.cust_pincode.get().strip(),'phone_no':self.cust_phone_no.get().strip(),'godown':self.cust_godown.get().strip()}
    def manual_header(self,items):
        mode=(self.gst_mode.get() or 'GST').upper()
        sub=sum(float(i.get('amount') or 0) for i in items)
        gst=DocEditor.csv_float(self,self.inv_gst.get(),DEFAULT_GST_RATE)
        discount=DocEditor.csv_float(self,self.inv_discount.get(),0)
        taxable=sub-discount
        tax=taxable*gst/100 if mode!='NO_GST' else 0
        freight=DocEditor.csv_float(self,self.inv_freight.get(),0)
        other=DocEditor.csv_float(self,self.inv_other.get(),0)
        total=taxable+tax+freight+other
        rec=DocEditor.csv_float(self,self.received.get(),0)
        number=self.inv_no.get().strip() or self.next_format_bill_no(mode)
        return {'number':number,'date':self.inv_date.get().strip() or datetime.now().strftime('%d-%m-%Y'),'day':self.inv_day.get(),'time':self.inv_time.get(),'gst_rate':gst if mode!='NO_GST' else 0,'subtotal':sub,'discount':discount,'cgst':tax/2,'sgst':tax/2,'freight':freight,'other_charges':other,'total':total,'payment_mode':self.mode.get(),'received':rec,'vehicle':self.inv_vehicle.get().strip(),'balance':total-rec,'notes':self.inv_notes.get().strip(),'godown':self.cust_godown.get().strip(),'gst_mode':'GST' if mode!='NO_GST' else 'NO_GST','tax_type':(self.tax_type.get() if mode!='NO_GST' else 'CGST+SGST')}
    def fill_manual_form(self,hdr,cust):
        self.inv_no.set(hdr.get('number',''));self.inv_date.set(hdr.get('date',''));self.inv_time.set(hdr.get('time') or self.inv_time.get() or datetime.now().strftime('%I:%M %p'));self.inv_gst.set(str(hdr.get('gst_rate') or DEFAULT_GST_RATE));self.inv_freight.set(str(hdr.get('freight') or 0));self.inv_discount.set(str(hdr.get('discount') or 0));self.inv_other.set(str(hdr.get('other_charges') or 0));self.inv_notes.set(hdr.get('notes') or '');self.inv_vehicle.set(hdr.get('vehicle') or '')
        self.cust_name.set(cust.get('name',''));self.cust_addr.set(cust.get('address',''));self.cust_phone.set(cust.get('contact_no',''));self.cust_email.set(cust.get('email',''));self.cust_state.set(cust.get('state',''));self.cust_gstin.set(cust.get('gstin',''));self.cust_person.set(cust.get('contact_person',''))
        self.cust_district.set(cust.get('district','') or '');self.cust_pincode.set(cust.get('pincode','') or '');self.cust_phone_no.set(cust.get('phone_no','') or '')
        self._update_customer_total(cust.get('id'))
       
        self.load_customer_godowns(cust.get('id'), cust.get('godown','') or '')
    def save_manual_invoice(self):
        if self.item_name.get().strip():
            self.add_manual_item()
        items=self.current_items();cust=self.manual_customer()
        if not cust.get('name') or not items:return messagebox.showerror('Required','Customer name and at least one material/item required')
        hdr=self.manual_header(items)
        existing_iid=(self.last_invoice or {}).get('id')
       
        if existing_iid:
            old_no=str((self.last_invoice.get('header') or {}).get('number') or '').strip()
            if str(hdr.get('number') or '').strip() != old_no:
                existing_iid=None
                self.last_invoice=None

        # Form 'fresh' aahe (edit sathi loaded navhata) ani typed kelela
        # Bill No. + Customer aadhichya ekhadya invoice shi jullat asel, tar
        # navin invoice na banavta tyach junya invoice madhye item merge kara.
        # Juney items tyanchich original date thevtat, navin item la aajchi
        # date milte (khali stamping loop madhe).
        merged=False
        if not existing_iid:
            match_id=self._find_matching_invoice(hdr.get('number'), cust.get('name'))
            if match_id:
                merged=True
                existing_iid=match_id
                with conn() as c:
                    old_items=[dict(r) for r in c.execute(
                        'SELECT * FROM invoice_items WHERE invoice_id=?', (match_id,)
                    ).fetchall()]
                current_ids={it.get('id') for it in items if it.get('id')}
                items=[it for it in old_items if it.get('id') not in current_ids]+items

        # Jya item la ajun swatachi date nahi (mhanje navin add kelela item),
        # tyala DATE BOX madhye jashi typed asel TASHICH date stamp kara.
        typed_date_str = self.inv_date.get().strip() or datetime.now().strftime('%d-%m-%Y')
        for it in items:
            if not it.get('date'):
                it['date']=typed_date_str

        hdr=self.manual_header(items)
        if not merged:
            hdr['number']=self._unique_invoice_number(hdr['number'], exclude_id=existing_iid)
        self.inv_no.set(hdr['number'])
        try:
            with conn() as c:
                old=c.execute('SELECT * FROM customers WHERE lower(name)=lower(?)',(cust['name'],)).fetchone()
                if old:
                    cid=old['id'];c.execute('UPDATE customers SET address=?,contact_no=?,email=?,state=?,gstin=?,contact_person=?,district=?,pincode=?,phone_no=? WHERE id=?',(cust['address'],cust['contact_no'],cust['email'],cust['state'],cust['gstin'],cust['contact_person'],cust.get('district',''),cust.get('pincode',''),cust.get('phone_no',''),cid))
                else:
                    cur=c.execute('INSERT INTO customers(name,address,contact_no,email,state,gstin,contact_person,district,pincode,phone_no) VALUES(?,?,?,?,?,?,?,?,?,?)',(cust['name'],cust['address'],cust['contact_no'],cust['email'],cust['state'],cust['gstin'],cust['contact_person'],cust.get('district',''),cust.get('pincode',''),cust.get('phone_no','')));cid=cur.lastrowid
                iid=existing_iid
                if iid:
                    # Editing/re-saving an already-settled invoice un-locks
                    # it again in the Customer Statement window (settled=0).
                    c.execute('UPDATE invoices SET number=?,date=?,customer_id=?,godown=?,gst_rate=?,subtotal=?,discount=?,cgst=?,sgst=?,freight=?,other_charges=?,total=?,payment_mode=?,received=?,balance=?,notes=?,time=?,gst_mode=?,tax_type=?,settled=0 WHERE id=?',(hdr['number'],hdr['date'],cid,hdr.get('godown',''),hdr['gst_rate'],hdr['subtotal'],hdr.get('discount',0),hdr['cgst'],hdr['sgst'],hdr['freight'],hdr.get('other_charges',0),hdr['total'],hdr['payment_mode'],hdr['received'],hdr['balance'],hdr['notes'],hdr['time'],hdr.get('gst_mode','GST'),hdr.get('tax_type','CGST+SGST'),iid));c.execute('DELETE FROM invoice_items WHERE invoice_id=?',(iid,))
                else:
                    cur=c.execute('INSERT INTO invoices(number,date,customer_id,godown,gst_rate,subtotal,discount,cgst,sgst,freight,other_charges,total,payment_mode,received,balance,notes,time,gst_mode,tax_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(hdr['number'],hdr['date'],cid,hdr.get('godown',''),hdr['gst_rate'],hdr['subtotal'],hdr.get('discount',0),hdr['cgst'],hdr['sgst'],hdr['freight'],hdr.get('other_charges',0),hdr['total'],hdr['payment_mode'],hdr['received'],hdr['balance'],hdr['notes'],hdr['time'],hdr.get('gst_mode','GST'),hdr.get('tax_type','CGST+SGST')));iid=cur.lastrowid
                for it in items:
                    # prati item tyachi swatachi date save kara
                    item_date=it.get('date') or hdr.get('date') or typed_date_str
                    c.execute('INSERT INTO invoice_items(invoice_id,product_id,item_name,hsn_sac,qty,unit,price,amount,weight_kg,loading,date,material) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(iid,it.get('product_id'),it.get('item_name',''),it.get('hsn_sac',''),it.get('qty',0),it.get('unit',''),it.get('price',0),it.get('amount',0),it.get('weight_kg',0),it.get('loading',0),item_date,it.get('material','') or ''))
                    self._remember_product_name(c,it.get('item_name',''))
                if hdr.get('vehicle') or not merged:
                    c.execute('UPDATE invoices SET vehicle=? WHERE id=?',(hdr.get('vehicle',''),iid))
                cust=dict(c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone())
        except Exception as e:
            return messagebox.showerror('Save Failed',f'Could not save invoice:\n{e}')
        # DELETE+INSERT mule item ids badalatat, tyamule edit-mode ithe nakki clear kara.
        self.editing_invoice_item_id=None
        self._set_item_edit_status('')
        self.last_invoice={'header':hdr,'customer':cust,'items':items,'id':iid};self.last_invoice_pdf=make_pdf('invoice',hdr,cust,items,copy_label='ORIGINAL');self.load_customers();self.load_products();self.load_invoices();self._update_customer_total(cid)
        # save zalyavar direct NAVIN invoice (rakkam kitihi asu dya)
        saved_no=hdr['number'];saved_pdf=self.last_invoice_pdf
        self.last_saved_id=iid
        self._start_fresh_invoice()
        messagebox.showinfo('Saved',f'Invoice {saved_no} saved and PDF ready:\n{saved_pdf}\n\nNavin Bill No.: {self.inv_no.get()}')
    def load_invoices(self):
        with conn() as c:
            rows=c.execute('SELECT ii.id AS item_id,i.id AS invoice_id,i.number,i.date AS invoice_date,'
                            'ii.date AS item_date,'
                            'ii.item_name,ii.material,ii.hsn_sac,ii.qty,ii.price,ii.loading,c.name,i.payment_mode,i.vehicle,i.total,c.gstin,i.godown,i.gst_mode '
                            'FROM invoice_items ii '
                            'JOIN invoices i ON i.id=ii.invoice_id '
                            'JOIN customers c ON c.id=i.customer_id '
                            'ORDER BY i.id DESC, ii.id').fetchall()
            inv_rows=c.execute('SELECT i.id,i.number,i.date,c.name,i.total FROM invoices i JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC').fetchall()
        self.invoice_map={f"{r['number']} | {r['date']} | {r['name']} | {r['total']:.2f}":r['id'] for r in inv_rows}
        if hasattr(self,'invoice_cb'):self.invoice_cb['values']=list(self.invoice_map)
        if hasattr(self,'ilist'):
            for x in self.ilist.get_children():self.ilist.delete(x)
            self.ilist_invoice_of={};self.ilist_item_of={}
            for r in rows:
                row_iid=f"item_{r['item_id']}"
                fmt = 'GST' if str(r['gst_mode'] or 'GST').upper() != 'NO_GST' else 'WITHOUT GST'
                # WITHOUT GST invoice must not show any GST value.
                # For GST invoices, show the customer's GSTIN.
                is_without_gst = str(r['gst_mode'] or 'GST').upper() == 'NO_GST'
                gstin_display = '' if is_without_gst else (r['gstin'] or '').strip()
                # 'Date' column prati item chi swatachi date dakhavte
                # (nasel tar invoice chi date fallback mhanun).
                row_date = r['item_date'] or r['invoice_date']

                vals=(r['number'],row_date,
                      r['item_name'] or '',r['material'] or '',r['hsn_sac'] or '',r['qty'] or 0,
                      r['price'] or 0,r['loading'] or 0,
                      r['name'] or '',r['payment_mode'] or '',r['vehicle'] or '',f"{float(r['total'] or 0):,.2f}",
                      gstin_display,fmt,
                      'Download','Print','Edit','Delete')
                self.ilist.insert('','end',iid=row_iid,values=vals)
                self.ilist_invoice_of[row_iid]=r['invoice_id']
                self.ilist_item_of[row_iid]=r['item_id']
    def day_from_date(self,ds):
        for fmt in ('%d-%m-%Y','%Y-%m-%d','%d/%m/%Y'):
            try:return datetime.strptime((ds or '').strip(),fmt).strftime('%A')
            except Exception:continue
        return ''
    def on_ilist_click(self,event):
        if self.ilist.identify('region',event.x,event.y)!='cell':return
        row_id=self.ilist.identify_row(event.y)
        if not row_id:return
        idx=int(self.ilist.identify_column(event.x).replace('#',''))-1
        if idx<0 or idx>=len(self.icols):return
        name=self.icols[idx]
        if name=='dl':self.download_row(row_id)
        elif name=='print':self.print_row(row_id)
        elif name=='edit':self.edit_row(row_id)
        elif name=='delete':self.delete_row(row_id)
    def edit_row(self,row_id):
        
        invoice_id=self.ilist_invoice_of.get(row_id)
        item_id=self.ilist_item_of.get(row_id)
        if not invoice_id:return
        self.load_invoice_by_id(invoice_id,silent=True)
        if item_id is not None:
            for it in self.current_items():
                if it.get('id')==item_id:
                    self._load_item_into_fields(it)
                    break
    # Download dabalyavar aadhi "kiti copies?" vicharto, mag PDF save karto.
    # PDF of ONE specific invoice id, built straight from the database.
    # Does not touch the form and has NO 'latest invoice' fallback, so the
    # invoice that was clicked is always the one downloaded.
    def _pdf_for_invoice_id(self,iid,copies=1,path=None):
        with conn() as c:
            row=c.execute('SELECT * FROM invoices WHERE id=?',(int(iid),)).fetchone()
            if not row:
                raise RuntimeError('Invoice not found.')
            inv=dict(row)
            cu=c.execute('SELECT * FROM customers WHERE id=?',(inv.get('customer_id'),)).fetchone()
            items=[dict(r) for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id',(int(iid),)).fetchall()]
        cust=dict(cu) if cu else {}
        cust['godown']=inv.get('godown') or ''
        if not items:
            raise RuntimeError('This invoice has no items.')
        hdr={'number':inv.get('number') or 'DOC','date':inv.get('date') or '','day':self.day_from_date(inv.get('date')),'time':inv.get('time') or '',
             'gst_rate':inv.get('gst_rate') or 0,'subtotal':inv.get('subtotal') or 0,'discount':inv.get('discount') or 0,
             'cgst':inv.get('cgst') or 0,'sgst':inv.get('sgst') or 0,'freight':inv.get('freight') or 0,
             'other_charges':inv.get('other_charges') or 0,'total':inv.get('total') or 0,'payment_mode':inv.get('payment_mode') or '',
             'received':inv.get('received') or 0,'balance':inv.get('balance') or 0,'notes':inv.get('notes') or '',
             'vehicle':inv.get('vehicle') or '','godown':inv.get('godown') or '',
             'gst_mode':inv.get('gst_mode') or 'GST','tax_type':inv.get('tax_type') or 'CGST+SGST','copies':copies}
        if path is None:
            path=os.path.join(tempfile.gettempdir(),f'invoice_{iid}_{datetime.now().strftime("%H%M%S")}.pdf')
        return make_pdf('invoice',hdr,cust,items,path=path)
    # Download: saves EXACTLY the clicked invoice (not the last / loaded one).
    def download_row(self,row_id):
        iid=self.ilist_invoice_of.get(row_id)
        if not iid:
            return
        n=self._ask_copies()
        if not n:
            return
        try:
            src=self._pdf_for_invoice_id(iid,copies=n)
        except Exception as e:
            return messagebox.showerror('Download Failed',f'Could not create invoice PDF:\n{e}')
        try:
            with conn() as c:
                r=c.execute('SELECT number FROM invoices WHERE id=?',(int(iid),)).fetchone()
            no=str(r['number']) if r and r['number'] else str(iid)
        except Exception:
            no=str(iid)
        dst=filedialog.asksaveasfilename(parent=self,defaultextension='.pdf',initialfile=f'invoice_{no}.pdf',filetypes=[('PDF','*.pdf')])
        if not dst:
            return
        try:
            shutil.copyfile(src,dst)
            messagebox.showinfo('Downloaded',dst)
        except Exception as e:
            messagebox.showerror('Download Failed',f'Could not save the PDF:\n{e}')
    def delete_row(self,row_id):
        self.delete_invoice_by_id(self.ilist_invoice_of.get(row_id))
    def load_selected_invoice(self):
        iid=self.invoice_map.get(self.existing_invoice.get())
        if not iid:return messagebox.showerror('Load','Select a saved invoice')
        self.load_invoice_by_id(iid)
    def load_invoice_by_id(self,iid,silent=False):
        
        self.editing_invoice_item_id=None
        self._set_item_edit_status('')
        self._loading_invoice_form=True
        try:
            with conn() as c:
                inv=dict(c.execute('SELECT * FROM invoices WHERE id=?',(iid,)).fetchone())
                cust=dict(c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone())
                items=[dict(r) for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=?',(iid,)).fetchall()]
        finally:
            self._loading_invoice_form=False
        # Godown customer 
        cust['godown']=inv.get('godown') or ''
        hdr={'number':inv['number'],'date':inv['date'],'day':self.day_from_date(inv['date']),'time':inv.get('time') or '','gst_rate':inv['gst_rate'],'subtotal':inv['subtotal'],'discount':inv.get('discount') or 0,'cgst':inv['cgst'],'sgst':inv['sgst'],'freight':inv['freight'],'other_charges':inv.get('other_charges') or 0,'total':inv['total'],'payment_mode':inv['payment_mode'],'received':inv['received'],'balance':inv['balance'],'notes':inv['notes'],'vehicle':inv.get('vehicle') or '','godown':inv.get('godown') or '','gst_mode':inv.get('gst_mode') or 'GST','tax_type':inv.get('tax_type') or 'CGST+SGST'}
        self.gst_mode.set(hdr['gst_mode']);self.tax_type.set(hdr['tax_type']);self.customer.set(self.customer_key(inv.get('customer_id')));self.mode.set(inv.get('payment_mode') or 'Cash');self.received.set(str(inv.get('received') or 0));self.fill_manual_form(hdr,cust);self._apply_gst_visibility();self.last_invoice={'header':hdr,'customer':cust,'items':items,'id':iid};self.last_invoice_pdf=make_pdf('invoice',hdr,cust,items,copy_label='ORIGINAL');self.show_invoice_items(items)
        if not silent:
            messagebox.showinfo('Loaded',f'Invoice loaded and PDF ready:\n{self.last_invoice_pdf}')
    def update_loaded_invoice(self):
        if not self.last_invoice or not self.last_invoice.get('id'):return messagebox.showerror('Invoice','Load an invoice first')
        iid=self.last_invoice['id'];items=self.last_invoice['items'];sub=sum(float(i.get('amount') or 0) for i in items);gmode=self.gst_mode.get() or 'GST';gst=float(self.last_invoice['header'].get('gst_rate') or DEFAULT_GST_RATE);discount=float(self.last_invoice['header'].get('discount') or 0);taxable=sub-discount;tax=taxable*gst/100 if gmode.upper()!='NO_GST' else 0;freight=float(self.last_invoice['header'].get('freight') or 0);other=float(self.last_invoice['header'].get('other_charges') or 0);total=taxable+tax+freight+other;rec=DocEditor.csv_float(self,self.received.get(),0);bal=total-rec
        ttype=self.tax_type.get() if gmode.upper()!='NO_GST' else 'CGST+SGST'
        with conn() as c:
            # Editing/re-saving an already-settled invoice un-locks it
            # again in the Customer Statement window (settled=0).
            c.execute('UPDATE invoices SET godown=?,subtotal=?,discount=?,cgst=?,sgst=?,freight=?,other_charges=?,total=?,payment_mode=?,received=?,balance=?,time=?,gst_mode=?,tax_type=?,settled=0 WHERE id=?',(self.cust_godown.get(),sub,discount,tax/2,tax/2,freight,other,total,self.mode.get(),rec,bal,self.inv_time.get(),gmode,ttype,iid))
            c.execute('UPDATE invoices SET vehicle=? WHERE id=?',(self.inv_vehicle.get().strip(),iid))
            inv=dict(c.execute('SELECT * FROM invoices WHERE id=?',(iid,)).fetchone());cust=dict(c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone())
        hdr={'number':inv['number'],'date':inv['date'],'day':self.day_from_date(inv['date']),'time':inv.get('time') or self.inv_time.get(),'gst_rate':inv['gst_rate'],'subtotal':sub,'discount':discount,'cgst':tax/2,'sgst':tax/2,'freight':freight,'other_charges':other,'total':total,'payment_mode':self.mode.get(),'received':rec,'balance':bal,'notes':inv['notes'],'vehicle':self.inv_vehicle.get().strip(),'gst_mode':gmode,'tax_type':ttype}
        self.last_invoice={'header':hdr,'customer':cust,'items':items,'id':iid};self.last_invoice_pdf=make_pdf('invoice',hdr,cust,items,copy_label='ORIGINAL');self.show_invoice_items(items);self.load_invoices();self._update_customer_total(inv.get('customer_id'));messagebox.showinfo('Updated',f'Invoice updated and PDF ready:\n{self.last_invoice_pdf}')

    # ---------- COPIES: kiti copies hawya (Print / Download) ----------
    def _ask_copies(self):
        """Print / Download How many copies"""
        return simpledialog.askinteger(
            'Copies',
            'How many  copies ?\n(2 copies = 1 A4 )',
            parent=self, minvalue=1, maxvalue=10, initialvalue=2
        )

    def _make_invoice_pdf_with_copies(self, copies, path=None):
        """Current invoice cha PDF 'copies' sankhyene banavto.
        Ek A4 var 2 copies (var + khali), ORIGINAL/DUPLICATE nav nahi."""
        hdr = dict(self.last_invoice['header'])
        hdr['copies'] = copies
        return make_pdf('invoice', hdr, self.last_invoice['customer'],
                        self.last_invoice['items'], path=path)

    def save_pdf_as(self, copies=None):
        if not self.ensure_invoice_pdf():return
        src=self.last_invoice_pdf
        if copies:
            try:
                no=str(self.last_invoice['header'].get('number','DOC'))
                tmp=os.path.join(tempfile.gettempdir(),f'invoice_{no}_{datetime.now().strftime("%H%M%S")}.pdf')
                src=self._make_invoice_pdf_with_copies(copies,path=tmp)
            except Exception as e:
                return messagebox.showerror('PDF',f'Could not create invoice PDF:\n{e}')
        dst=filedialog.asksaveasfilename(defaultextension='.pdf',initialfile=os.path.basename(src),filetypes=[('PDF','*.pdf')])
        if dst:shutil.copyfile(src,dst);messagebox.showinfo('Downloaded',dst)
    def ensure_invoice_pdf(self):
        if self.current_items():
            cust=self.manual_customer();hdr=self.manual_header(self.current_items())
            if not cust.get('name'):messagebox.showerror('Invoice','Customer name required');return None
            self.last_invoice={'header':hdr,'customer':cust,'items':self.current_items(),'id':(self.last_invoice or {}).get('id')}
            self.last_invoice_pdf=make_pdf('invoice',hdr,cust,self.current_items(),copy_label='ORIGINAL')
        if not self.last_invoice_pdf or not self.last_invoice:
            messagebox.showerror('Invoice','Generate, save, load, or import an invoice first')
            return None
        return self.last_invoice_pdf
    # Print dabalyavar "kiti copies?" vicharto. Save nantar form 'navin invoice'
    # madhe asto, tari Print shevatcha saved invoice chi karto; kaam zalyavar
    # form parat navin invoice hoto. PDF viewer madhe ughdto (tithun Ctrl+P).
    # Print button inside a Saved Invoices row: prints EXACTLY that invoice.
    def print_row(self,row_id):
        iid=self.ilist_invoice_of.get(row_id)
        if not iid:
            return
        n=self._ask_copies()
        if not n:
            return
        self._print_invoice_id(iid,n)
    def _print_invoice_id(self,iid,n):
        try:
            os.startfile(self._pdf_for_invoice_id(iid,copies=n))
        except Exception as e:
            messagebox.showerror('Print Failed',f'Could not open invoice for printing:\n{e}')
    # Invoice row selected (clicked) in Saved Invoices, if any.
    def _selected_invoice_id(self):
        try:
            for r in self.ilist.selection():
                iid=self.ilist_invoice_of.get(r)
                if iid:
                    return iid
        except Exception:
            pass
        return None
    def print_current(self):
        n=self._ask_copies()
        if not n:
            return
        # An invoice is selected in Saved Invoices and nothing is being typed
        # in the form -> print THAT invoice (not the latest one).
        sel_id=self._selected_invoice_id()
        if sel_id and not self.current_items():
            self._print_invoice_id(sel_id,n)
            return
        was_fresh=self._load_latest_saved_for_send()
        try:
            if not was_fresh and (not self.last_invoice or not self.last_invoice_pdf):
                if not self.ensure_invoice_pdf():
                    return

            if not self.last_invoice:
                messagebox.showerror('Print', 'Invoice data not available.')
                return

            try:
                no=str(self.last_invoice['header'].get('number','DOC')).strip() or 'DOC'
                # roj navin file-name, mhanje junya ughdya PDF mule error yenar nahi
                pdf_path=os.path.join(
                    tempfile.gettempdir(),
                    f'invoice_{no}_{datetime.now().strftime("%H%M%S")}.pdf'
                )
                pdf=self._make_invoice_pdf_with_copies(n,path=pdf_path)
                os.startfile(pdf)      # default PDF viewer madhe ughdto
            except Exception as e:
                messagebox.showerror('Print Failed', f'Could not open invoice for printing:\n{e}')
        finally:
            if was_fresh:
                self._start_fresh_invoice()
    def import_csv_invoice(self):
        path=filedialog.askopenfilename(filetypes=[('CSV','*.csv'),('All files','*.*')])
        if not path:return
        rows=DocEditor.read_csv_rows(self,path)
        if not rows:return messagebox.showerror('CSV','CSV file is empty')
        cust=DocEditor.upsert_customer_from_row(self,rows[0]);items=[DocEditor.item_from_csv_row(self,r) for r in rows];items=[i for i in items if i]
        if not cust or not items:return messagebox.showerror('CSV','Customer and item rows required')
        gst=DocEditor.csv_float(self,rows[0].get('gst_rate') or rows[0].get('gst'),DEFAULT_GST_RATE);gmode=self.gst_mode.get() or 'GST';sub=sum(i['amount'] for i in items);discount=DocEditor.csv_float(self,rows[0].get('discount'),0);taxable=sub-discount;tax=taxable*gst/100 if gmode.upper()!='NO_GST' else 0;freight=DocEditor.csv_float(self,rows[0].get('freight'),0);other=DocEditor.csv_float(self,rows[0].get('other_charges'),0);total=taxable+tax+freight+other;rec=DocEditor.csv_float(self,rows[0].get('received') or self.received.get(),0);bal=total-rec;num=rows[0].get('number') or rows[0].get('invoice_no') or next_number('invoices','INV-');dt=rows[0].get('date') or rows[0].get('bill_date') or datetime.now().strftime('%d-%m-%Y');tm=rows[0].get('time') or datetime.now().strftime('%I:%M %p');gmode=self.gst_mode.get()
        ttype=self.tax_type.get() if str(gmode).upper()!='NO_GST' else 'CGST+SGST'
        num=self._unique_invoice_number(num)
        with conn() as c:
            cur=c.execute('INSERT INTO invoices(number,date,customer_id,godown,gst_rate,subtotal,discount,cgst,sgst,freight,other_charges,total,payment_mode,received,balance,notes,time,gst_mode,tax_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(num,dt,cust['id'],rows[0].get('godown') or '',gst,sub,discount,tax/2,tax/2,freight,other,total,self.mode.get(),rec,bal,rows[0].get('notes') or 'Imported from CSV',tm,gmode,ttype));iid=cur.lastrowid
            for it in items:
                # CSV madhun aalele items sagle 'dt' (invoice date) hi date ghetat
                c.execute('INSERT INTO invoice_items(invoice_id,product_id,item_name,hsn_sac,qty,unit,price,amount,weight_kg,loading,date) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,it['product_id'],it['item_name'],it['hsn_sac'],it['qty'],it['unit'],it['price'],it['amount'],it['weight_kg'],it.get('loading',0),dt))
                self._remember_product_name(c,it['item_name'])
        hdr={'number':num,'date':dt,'day':self.day_from_date(dt),'time':tm,'gst_rate':gst,'subtotal':sub,'discount':discount,'cgst':tax/2,'sgst':tax/2,'freight':freight,'other_charges':other,'total':total,'payment_mode':self.mode.get(),'received':rec,'balance':bal,'notes':rows[0].get('notes') or 'Imported from CSV','gst_mode':gmode,'tax_type':ttype}
        self.fill_manual_form(hdr,cust);self.last_invoice_pdf=make_pdf('invoice',hdr,cust,items,copy_label='ORIGINAL');self.last_invoice={'header':hdr,'customer':cust,'items':items,'id':iid};self.show_invoice_items(items)
        self.load_customers();self.load_products();self.load_invoices();messagebox.showinfo('Imported',f'Invoice imported and PDF created:\n{self.last_invoice_pdf}')
    def export_invoice_csv(self):
        if not self.last_invoice:return messagebox.showerror('Export','Load, generate, or import an invoice first')
        hdr=self.last_invoice['header'];cust=self.last_invoice['customer'];items=self.last_invoice['items']
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'invoice_{hdr["number"]}.csv',filetypes=[('CSV','*.csv')])
        if not path:return
        cols=['doc_type','number','date','day','time','customer_name','customer_address','contact_no','email','state','gstin','contact_person','gst_rate','discount','freight','other_charges','payment_mode','received','balance','notes','item_name','hsn_sac','qty','unit','price','loading','amount','weight_kg']
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
            for it in items:w.writerow({'doc_type':'invoice','number':hdr.get('number',''),'date':hdr.get('date',''),'day':hdr.get('day',''),'time':hdr.get('time',''),'customer_name':cust.get('name',''),'customer_address':cust.get('address',''),'contact_no':cust.get('contact_no',''),'email':cust.get('email',''),'state':cust.get('state',''),'gstin':cust.get('gstin',''),'contact_person':cust.get('contact_person',''),'gst_rate':'','discount':hdr.get('discount',0),'freight':hdr.get('freight',0),'other_charges':hdr.get('other_charges',0),'payment_mode':hdr.get('payment_mode',''),'received':hdr.get('received',0),'balance':hdr.get('balance',0),'notes':hdr.get('notes',''),'item_name':it.get('item_name',''),'hsn_sac':it.get('hsn_sac',''),'qty':it.get('qty',0),'unit':it.get('unit',''),'price':it.get('price',0),'loading':it.get('loading',0),'amount':it.get('amount',0),'weight_kg':it.get('weight_kg',0)})
        messagebox.showinfo('Exported',path)
    def delete_invoice(self):
        iid=(self.last_invoice or {}).get('id') or self.invoice_map.get(self.existing_invoice.get())
        if not iid:return messagebox.showerror('Delete','Load or select a saved invoice first')
        self.delete_invoice_by_id(iid)
    def delete_invoice_by_id(self,iid):
        if not messagebox.askyesno('Delete','Delete selected invoice?'):return
        with conn() as c:
            c.execute('DELETE FROM invoice_challans WHERE invoice_id=?',(iid,))
            c.execute('DELETE FROM invoice_items WHERE invoice_id=?',(iid,))
            c.execute('DELETE FROM invoices WHERE id=?',(iid,))
        if self.last_saved_id==iid:self.last_saved_id=None
        self.last_invoice=None;self.last_invoice_pdf='';self.existing_invoice.set('');self.show_invoice_items([]);self.load_invoices()
        # invoice delete zalyavar Customer Total parat mojto; product naave tasech rahtat
        self._update_customer_total()
        self.refresh_product_dropdown()
        messagebox.showinfo('Deleted','Invoice deleted')
    # WhatsApp pan save nantar shevatcha saved invoice pathavto.
    def whatsapp_current(self):
        was_fresh=self._load_latest_saved_for_send()
        try:
            if not was_fresh and (not self.last_invoice or not self.last_invoice_pdf):
                if not self.ensure_invoice_pdf():
                    return

            if not self.last_invoice or not self.last_invoice_pdf:
                messagebox.showerror('WhatsApp','Generate, save, load, or import an invoice first')
                return

            cust=self.last_invoice['customer']
            hdr=self.last_invoice['header']
            phone=simpledialog.askstring(
                'WhatsApp',
                'Enter WhatsApp number',
                initialvalue=cust.get('contact_no','')
            )
            if not phone:
                return

            try:
                result=open_whatsapp(
                    phone,
                    f'Invoice {hdr["number"]} generated. Total Rs. {hdr["total"]:.2f}.',
                    self.last_invoice_pdf
                )
                messagebox.showinfo('WhatsApp', result)
            except Exception as e:
                messagebox.showerror('WhatsApp','Could not send invoice PDF:\n'+str(e))
        finally:
            if was_fresh:
                self._start_fresh_invoice()
    # Email pan save nantar shevatcha saved invoice pathavto.
    def email_current(self):
        was_fresh=self._load_latest_saved_for_send()
        try:
            if not self.ensure_invoice_pdf():return
            cust=self.last_invoice['customer'];hdr=self.last_invoice['header'];to=simpledialog.askstring('Email','Enter email address',initialvalue=cust.get('email',''))
            if not to:return
            try:
                msg=send_email_or_compose(to,f'Invoice {hdr["number"]}',f'Please find attached Invoice {hdr["number"]}. Total Rs. {hdr["total"]:.2f}.',self.last_invoice_pdf);messagebox.showinfo('Email',msg)
            except Exception as e:messagebox.showerror('Email not sent',str(e))
        finally:
            if was_fresh:
                self._start_fresh_invoice()

    # ================= CUSTOMER STATEMENT (Invoices) =================
    # Pick a Customer (type the name - matching names appear in a list
    # under the box), see EVERY one of their saved Invoices - ONE ROW PER
    # PRODUCT (nothing is merged/de-duplicated). Payment Mode and 'settled'
    # belong to the whole INVOICE, so ticking any row ticks all rows of
    # that invoice together. An invoice locks ONLY after "Apply Payment
    # Mode to Selected" is used on it; editing/re-saving it elsewhere
    # unlocks it again. The Total next to the Customer field drops live by
    # whatever (still-unlocked) invoices are ticked.
    def open_customer_statement(self):
        win = tk.Toplevel(self)
        win.title('Customer Statement')
        win.geometry('980x580')
        try:
            win.transient(self.winfo_toplevel())
        except Exception:
            pass

        top = ttk.Frame(win)
        top.pack(fill='x', padx=10, pady=10)
        ttk.Label(top, text='Customer').pack(side='left')

        cust_var = tk.StringVar()

        def _all_customer_names():
            names = set()
            try:
                with conn() as c:
                    for r in c.execute('SELECT name FROM customers'):
                        nm = (r['name'] or '').strip()
                        if nm:
                            names.add(nm)
            except Exception:
                pass
            for nm in getattr(self, 'customer_by_name', {}).keys():
                nm = (nm or '').strip()
                if nm:
                    names.add(nm)
            return sorted(names, key=str.lower)

        all_names = _all_customer_names()
        cust_cb = ttk.Combobox(top, textvariable=cust_var, values=all_names, width=28, state='normal')
        cust_cb.pack(side='left', padx=(6, 16))

        # ---- Payment Mode: which mode to mark the SELECTED invoices as
        # once "Apply Payment Mode to Selected" is clicked. ----
        ttk.Label(top, text='Payment Mode').pack(side='left')
        pay_mode_var = tk.StringVar(value=self.PAYMENT_MODES[0])
        pay_mode_cb = ttk.Combobox(
            top, textvariable=pay_mode_var,
            values=list(self.PAYMENT_MODES),
            width=10, state='readonly'
        )
        pay_mode_cb.pack(side='left', padx=(6, 16))

        # ---- Payment Amount: auto-fills with the total of ticked rows,
        # but stays a normal editable box (e.g. partial payment). ----
        ttk.Label(top, text='Payment Amount').pack(side='left')
        payment_amount_var = tk.StringVar(value='0.00')
        payment_amount_entry = ttk.Entry(top, textvariable=payment_amount_var, width=14)
        payment_amount_entry.pack(side='left', padx=(6, 16))

        # Total of ALL this customer's invoices (any Payment Mode). Drops
        # live as rows below get ticked.
        cust_total_var = tk.StringVar(value='Total: ₹0.00')
        ttk.Label(top, textvariable=cust_total_var, font=('Segoe UI', 9, 'bold'),
                  foreground='#B00020').pack(side='left')

        btn_row = ttk.Frame(win)
        btn_row.pack(fill='x', padx=10)

        cols = ('sel', 'number', 'date', 'payment_mode', 'items', 'total')
        heads = {'sel': '✓', 'number': 'Bill No.', 'date': 'Date',
                 'payment_mode': 'Payment Mode', 'items': 'Item', 'total': 'Total (₹)'}
        widths = {'sel': 40, 'number': 110, 'date': 90, 'payment_mode': 110, 'items': 340, 'total': 110}
        # Table + its own vertical scrollbar so every invoice row is reachable.
        tree_wrap = ttk.Frame(win)
        tree_wrap.pack(fill='both', expand=True, padx=10, pady=(6, 4))
        tree = ttk.Treeview(tree_wrap, columns=cols, show='headings', height=17, selectmode='none')
        for k in cols:
            tree.heading(k, text=heads[k])
            tree.column(k, width=widths[k],
                        anchor='center' if k in ('sel', 'date', 'payment_mode', 'total') else 'w')
        tree.tag_configure('picked', background='#FFF59D')   # yellow highlight for ticked rows
        tree.tag_configure('settled', foreground='#888888')  # greyed out - already applied, locked
        stmt_vsb = ttk.Scrollbar(tree_wrap, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=stmt_vsb.set)
        stmt_vsb.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)

        def _stmt_wheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                tree.yview_scroll(-1, 'units')
            elif num == 5:
                tree.yview_scroll(1, 'units')
            else:
                tree.yview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')
            return 'break'
        tree.bind('<MouseWheel>', _stmt_wheel)
        tree.bind('<Button-4>', _stmt_wheel)
        tree.bind('<Button-5>', _stmt_wheel)

        bottom = ttk.Frame(win)
        bottom.pack(fill='x', padx=10, pady=(0, 10))
        selected_count_var = tk.StringVar(value='0 invoice(s) selected')
        ttk.Label(bottom, textvariable=selected_count_var).pack(side='left')
        ttk.Label(bottom, text='(One row per product. Ticking a row ticks the whole invoice. '
                               'An invoice locks ONLY once its Payment Mode is applied from '
                               'here - edit it again to unlock.)',
                  foreground='#666666').pack(side='right')

        # state['rows']         -> invoice_id -> total (₹) of that invoice
        # state['settled']      -> invoice_id -> True if already applied/locked
        # state['checked']      -> set of ticked invoice_ids (only un-locked ones)
        # state['group_of']     -> tree row iid -> the invoice_id it belongs to
        # state['rows_of_group']-> invoice_id -> list of tree row iids (one per item)
        # state['all_total']    -> sum of every invoice of this customer, any mode
        state = {'rows': {}, 'settled': {}, 'checked': set(), 'group_of': {}, 'rows_of_group': {}, 'all_total': 0.0}

        def update_selected_total():
            checked = state['checked']
            tot = sum(state['rows'].get(iid, 0.0) for iid in checked)
            payment_amount_var.set(f'{tot:,.2f}')
            selected_count_var.set(f"{len(checked)} invoice(s) selected")
            remaining = state.get('all_total', 0.0) - tot
            cust_total_var.set(f'Total: ₹{remaining:,.2f}')

        def set_row_checked(inv_id, checked):
            # An invoice already applied/settled from this window stays
            # locked. Every item-row of this invoice is ticked/unticked
            # together, since payment applies to the whole invoice.
            if state['settled'].get(inv_id):
                return
            if checked:
                state['checked'].add(inv_id)
            else:
                state['checked'].discard(inv_id)
            for riid in state['rows_of_group'].get(inv_id, []):
                tree.set(riid, 'sel', '☑' if checked else '☐')
                tree.item(riid, tags=('picked',) if checked else ())

        def toggle_row(row_iid):
            inv_id = state['group_of'].get(row_iid)
            if not inv_id:
                return
            set_row_checked(inv_id, inv_id not in state['checked'])
            update_selected_total()

        def select_all(select):
            for inv_id in list(state['rows'].keys()):
                set_row_checked(inv_id, select)
            update_selected_total()

        def load_for_customer(*_, silent=False):
            for iid in tree.get_children():
                tree.delete(iid)
            state['rows'] = {}
            state['settled'] = {}
            state['checked'] = set()
            state['group_of'] = {}
            state['rows_of_group'] = {}
            state['all_total'] = 0.0
            name = cust_var.get().strip()
            if not name:
                cust_total_var.set('Total: ₹0.00')
                update_selected_total()
                return

            # EVERY invoice of this customer, ONE ROW PER PRODUCT.
            # Typed name: exact match first; if none, any customer whose
            # name CONTAINS the typed text (e.g. "Yash" finds "Yash Traders").
            sql = """
                SELECT i.id AS iid, i.number, i.date, i.payment_mode, i.total,
                       COALESCE(i.settled,0) AS settled,
                       ii.item_name AS item_name
                FROM invoices i
                LEFT JOIN customers cu ON cu.id = i.customer_id
                LEFT JOIN invoice_items ii ON ii.invoice_id = i.id
                WHERE {where}
                ORDER BY i.id DESC, ii.id ASC
                """
            with conn() as c:
                rows = c.execute(
                    sql.format(where="lower(TRIM(cu.name)) = lower(TRIM(?))"),
                    (name,)
                ).fetchall()
                if not rows:
                    rows = c.execute(
                        sql.format(where="lower(cu.name) LIKE '%' || lower(TRIM(?)) || '%'"),
                        (name,)
                    ).fetchall()

            all_total = 0.0
            seen_invoices = set()
            row_seq = 0
            for r in rows:
                inv_id = str(r['iid'])
                tot = float(r['total'] or 0)
                mode = (r['payment_mode'] or '').strip()
                is_settled = bool(int(r['settled'] or 0))
                item_name = r['item_name'] or '(no items)'
                first_of_invoice = inv_id not in seen_invoices

                if first_of_invoice:
                    seen_invoices.add(inv_id)
                    all_total += tot
                    state['rows'][inv_id] = tot
                    state['settled'][inv_id] = is_settled
                    state['rows_of_group'][inv_id] = []

                row_seq += 1
                row_iid = f'{inv_id}_{row_seq}'
                state['group_of'][row_iid] = inv_id
                state['rows_of_group'][inv_id].append(row_iid)

                # Bill No. / Date / Payment Mode on EVERY row (like Challan);
                # the invoice Total only once, on the first row of the invoice.
                tree.insert('', 'end', iid=row_iid, values=(
                    '—' if is_settled else '☐',
                    r['number'] or '',
                    r['date'] or '',
                    mode,
                    item_name,
                    f'{tot:,.2f}' if first_of_invoice else ''
                ))
                if is_settled:
                    tree.item(row_iid, tags=('settled',))

            state['all_total'] = all_total
            update_selected_total()

            if not rows and not silent:
                messagebox.showinfo(
                    'Customer Statement',
                    f'"{name}" has no Invoices yet.',
                    parent=win
                )

        def on_tree_click(event):
            region = tree.identify('region', event.x, event.y)
            if region != 'cell':
                return
            row_id = tree.identify_row(event.y)
            if not row_id:
                return
            toggle_row(row_id)

        ttk.Button(btn_row, text='Select All', command=lambda: select_all(True)).pack(side='left')
        ttk.Button(btn_row, text='Clear Selection', command=lambda: select_all(False)).pack(side='left', padx=(6, 0))
        ttk.Button(btn_row, text='Load', command=load_for_customer).pack(side='left', padx=(6, 0))
        ttk.Button(btn_row, text='✅ Apply Payment Mode to Selected',
                   command=lambda: mark_selected_paid()).pack(side='left', padx=(16, 0))

        def mark_selected_paid():
            mode = pay_mode_var.get().strip()
            if mode not in self.PAYMENT_MODES:
                messagebox.showwarning(
                    'Payment Mode',
                    'Please select one Payment Mode (Cash / Credit / NEFT) from the dropdown above.',
                    parent=win
                )
                return
            checked = list(state['checked'])
            if not checked:
                messagebox.showwarning(
                    'Payment Mode',
                    'Please select at least one Invoice row first (click on it).',
                    parent=win
                )
                return
            with conn() as c:
                for inv_id in checked:
                    # Apply the chosen Payment Mode AND lock the invoice
                    # (settled=1) until it is edited/re-saved elsewhere.
                    c.execute('UPDATE invoices SET payment_mode=?,settled=1 WHERE id=?', (mode, int(inv_id)))
            # Reflect everywhere: main Saved Invoices table, the Customer
            # Total on the main Invoice form, and this window.
            self.load_invoices()
            self._update_customer_total()
            messagebox.showinfo(
                'Payment Updated',
                f'{len(checked)} Invoice(s) updated to Payment Mode "{mode}" successfully.',
                parent=win
            )
            load_for_customer()

        # ---- Type-to-search on the Customer box (live list under it) ----
        typing_job = {'id': None}

        def _stmt_matches():
            typed = cust_var.get().strip()
            if not typed or typed in all_names:
                return []
            return _search_names(all_names, typed)

        def _stmt_pick(name):
            cust_var.set(name)
            cust_cb['values'] = all_names
            load_for_customer()

        stmt_popup = _SuggestPopup(cust_cb, _stmt_matches, _stmt_pick)

        def on_cust_typed(event=None):
            if event is not None and getattr(event, 'keysym', '') in _NAV_KEYS:
                return
            cust_cb['values'] = _search_names(all_names, cust_var.get())
            stmt_popup.refresh()
            # load challans/invoices ~0.4s after the person stops typing
            if typing_job['id'] is not None:
                try:
                    win.after_cancel(typing_job['id'])
                except Exception:
                    pass
            typing_job['id'] = win.after(400, lambda: load_for_customer(silent=True))

        tree.bind('<Button-1>', on_tree_click)
        cust_cb.bind('<KeyRelease>', on_cust_typed, add='+')
        cust_cb.bind('<<ComboboxSelected>>', lambda e: load_for_customer())
        cust_cb.bind('<Return>', lambda e: load_for_customer(), add='+')
        cust_cb.bind('<FocusOut>', lambda e: load_for_customer(silent=True), add='+')

        # If a customer is already selected on the main Invoice screen,
        # open the statement pre-filled for that same customer.
        current_name = self.cust_name.get().strip() if hasattr(self, 'cust_name') else ''
        if current_name:
            cust_var.set(current_name)
            load_for_customer()

        cust_cb.focus_set()