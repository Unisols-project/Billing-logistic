"""
Product Master screen — single dedicated file.

Same style of customization as Customer screen (app/customer_tab.py); the
shared MasterBase used by other master tabs is left untouched.

Customizations:
  1. Export CSV / Save PDF As / Print / WhatsApp / Email buttons removed
     from the top form.
  2. New fields added: Date, Company Name, Buying Price, MRP Rate,
     Wholesale Rate, Quantity, and Amount. These are added automatically
     to the database the first time this screen runs (no separate
     migration step needed).
        - Date: user editable, must be DD-MM-YYYY. (Day/Time fields have
          been removed.)
        - Company Name: editable dropdown — type any company name and
          Save; it then shows up in the dropdown (and on Edit) from then
          on. Use the "+" button next to it to add one without typing it
          into the field first.
        - Unit: editable dropdown with defaults Box, Bag, Bti, Bucket,
          Doz, Gm, Jar, Kg. Same "type it / hit +, then Save" behavior —
          whatever you add shows up in the dropdown afterwards.
        - Amount: auto-calculated as Quantity x Price Per Unit, live,
          as soon as you type either one (read only).
        - Wholesale Rate: plain editable field (no more auto Discount %
          two-way calculation — see removal note below).
        - Total: auto-calculated as Quantity x Wholesale Rate, live, read
          only. This is now the final calculated total shown on the
          screen (see item 8 — AMT is gone).
  3. Quantity, Price Per Unit, Buying Price, MRP Rate, Wholesale Rate and
     Loading only accept numbers (digits and a single decimal point)
     while typing.
  4. The table now has three action columns at the END of every row:
     "Download" (saves that single product's details as a PDF),
     "Edit" (loads that row back into the form for editing), and
     "Delete" (deletes that row, after confirmation).
     A "Delete" button is also available in the form to delete whichever
     record is currently loaded/selected.
  5. GST % / GST Type / Discount % — REMOVED.
  6. GODOWN ITEM MAPPING (GODOWNS ARE GLOBAL): see "+" popup next to
     Item Name. Mapping is stored in `godown_products`.
  7. GODOWN COLUMN IN SAVED PRODUCTS TABLE (read-only, computed live).
  8. WEIGHT KG / AMT — REMOVED.
  9. CATEGORY — REMOVED, GODOWN MOVED INTO ITS SPOT.
  10. GODOWN-FILTERED ITEM NAME LIST — shows finished AND "(pending)"
      items; picking one loads that exact record by id.
  11. TABLE SCROLLING: page scroll wrapper + table vertical/horizontal
      scrollbars. Height set by TABLE_ROWS below.
  12. EDIT FIX (this change): when a row is loaded for editing (via the
      Edit button, or by picking an item from the Item Name dropdown) and
      Save is pressed, THAT SAME ROW is always updated — even if Item
      Name or Unit was changed. Previously, changing Item Name / Unit
      during Edit created a brand-new product row. Now a new row is
      created only when no record is loaded (use "Clear / New" first).
      If the edited Item Name + Unit already belongs to ANOTHER product,
      Save shows a "Duplicate" error instead of creating a mess.
      Edit also now loads values straight from the database (not from the
      table's display text), so blank fields no longer turn into "None".
  13. ONE RECORD = ITEM NAME + UNIT + GODOWN: the same item in two
      different Godowns (or two different items in one Godown) are separate
      rows. Old rows that were mapped to several Godowns are split
      automatically at startup. Changing the Godown while editing MOVES
      that row; use "Clear / New" to add the same item to another Godown.
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime

from app.master_base import MasterBase
from database import conn, ensure_godown
from services.pdf_service import make_report_pdf


class ProductTab(MasterBase):
    table = 'products'
    fields = [
        ('date', 'Date'),
        ('item_name', 'Item Name'),
        ('unit', 'Unit'),
        ('hsn_sac', 'HSN/SAC'),
        ('qty', 'Quantity'),
        ('price', 'Price Per Unit'),
        ('buying_price', 'Buying Price'),
        ('mrp_rate', 'MRP Rate'),
        ('wholesale_rate', 'Wholesale Rate'),
        ('loading', 'Loading'),
        ('total', 'Total'),
        ('company_name', 'Company Name'),
    ]

    NEW_DB_COLUMNS = {'date': 'TEXT', 'qty': 'REAL', 'amount': 'REAL',
                       'company_name': 'TEXT', 'buying_price': 'REAL',
                       'mrp_rate': 'REAL', 'wholesale_rate': 'REAL',
                       'discount_percent': 'REAL', 'total': 'REAL',
                       'category': 'TEXT', 'loading': 'REAL',
                       'gst': 'REAL', 'gst_type': 'TEXT', 'amt': 'REAL',
                       'is_placeholder': 'INTEGER DEFAULT 0'}

    EXTRA_DISPLAY_COLUMNS = [('godown', 'Godown')]

    ACTION_COLUMNS = [('dl', 'Download'), ('edit', 'Edit'), ('delete', 'Delete')]

    READONLY_FIELDS = {'total'}
    DECIMAL_FIELDS = {'qty', 'price', 'buying_price', 'mrp_rate', 'wholesale_rate', 'loading'}

    DEFAULT_UNIT_OPTIONS = ['Box', 'Bag', 'Bti', 'Bucket', 'Doz', 'Gm', 'Jar', 'Kg', 'Nos', 'Piece', 'Ltr', 'Pkt', 'Ton']
    GROWABLE_COMBO_FIELDS = {'company_name': [], 'unit': DEFAULT_UNIT_OPTIONS}

    COMBO_FIELDS = {}

    GODOWN_MARKER = '__godown__'

    PENDING_SUFFIX = '  (pending)'

    # ===== TABLE HEIGHT (number of visible rows) =====================
    TABLE_ROWS = 9
    # ==================================================================

    def __init__(self, parent, app):
        self._ensure_columns()
        self._migrate_hide_blank_placeholders()
        self._ensure_godowns_table()
        self._ensure_product_godown_table()
        self._split_multi_godown_products()
        self.godown_var = tk.StringVar()
        self.godown_combo = None
        self._godown_item_lookup = {}

        self._editing_original_item_name = None
        self._editing_original_unit = None
        # Dedicated id of the row being edited (independent of selected_id).
        self._edit_id = None
        self._editing_original_godown = ''
        # True while a row opened with the table's Edit button is being edited.
        self._edit_locked = False

        super().__init__(parent, app)

    # ---------- Global Godowns table (shared with Challan/Invoice) ----------
    def _ensure_godowns_table(self):
        with conn() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS godowns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )''')

    # ---------- Godown <-> Product mapping table ----------
    def _ensure_product_godown_table(self):
        with conn() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS godown_products(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    godown_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    UNIQUE(godown_id, product_id),
                    FOREIGN KEY(godown_id) REFERENCES godowns(id) ON DELETE CASCADE,
                    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            ''')

    def _split_multi_godown_products(self):
        # A product row now belongs to exactly ONE Godown (Item + Unit +
        # Godown = one record). Old data where one product row was mapped to
        # several Godowns is split here: the first Godown keeps the original
        # row, every other Godown gets its own copy of the row.
        try:
            with conn() as c:
                cols = [r['name'] for r in c.execute(f'PRAGMA table_info({self.table})')
                        if r['name'] != 'id']
                cl = ','.join(cols)
                multi = c.execute(
                    'SELECT product_id FROM godown_products '
                    'GROUP BY product_id HAVING COUNT(*)>1'
                ).fetchall()
                for m in multi:
                    pid = m['product_id']
                    maps = c.execute(
                        'SELECT id FROM godown_products WHERE product_id=? ORDER BY id',
                        (pid,)
                    ).fetchall()
                    for extra in maps[1:]:
                        cur = c.execute(
                            f'INSERT INTO {self.table}({cl}) SELECT {cl} FROM {self.table} WHERE id=?',
                            (pid,)
                        )
                        c.execute('UPDATE godown_products SET product_id=? WHERE id=?',
                                  (cur.lastrowid, extra['id']))
        except sqlite3.Error:
            pass

    def _all_godown_values(self):
        try:
            with conn() as c:
                rows = c.execute("SELECT name FROM godowns ORDER BY name").fetchall()
            return [r['name'] for r in rows]
        except sqlite3.Error:
            return []

    def _godown_id_map(self):
        try:
            with conn() as c:
                rows = c.execute("SELECT id, name FROM godowns ORDER BY name").fetchall()
            return {r['name']: r['id'] for r in rows}
        except sqlite3.Error:
            return {}

    def _godowns_for_products(self, product_ids):
        result = {}
        if not product_ids:
            return result
        try:
            placeholders = ','.join('?' for _ in product_ids)
            with conn() as c:
                rows = c.execute(
                    f'''SELECT gp.product_id AS pid, g.name AS gname
                        FROM godown_products gp
                        JOIN godowns g ON g.id = gp.godown_id
                        WHERE gp.product_id IN ({placeholders})
                        ORDER BY g.name''',
                    list(product_ids)
                ).fetchall()
        except sqlite3.Error:
            return result
        for r in rows:
            result.setdefault(r['pid'], []).append(r['gname'])
        return {pid: ', '.join(names) for pid, names in result.items()}

    def _add_new_godown(self, godown_var, godown_combo):
        name = simpledialog.askstring('Add New Godown', 'Enter new Godown name:', parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        ensure_godown(name)
        vals = self._all_godown_values()
        godown_combo['values'] = vals
        godown_var.set(name)

    # ---------- ONE-TIME DB MIGRATION (products table only) ----------
    def _ensure_columns(self):
        with conn() as c:
            cols = [r['name'] for r in c.execute(f'PRAGMA table_info({self.table})')]
            for col, coltype in self.NEW_DB_COLUMNS.items():
                if col not in cols:
                    c.execute(f'ALTER TABLE {self.table} ADD COLUMN {col} {coltype}')

    def _migrate_hide_blank_placeholders(self):
        check_cols = [k for k, _ in self.fields if k not in ('date', 'item_name')]
        with conn() as c:
            cols = [r['name'] for r in c.execute(f'PRAGMA table_info({self.table})')]
            present = [k for k in check_cols if k in cols]
            if not present:
                return
            blank_clause = ' AND '.join(
                f"({k} IS NULL OR TRIM(CAST({k} AS TEXT))='')" for k in present
            )
            try:
                c.execute(
                    f"UPDATE {self.table} SET is_placeholder=1 "
                    f"WHERE COALESCE(is_placeholder,0)=0 AND {blank_clause}"
                )
            except sqlite3.Error:
                pass

    # ---------- GODOWN HELPERS ----------
    def _set_plain_item_values(self):
        # Plain (non Godown-filtered) Item Name list. Never calls back into
        # _on_main_godown_changed, so it can NOT recurse.
        if getattr(self, 'item_combo', None) is not None:
            self.item_combo['values'] = self._combo_values('item_name')

    def _on_main_godown_changed(self, *args):
        """When a Godown is selected, show every product mapped to it —
        finished AND still-pending (placeholder) ones (see item 10)."""
        if not getattr(self, 'item_combo', None):
            return
        name = self.godown_var.get().strip()
        self._godown_item_lookup = {}
        if not name:
            self._set_plain_item_values()
            return
        gid = self._godown_id_map().get(name)
        if not gid:
            self._set_plain_item_values()
            return
        try:
            with conn() as c:
                rows = c.execute(
                    """SELECT p.id, p.item_name, COALESCE(p.is_placeholder,0) AS is_ph
                       FROM godown_products gp
                       JOIN products p ON p.id=gp.product_id
                       WHERE gp.godown_id=?
                       ORDER BY p.item_name, p.unit, p.id""",
                    (gid,)
                ).fetchall()
            vals = []
            for r in rows:
                nm = r['item_name']
                if not nm:
                    continue
                display = nm + (self.PENDING_SUFFIX if r['is_ph'] else '')
                if display not in vals:
                    vals.append(display)
                self._godown_item_lookup.setdefault(nm, r['id'])
                self._godown_item_lookup.setdefault(display, r['id'])
            self.item_combo['values'] = vals
        except sqlite3.Error:
            self._set_plain_item_values()

    def _on_item_combo_selected(self, event=None):
        """Picking an item from the (Godown-filtered) dropdown loads that
        EXACT product record by id — Unit included."""
        raw = self.vars['item_name'].get().strip()
        if not raw:
            return
        if self._edit_locked:
            # A row is being EDITED (Edit button). Picking a name from the
            # dropdown must only RENAME this row, not load another record
            # (that used to throw away the edit and change the wrong row).
            if raw.endswith(self.PENDING_SUFFIX):
                raw = raw[: -len(self.PENDING_SUFFIX)].strip()
            self.vars['item_name'].set(raw)
            return
        pid = self._godown_item_lookup.get(raw)
        if pid is None:
            # Not in the selected Godown's list. If a Godown is selected this
            # is a NEW item for that Godown -> do not load another Godown's
            # record (that would move it). Without a Godown, load by name.
            if self.godown_var.get().strip():
                return
            try:
                with conn() as c:
                    row = c.execute(
                        """SELECT id FROM products
                           WHERE LOWER(TRIM(item_name))=LOWER(?)
                           ORDER BY COALESCE(is_placeholder,0), id LIMIT 1""",
                        (raw,)
                    ).fetchone()
                pid = row['id'] if row else None
            except sqlite3.Error:
                pid = None
        if pid is not None:
            self._load_product_into_form(pid)
            mapped = self._mapped_godowns_for_product(pid)
            if mapped and not self.godown_var.get().strip():
                self.godown_var.set(mapped[0])
                self._edit_id = pid
                self.selected_id = pid

    def _load_product_into_form(self, product_id):
        """Fill the Details form directly from the products row with this
        id (Unit included), and remember it as the record Save() will
        update. Godown selection itself is left untouched."""
        try:
            with conn() as c:
                row = c.execute(f'SELECT * FROM {self.table} WHERE id=?', (product_id,)).fetchone()
        except sqlite3.Error:
            row = None
        if not row:
            return
        self.selected_id = product_id
        self._edit_id = product_id
        self._editing_original_item_name = str(row['item_name'] or '').strip()
        self._editing_original_unit = str(row['unit'] or 'Nos').strip()
        for key, _ in self.fields:
            if key in row.keys():
                val = row[key]
                self.vars[key].set('' if val is None else val)
        if not self.vars['date'].get():
            self.vars['date'].set(datetime.now().strftime('%d-%m-%Y'))
        if not self.vars['loading'].get():
            self.vars['loading'].set('0')

    def _filter_main_godowns(self, event=None):
        if not self.godown_combo:
            return
        typed = self.godown_var.get().strip().lower()
        vals = self._all_godown_values()
        if typed:
            vals = [v for v in vals if typed in v.lower()]
        self.godown_combo['values'] = vals

    def _add_new_godown_main(self, combo=None):
        name = simpledialog.askstring('Add New Godown', 'Enter new Godown name:', parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        ensure_godown(name)
        vals = self._all_godown_values()
        if combo is None:
            combo = self.godown_combo
        if combo is not None:
            combo['values'] = vals
        self.godown_var.set(name)

    def _mapped_godowns_for_product(self, product_id):
        if not product_id:
            return []
        try:
            with conn() as c:
                rows = c.execute(
                    """SELECT g.name FROM godown_products gp
                       JOIN godowns g ON g.id=gp.godown_id
                       WHERE gp.product_id=? ORDER BY g.name""",
                    (product_id,)
                ).fetchall()
            return [r['name'] for r in rows]
        except sqlite3.Error:
            return []

    # ---------- UI BUILD ----------
    def build(self):
        outer = ttk.Frame(self)
        outer.pack(fill='both', expand=True)

        page_canvas = tk.Canvas(outer, highlightthickness=0)
        page_vsb = ttk.Scrollbar(outer, orient='vertical', command=page_canvas.yview)
        page_canvas.configure(yscrollcommand=page_vsb.set)
        page_vsb.pack(side='right', fill='y')
        page_canvas.pack(side='left', fill='both', expand=True)

        container = ttk.Frame(page_canvas)
        page_window = page_canvas.create_window((0, 0), window=container, anchor='nw')

        def _fit_page(event=None):
            page_canvas.itemconfig(page_window, width=page_canvas.winfo_width())
            page_canvas.configure(scrollregion=page_canvas.bbox('all'))

        container.bind('<Configure>', _fit_page)
        page_canvas.bind('<Configure>', _fit_page)

        def _page_wheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                page_canvas.yview_scroll(-1, 'units')
            elif num == 5:
                page_canvas.yview_scroll(1, 'units')
            else:
                page_canvas.yview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')

        def _bind_page_wheel(_):
            page_canvas.bind_all('<MouseWheel>', _page_wheel)
            page_canvas.bind_all('<Button-4>', _page_wheel)
            page_canvas.bind_all('<Button-5>', _page_wheel)

        def _unbind_page_wheel(_):
            page_canvas.unbind_all('<MouseWheel>')
            page_canvas.unbind_all('<Button-4>')
            page_canvas.unbind_all('<Button-5>')

        page_canvas.bind('<Enter>', _bind_page_wheel)
        page_canvas.bind('<Leave>', _unbind_page_wheel)

        form = ttk.LabelFrame(container, text='Details')
        form.pack(fill='x', padx=8, pady=8)
        self.combo_widgets = {}

        self.godown_var.trace_add('write', self._on_main_godown_changed)

        layout = list(self.fields)
        layout.insert(1, (self.GODOWN_MARKER, 'Godown'))

        for i, (key, label) in enumerate(layout):
            row = (i // 4) * 2
            col = i % 4

            ttk.Label(form, text=label).grid(row=row, column=col, padx=6, pady=(6, 0), sticky='w')

            if key == self.GODOWN_MARKER:
                cell = ttk.Frame(form)
                combo = ttk.Combobox(cell, textvariable=self.godown_var, width=22, state='normal')
                combo.pack(side='left', fill='x', expand=True)
                combo['values'] = self._all_godown_values()
                ttk.Button(cell, text='+', width=2,
                           command=lambda c=None: self._add_new_godown_main()).pack(side='left', padx=(4, 0))
                combo.bind('<KeyRelease>', self._filter_main_godowns)
                combo.bind('<<ComboboxSelected>>', lambda e: self._filter_main_godowns())
                self.godown_combo = combo
                entry = cell
            else:
                v = tk.StringVar()
                self.vars[key] = v
                if key == 'item_name':
                    cell = ttk.Frame(form)
                    combo = ttk.Combobox(cell, textvariable=v, values=self._combo_values(key), width=22)
                    combo.pack(side='left', fill='x', expand=True)
                    ttk.Button(cell, text='+', width=2,
                               command=self.open_item_mapping).pack(side='left', padx=(4, 0))
                    combo.bind('<<ComboboxSelected>>', self._on_item_combo_selected)
                    self.item_combo = combo
                    entry = cell
                elif key in self.GROWABLE_COMBO_FIELDS:
                    cell = ttk.Frame(form)
                    combo = ttk.Combobox(cell, textvariable=v, values=self._combo_values(key), width=22)
                    combo.pack(side='left', fill='x', expand=True)
                    ttk.Button(cell, text='+', width=2,
                               command=lambda k=key, c=combo: self._add_combo_value(k, c)).pack(side='left', padx=(4, 0))
                    self.combo_widgets[key] = combo
                    entry = cell
                elif key in self.COMBO_FIELDS:
                    options, default = self.COMBO_FIELDS[key]
                    v.set(default)
                    entry = ttk.Combobox(form, textvariable=v, values=options, width=26, state='readonly')
                elif key in self.DECIMAL_FIELDS:
                    vcmd = (self.register(self._validate_decimal), '%P')
                    entry = ttk.Entry(form, textvariable=v, width=28, validate='key', validatecommand=vcmd)
                else:
                    entry = ttk.Entry(form, textvariable=v, width=28)
                if key in self.READONLY_FIELDS:
                    entry.configure(state='readonly')

            entry.grid(row=row + 1, column=col, padx=6, pady=(0, 6), sticky='ew')

        self.vars['qty'].trace_add('write', self._recalc_total)
        self.vars['price'].trace_add('write', self._recalc_total)
        self.vars['buying_price'].trace_add('write', self._recalc_total)
        self.vars['mrp_rate'].trace_add('write', self._recalc_total)
        self.vars['wholesale_rate'].trace_add('write', self._recalc_total)
        self.vars['loading'].trace_add('write', self._recalc_total)

        btn_row = ((len(layout) - 1) // 4 + 1) * 2 + 2
        ttk.Button(form, text='Save', command=self.save).grid(row=btn_row, column=0, padx=6, pady=6)
        ttk.Button(form, text='Clear / New', command=self.clear).grid(row=btn_row, column=1, padx=6, pady=6)
        ttk.Button(form, text='Delete', command=self.delete_selected).grid(row=btn_row, column=2, padx=6, pady=6)
        self.search_var = tk.StringVar()
        ttk.Label(form, text='Search').grid(row=btn_row, column=3, padx=6, pady=6, sticky='e')
        ttk.Entry(form, textvariable=self.search_var, width=24).grid(row=btn_row, column=4, padx=6, pady=6)
        ttk.Button(form, text='Search', command=self.load).grid(row=btn_row + 1, column=0, padx=6, pady=6)

        display_field_order = [
            'date', 'item_name', 'unit', 'godown',
            'company_name', 'hsn_sac',
            'qty', 'price', 'buying_price', 'mrp_rate',
            'wholesale_rate', 'loading', 'total'
        ]
        self.tree_columns = display_field_order + [k for k, _ in self.ACTION_COLUMNS]

        listf = ttk.LabelFrame(container, text='Products')
        listf.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        table_area = ttk.Frame(listf)
        table_area.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        self.tree = ttk.Treeview(
            table_area,
            columns=self.tree_columns,
            show='headings',
            height=self.TABLE_ROWS
        )
        labels = dict(self.fields)
        labels['godown'] = 'Godown'
        for k in self.tree_columns:
            if k in ('dl', 'edit', 'delete'):
                continue
            self.tree.heading(k, text=labels.get(k, k.title()))
            self.tree.column(
                k,
                width=160 if k == 'godown' else (180 if k == 'item_name' else 110),
                stretch=False
            )
        for k, l in self.ACTION_COLUMNS:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=90, anchor='center', stretch=False)

        vsb = ttk.Scrollbar(table_area, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(listf, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        hsb.pack(fill='x', padx=6, pady=(0, 6))

        def _tree_vwheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                self.tree.yview_scroll(-1, 'units')
            elif num == 5:
                self.tree.yview_scroll(1, 'units')
            else:
                self.tree.yview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')
            return 'break'

        def _tree_hwheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                self.tree.xview_scroll(-1, 'units')
            elif num == 5:
                self.tree.xview_scroll(1, 'units')
            else:
                self.tree.xview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')
            return 'break'

        self.tree.bind('<MouseWheel>', _tree_vwheel)
        self.tree.bind('<Shift-MouseWheel>', _tree_hwheel)
        self.tree.bind('<Button-4>', _tree_vwheel)
        self.tree.bind('<Button-5>', _tree_vwheel)
        self.tree.bind('<Shift-Button-4>', _tree_hwheel)
        self.tree.bind('<Shift-Button-5>', _tree_hwheel)

        self.tree.bind('<Button-1>', self.on_tree_click)

        self._set_auto_datetime()

    def open_item_mapping(self):
        """Map existing Product Master products to a selected global Godown.

        Unit is NOT entered here. Unit belongs to Product Master and is shown
        automatically beside every product in the picker/list.
        """
        win = tk.Toplevel(self)
        win.title("Godown Wise Items")
        win.geometry("720x650")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ttk.Label(win, text="Godown (global list — searchable)").pack(anchor="w", padx=12, pady=(12, 3))
        picker_row = ttk.Frame(win)
        picker_row.pack(fill="x", padx=12)
        godown_var = tk.StringVar()
        godown_combo = ttk.Combobox(picker_row, textvariable=godown_var, width=48, state='normal')
        godown_combo.pack(side="left", fill="x", expand=True)
        godown_combo['values'] = self._all_godown_values()
        ttk.Button(picker_row, text='+', width=2, command=lambda: self._add_new_godown_main(godown_combo)).pack(side="left", padx=(4, 0))

        ttk.Label(win, text="Add existing Product Master item to THIS godown — Unit comes automatically from Product Master:").pack(anchor="w", padx=12, pady=(10, 3))
        add_item_row = ttk.Frame(win)
        add_item_row.pack(fill="x", padx=12)
        product_var = tk.StringVar()
        product_combo = ttk.Combobox(add_item_row, textvariable=product_var, width=58, state='normal')
        product_combo.pack(side="left", fill="x", expand=True)

        ttk.Label(win, text="Items in THIS godown only (Item Name + Unit — pending ones still need details filled in Product Master):").pack(anchor="w", padx=12, pady=(10, 3))
        listbox = tk.Listbox(win, selectmode="browse", height=17, exportselection=False, font=("Segoe UI", 10))
        listbox.pack(fill="both", expand=True, padx=12, pady=4)

        product_map = {}
        item_ids = []

        def all_product_options():
            product_map.clear()
            options = []
            with conn() as c:
                rows = c.execute(
                    """SELECT id, item_name, COALESCE(unit, 'Nos') AS unit
                       FROM products
                       WHERE COALESCE(is_placeholder,0)=0
                       ORDER BY item_name, unit, id"""
                ).fetchall()
            for r in rows:
                display = f"{r['item_name']}    |    Unit: {r['unit']}"
                product_map[display] = {'id': r['id'], 'name': r['item_name'], 'unit': r['unit'] or 'Nos'}
                options.append(display)
            return options

        all_options = all_product_options()
        product_combo['values'] = all_options

        def filter_product_options(event=None):
            typed = product_var.get().strip().lower()
            vals = all_options if not typed else [v for v in all_options if typed in v.lower()]
            product_combo['values'] = vals

        def current_godown_name():
            return godown_var.get().strip()

        def load_godown_items():
            listbox.delete(0, "end")
            item_ids.clear()
            name = current_godown_name()
            if not name:
                return
            gid = self._godown_id_map().get(name)
            if not gid:
                return
            with conn() as c:
                rows = c.execute(
                    """SELECT p.id, p.item_name, COALESCE(p.unit, 'Nos') AS unit,
                              COALESCE(p.is_placeholder,0) AS is_ph
                       FROM godown_products gp
                       JOIN products p ON p.id = gp.product_id
                       WHERE gp.godown_id=?
                       ORDER BY LOWER(p.item_name), LOWER(COALESCE(p.unit, 'Nos')), p.id""",
                    (gid,)
                ).fetchall()
            for r in rows:
                display = f"{r['item_name']}    |    Unit: {r['unit']}"
                if r['is_ph']:
                    display += self.PENDING_SUFFIX
                item_ids.append(int(r['id']))
                listbox.insert("end", display)
            listbox.selection_clear(0, 'end')

        def add_existing_product(event=None):
            godown = current_godown_name()
            if not godown:
                return messagebox.showerror("Required", "आधी Godown निवडा", parent=win)

            display = product_var.get().strip()
            if not display:
                return messagebox.showerror("Required", "Product Name टाका", parent=win)

            rec = product_map.get(display)
            if not rec:
                for key, value in product_map.items():
                    if key.strip().lower() == display.lower():
                        rec = value
                        display = key
                        break

            item_name = rec['name'] if rec else display
            try:
                unit = (rec['unit'] if rec else None) or self.vars['unit'].get().strip() or 'Nos'
            except Exception:
                unit = (rec['unit'] if rec else None) or 'Nos'
            today = datetime.now().strftime('%d-%m-%Y')

            try:
                with conn() as c:
                    grow = c.execute(
                        'SELECT id FROM godowns WHERE lower(name)=lower(?)', (godown,)
                    ).fetchone()
                    if not grow:
                        c.execute('INSERT INTO godowns(name) VALUES(?)', (godown,))
                        grow = c.execute(
                            'SELECT id FROM godowns WHERE lower(name)=lower(?)', (godown,)
                        ).fetchone()
                    gid = grow['id']

                    product_id = rec['id'] if rec else None
                    if product_id is not None:
                        prow = c.execute(
                            'SELECT id, item_name, COALESCE(unit, "Nos") AS unit FROM products WHERE id=?',
                            (product_id,)
                        ).fetchone()
                        if not prow:
                            product_id = None

                    if product_id is not None:
                        # Already in ANOTHER godown? Then it must not be shared:
                        # a separate record is used/created for THIS godown.
                        other = c.execute(
                            'SELECT 1 FROM godown_products WHERE product_id=? AND godown_id<>? LIMIT 1',
                            (product_id, gid)
                        ).fetchone()
                        if other:
                            product_id = None

                    if product_id is None:
                        row = c.execute(
                            f"""SELECT id, item_name, COALESCE(unit, 'Nos') AS unit
                                FROM {self.table}
                                WHERE LOWER(TRIM(item_name))=LOWER(?)
                                  AND LOWER(TRIM(COALESCE(unit, 'Nos')))=LOWER(?)
                                  AND (id IN (SELECT product_id FROM godown_products WHERE godown_id=?)
                                       OR id NOT IN (SELECT product_id FROM godown_products))
                                ORDER BY id LIMIT 1""",
                            (item_name, unit, gid)
                        ).fetchone()
                        if row:
                            product_id = row['id']
                            actual_unit = row['unit'] or unit
                        else:
                            cur = c.execute(
                                f"""INSERT INTO {self.table}
                                    (item_name, unit, date, is_placeholder)
                                    VALUES(?, ?, ?, 1)""",
                                (item_name, unit, today)
                            )
                            product_id = cur.lastrowid
                            actual_unit = unit
                        display = f"{item_name}    |    Unit: {actual_unit}"
                        rec = {'id': product_id, 'name': item_name, 'unit': actual_unit}
                        product_map[display] = rec
                        if display not in all_options:
                            all_options.append(display)
                        product_combo['values'] = all_options

                    c.execute(
                        """INSERT OR IGNORE INTO godown_products(godown_id, product_id)
                           VALUES(?, ?)""",
                        (gid, product_id)
                    )
            except sqlite3.Error as e:
                return messagebox.showerror(
                    "Product Add Error", f"Product add करता आला नाही.\n{e}", parent=win
                )

            if int(rec['id']) not in item_ids:
                item_ids.append(int(rec['id']))
                listbox.insert("end", display)

            product_var.set("")
            product_combo['values'] = all_options
            product_combo.focus_set()

        def remove_selected(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            idx = int(sel[0])
            listbox.delete(idx)
            if 0 <= idx < len(item_ids):
                item_ids.pop(idx)

        def save_mapping():
            godown = current_godown_name()
            if not godown:
                return messagebox.showerror("Required", "Godown निवडा", parent=win)
            gid = ensure_godown(godown)
            with conn() as c:
                c.execute("DELETE FROM godown_products WHERE godown_id=?", (gid,))
                for pid in item_ids:
                    prow = c.execute('SELECT id FROM products WHERE id=?', (pid,)).fetchone()
                    if not prow:
                        continue
                    c.execute(
                        """INSERT OR IGNORE INTO godown_products(godown_id, product_id)
                           VALUES(?, ?)""",
                        (gid, pid)
                    )
            self._refresh_item_combo()
            self.load()
            win.destroy()

        initial_godown = self.godown_var.get().strip() if hasattr(self, 'godown_var') else ''
        if initial_godown in self._all_godown_values():
            godown_var.set(initial_godown)

        godown_combo.bind("<<ComboboxSelected>>", lambda e: load_godown_items())
        godown_combo.bind("<Return>", lambda e: load_godown_items())
        godown_combo.bind("<FocusOut>", lambda e: load_godown_items())
        load_godown_items()
        product_combo.bind("<KeyRelease>", filter_product_options)
        product_combo.bind("<Return>", add_existing_product)
        listbox.bind("<Double-Button-1>", remove_selected)
        ttk.Button(add_item_row, text="Add Item", command=add_existing_product).pack(side="left", padx=(6, 0))

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="Remove Selected", command=remove_selected).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Save", command=save_mapping).pack(side="left", padx=4)

    def _validate_decimal(self, proposed):
        if proposed == '':
            return True
        if proposed.count('.') > 1:
            return False
        return all(ch.isdigit() or ch == '.' for ch in proposed)

    def _recalc_total(self, *args):
        # Total = Quantity x (Price Per Unit + Buying Price + MRP Rate
        #                    + Wholesale Rate + Loading)
        try:
            qty = float(self.vars['qty'].get() or 0)
            price = float(self.vars['price'].get() or 0)
            buying = float(self.vars['buying_price'].get() or 0)
            mrp = float(self.vars['mrp_rate'].get() or 0)
            wholesale = float(self.vars['wholesale_rate'].get() or 0)
            loading = float(self.vars['loading'].get() or 0)

            if min(buying, mrp, wholesale, loading) < 0:
                self._set_readonly('total', '0.00')
                return

            total = qty * (price + buying + mrp + wholesale + loading)
            self._set_readonly('total', f'{total:.2f}')
        except (ValueError, TypeError):
            self._set_readonly('total', '0.00')

    def _combo_values(self, key):
        seed = self.GROWABLE_COMBO_FIELDS.get(key, [])
        db_vals = []
        try:
            with conn() as c:
                rows = c.execute(
                    f'SELECT DISTINCT {key} FROM {self.table} '
                    f'WHERE {key} IS NOT NULL AND TRIM({key}) != "" ORDER BY {key}'
                )
                db_vals = [r[0] for r in rows]
        except sqlite3.Error:
            pass
        return list(dict.fromkeys(list(seed) + db_vals))

    def _add_combo_value(self, key, combo_widget):
        label = dict(self.fields).get(key, key)
        val = simpledialog.askstring(f'Add {label}', f'Enter new {label}:')
        if not val:
            return
        val = val.strip()
        if not val:
            return
        current = list(combo_widget['values'])
        if val not in current:
            current.append(val)
            combo_widget['values'] = current
        self.vars[key].set(val)

    def _refresh_growable_combos(self):
        for key, combo in self.combo_widgets.items():
            combo['values'] = self._combo_values(key)

    def _refresh_item_combo(self):
        # Godown selected (and it exists) -> Godown-filtered list, otherwise
        # plain list. _on_main_godown_changed never calls this any more, so
        # there is no recursion.
        if self.godown_var.get().strip():
            self._on_main_godown_changed()
        else:
            self._set_plain_item_values()

    def _add_item_combo_value(self, name):
        if not hasattr(self, 'item_combo') or not name:
            return
        current = list(self.item_combo['values'])
        if name not in current:
            current.append(name)
            self.item_combo['values'] = current

    def _set_readonly(self, key, value):
        self.vars[key].set(value)

    def _set_auto_datetime(self):
        now = datetime.now()
        self.vars['date'].set(now.strftime('%d-%m-%Y'))
        for key, (_, default) in self.COMBO_FIELDS.items():
            self.vars[key].set(default)
        if not self.vars['loading'].get():
            self.vars['loading'].set('0')

    # ---------- DATA ----------
    def clear(self):
        for v in self.vars.values():
            v.set('')
        if hasattr(self, 'godown_var'):
            self.godown_var.set('')
        if hasattr(self, 'godown_combo') and self.godown_combo is not None:
            self.godown_combo['values'] = self._all_godown_values()
        self.selected_id = None
        self._edit_id = None
        self._edit_locked = False
        self._editing_original_godown = ''
        self._editing_original_item_name = None
        self._editing_original_unit = None
        self._set_auto_datetime()

    def load(self):
        for x in self.tree.get_children():
            self.tree.delete(x)
        self.current_rows = []
        term = self.search_var.get().strip().lower() if hasattr(self, 'search_var') else ''
        with conn() as c:
            db_rows = list(c.execute(
                f'SELECT * FROM {self.table} WHERE COALESCE(is_placeholder,0)=0 ORDER BY id DESC'
            ))
        godown_map = self._godowns_for_products([r['id'] for r in db_rows])
        for r in db_rows:
            row = {k: r[k] for k, _ in self.fields}
            godown_str = godown_map.get(r['id'], '')
            if term and term not in (' '.join(str(v or '').lower() for v in row.values()) + ' ' + godown_str.lower()):
                continue
            self.current_rows.append(row)
            display_values = [
                r['date'],
                r['item_name'],
                r['unit'],
                godown_str,
                r['company_name'],
                r['hsn_sac'],
                r['qty'],
                r['price'],
                r['buying_price'],
                r['mrp_rate'],
                r['wholesale_rate'],
                r['loading'],
                r['total'],
                '⬇ Download',
                '✎ Edit',
                '🗑 Delete'
            ]
            self.tree.insert(
                '', 'end', iid=str(r['id']),
                values=display_values,
            )
        if hasattr(self, 'combo_widgets'):
            self._refresh_growable_combos()
        self._refresh_item_combo()

    def save(self):
        keys = [k for k, _ in self.fields]
        raw_item_name = self.vars['item_name'].get().strip()
        if raw_item_name.endswith(self.PENDING_SUFFIX):
            raw_item_name = raw_item_name[: -len(self.PENDING_SUFFIX)].strip()
            self.vars['item_name'].set(raw_item_name)

        vals = [self.vars[k].get().strip() for k in keys]
        by_key = dict(zip(keys, vals))

        if not by_key['item_name']:
            return messagebox.showerror('Required', 'Item Name is required')

        by_key['unit'] = (by_key.get('unit') or 'Nos').strip()

        if not by_key['date']:
            return messagebox.showerror('Required', 'Date is required')
        try:
            datetime.strptime(by_key['date'], '%d-%m-%Y')
        except ValueError:
            return messagebox.showerror('Invalid Date', 'Date must be in DD-MM-YYYY format')

        try:
            qty = float(by_key.get('qty', '') or 0)
            price = float(by_key.get('price', '') or 0)
            buying = float(by_key.get('buying_price', '') or 0)
            mrp = float(by_key.get('mrp_rate', '') or 0)
            wholesale = float(by_key.get('wholesale_rate', '') or 0)
            loading = float(by_key.get('loading', '') or 0)

            if min(buying, mrp, wholesale, loading) < 0:
                return messagebox.showerror(
                    'Invalid Value',
                    'Buying Price, MRP Rate, Wholesale Rate and Loading cannot be negative'
                )

            by_key['buying_price'] = f'{buying:.2f}'
            by_key['mrp_rate'] = f'{mrp:.2f}'
            by_key['wholesale_rate'] = f'{wholesale:.2f}'
            by_key['loading'] = f'{loading:.2f}'
            by_key['total'] = f'{qty * (price + buying + mrp + wholesale + loading):.2f}'
        except (ValueError, TypeError):
            return messagebox.showerror('Invalid Value', 'Please enter valid numeric values')

        vals = [by_key[k] for k in keys]

        godown_name = self.godown_var.get().strip() if hasattr(self, 'godown_var') else ''

        with conn() as c:
            target_id = self._edit_id or self.selected_id

            # ONE product record = Item Name + Unit + Godown.
            if godown_name:
                gclause = ('AND p.id IN (SELECT gp.product_id FROM godown_products gp '
                           'JOIN godowns g ON g.id=gp.godown_id WHERE lower(g.name)=lower(?))')
                gparams = [godown_name]
            else:
                gclause = 'AND p.id NOT IN (SELECT product_id FROM godown_products)'
                gparams = []

            dup_sql = (
                f"""SELECT p.id FROM {self.table} p
                    WHERE LOWER(TRIM(p.item_name))=LOWER(?)
                      AND LOWER(TRIM(COALESCE(p.unit,'Nos')))=LOWER(?)
                      AND COALESCE(p.is_placeholder,0)=0 {gclause}"""
            )
            dup_params = [by_key['item_name'], by_key['unit']] + gparams
            if target_id:
                dup_sql += ' AND p.id<>?'
                dup_params.append(target_id)
            if c.execute(dup_sql, dup_params).fetchone():
                return messagebox.showerror(
                    'Duplicate',
                    'This Item Name + Unit already exists in this Godown.'
                    if godown_name else
                    'This Item Name + Unit already exists (without a Godown).'
                )

            sets = ','.join(f'{k}=?' for k in keys)
            if target_id:
                # EDIT: always update the SAME row (name / unit / godown / qty ...)
                c.execute(
                    f'UPDATE {self.table} SET {sets}, is_placeholder=0 WHERE id=?',
                    vals + [target_id]
                )
            else:
                # NEW: complete a pending placeholder of the same
                # Item + Unit + Godown, otherwise insert a new row.
                ph_sql = (
                    f"""SELECT p.id FROM {self.table} p
                        WHERE p.is_placeholder=1
                          AND LOWER(TRIM(p.item_name))=LOWER(?)
                          AND LOWER(TRIM(COALESCE(p.unit,'Nos')))=LOWER(?) {gclause}
                        ORDER BY p.id LIMIT 1"""
                )
                row = c.execute(ph_sql, [by_key['item_name'], by_key['unit']] + gparams).fetchone()
                if row:
                    target_id = row['id']
                    c.execute(
                        f'UPDATE {self.table} SET {sets}, is_placeholder=0 WHERE id=?',
                        vals + [target_id]
                    )
                else:
                    cur = c.execute(
                        f'INSERT INTO {self.table}({",".join(keys)}) '
                        f'VALUES({",".join("?" for _ in keys)})',
                        vals
                    )
                    target_id = cur.lastrowid

            # A record belongs to exactly one Godown: replace its mapping.
            c.execute('DELETE FROM godown_products WHERE product_id=?', (target_id,))
            if godown_name:
                grow = c.execute(
                    'SELECT id FROM godowns WHERE lower(name)=lower(?)', (godown_name,)
                ).fetchone()
                if not grow:
                    c.execute('INSERT INTO godowns(name) VALUES(?)', (godown_name,))
                    grow = c.execute(
                        'SELECT id FROM godowns WHERE lower(name)=lower(?)', (godown_name,)
                    ).fetchone()
                c.execute(
                    'INSERT OR IGNORE INTO godown_products(godown_id, product_id) VALUES(?, ?)',
                    (grow['id'], target_id)
                )

        self.clear()
        self.load()

    def delete_selected(self):
        if not self.selected_id:
            return messagebox.showerror('Delete', 'Load a record first (click Edit on a row, or select one)')
        self._delete_by_id(self.selected_id)

    # ---------- ROW ACTIONS (Download / Edit / Delete buttons in the table) ----------
    def on_tree_click(self, event):
        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        col_index = int(col.replace('#', '')) - 1
        if col_index < 0 or col_index >= len(self.tree_columns):
            return
        col_name = self.tree_columns[col_index]
        if col_name == 'dl':
            self.download_row(row_id)
        elif col_name == 'edit':
            self.edit_row(row_id)
        elif col_name == 'delete':
            self.delete_row(row_id)

    def edit_row(self, row_id):
        product_id = int(row_id)
        # Load straight from the database (no "None" text, exact record).
        self._load_product_into_form(product_id)

        mapped = self._mapped_godowns_for_product(product_id)
        self.godown_var.set(mapped[0] if mapped else '')
        if self.godown_combo is not None:
            self.godown_combo['values'] = self._all_godown_values()
        # Make sure Save updates THIS row.
        self.selected_id = product_id
        self._edit_id = product_id
        self._edit_locked = True
        self._editing_original_godown = mapped[0] if mapped else ''

    def download_row(self, row_id):
        idx = self.tree.index(row_id)
        if idx >= len(self.current_rows):
            return
        row = self.current_rows[idx]
        safe_name = ''.join(ch for ch in str(row.get('item_name', 'product')) if ch.isalnum() or ch in (' ', '_', '-')).strip() or 'product'
        path = filedialog.asksaveasfilename(
            defaultextension='.pdf', filetypes=[('PDF', '*.pdf')],
            initialfile=f'{safe_name}.pdf',
        )
        if not path:
            return
        make_report_pdf('Product Details', [k for k, _ in self.fields], [row], path)
        messagebox.showinfo('Downloaded', path)

    def delete_row(self, row_id):
        self._delete_by_id(row_id)

    def _delete_by_id(self, row_id):
        if not messagebox.askyesno('Delete', 'Delete this product record? This cannot be undone.'):
            return
        try:
            with conn() as c:
                c.execute(f'DELETE FROM {self.table} WHERE id=?', (row_id,))
        except sqlite3.IntegrityError:
            return messagebox.showerror(
                'Cannot Delete',
                'This product is already used in one or more Quotation / Challan / Invoice records, '
                'so it cannot be deleted.'
            )
        if self.selected_id and str(self.selected_id) == str(row_id):
            self.clear()
        self.load()

    def pick_row(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.edit_row(sel[0])