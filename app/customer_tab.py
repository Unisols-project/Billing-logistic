"""
Customer Master screen — single dedicated file.

Everything customer-specific lives here only; the shared MasterBase (used by
Product/Route/other master tabs) is left untouched.

Customer-only customizations:
  1. Export CSV / Save PDF As / Print / WhatsApp / Email buttons removed
     from the top form.
  2. New fields added: Date, District, Pin Code, Phone No, Customer Type,
     Rate Type (in addition to the existing Name, Address, Contact No,
     Email, State, GSTIN, Contact Person). These are added automatically
     to the database the first time this screen runs (no separate
     migration step needed).
        - Date: user editable, must be DD-MM-YYYY. (Day/Time fields have
          been removed.)
        - Customer Type: dropdown — Regular / URD / Composition.
          Defaults to "Regular". Optional — can be left as-is or changed;
          saving works either way.
        - Rate Type: dropdown — Wholesale / Retail / M.R.P.
          Defaults to "Wholesale". Optional — saving works either way.
  3. Contact No and Phone No are restricted to digits only while typing
     (max 10 digits) and validated again on Save (must be exactly 10 digits
     if filled in — both fields are now optional; leaving either blank
     never blocks Save). Pin Code is restricted to 6 digits.
  4. The table now has three action columns at the END of every row:
     "Download" (saves that single customer's details as a PDF),
     "Edit" (loads that row back into the form for editing), and
     "Delete" (deletes that row, after confirmation).
     A "Delete" button is also available in the form to delete whichever
     record is currently loaded/selected.
  5. GODOWN REMOVED FROM THIS SCREEN: Godowns are now a single GLOBAL
     list (see the `godowns` table in database.py), completely
     independent of any one Customer. The old per-customer Godown field,
     the "+" bulk-add-godowns popup, and the customer_godowns linking
     logic have all been removed from this screen. The old
     customer_godowns table itself is left in the database, untouched.
  6. TABLE SCROLLING (this change): the results table has a vertical
     scrollbar (right) AND a horizontal scrollbar (bottom line). Both
     scrollbars are packed BEFORE the table, so they always get their
     space and can never be pushed off-screen by the table's height.
     The table height is also reduced (8 rows) so the whole table +
     its bottom scrollbar line fits on the screen under the form.
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime

from app.master_base import MasterBase
from database import conn
from services.pdf_service import make_report_pdf


class CustomerTab(MasterBase):
    table = 'customers'
    fields = [
        ('date', 'Date'),
        ('name', 'Name'),
        ('category', 'Category'),
        ('address', 'Address'),
        ('contact_no', 'Contact No'),
        ('email', 'Email'),
        ('state', 'State'),
        ('district', 'District'),
        ('pincode', 'Pin Code'),
        ('gstin', 'GSTIN'),
        ('contact_person', 'Contact Person'),
        ('phone_no', 'Phone No'),
        ('customer_type', 'Customer Type'),
        ('rate_type', 'Rate Type'),
    ]

    # Columns not stored directly the old way; these are new DB columns
    # this screen needs. Added automatically if missing (no other table
    # is touched).
    NEW_DB_COLUMNS = {'date': 'TEXT',
                       'district': 'TEXT', 'pincode': 'TEXT', 'phone_no': 'TEXT',
                       'customer_type': 'TEXT', 'rate_type': 'TEXT', 'category': 'TEXT'}

    # ===== TABLE HEIGHT (number of visible rows) =====================
    # Change ONLY this number to make the table taller / shorter:
    #   - scroll line is hidden / cut off at the bottom  -> make it SMALLER (e.g. 5)
    #   - empty grey space under the table                -> make it BIGGER  (e.g. 9)
    TABLE_ROWS = 9
    # =================================================================

    # Extra columns shown at the END of the table for row actions.
    ACTION_COLUMNS = [('dl', 'Download'), ('edit', 'Edit'), ('delete', 'Delete')]

    READONLY_FIELDS = set()
    DIGIT_FIELDS = {'contact_no': 10, 'phone_no': 10, 'pincode': 6}

    # Dropdown fields: key -> (options, default value). These render as
    # readonly comboboxes (fixed list — can't type a new value). Both are
    # optional — leaving the default (or any picked value) never blocks Save.
    COMBO_FIELDS = {
        'customer_type': (['Regular', 'URD', 'Composition'], 'Regular'),
        'rate_type': (['Default', 'Wholesale', 'Retail', 'M.R.P.'], 'Default'),
    }

    # Editable/typeable dropdowns: typing a brand-new value and Saving makes
    # it show up in the dropdown (and on Edit) from then on — a "+" button
    # next to the field also lets you add one without typing it in first.
    # Values are pulled live from what's already saved in this table, on
    # top of these seed options.
    DEFAULT_CATEGORY_OPTIONS = ['Retail', 'Wholesale', 'Corporate', 'Government', 'Individual', 'Other']
    GROWABLE_COMBO_FIELDS = {'category': DEFAULT_CATEGORY_OPTIONS}

    def __init__(self, parent, app):
        self._ensure_columns()
        super().__init__(parent, app)

    # ---------- ONE-TIME DB MIGRATION (customer table only) ----------
    def _ensure_columns(self):
        with conn() as c:
            cols = [r['name'] for r in c.execute(f'PRAGMA table_info({self.table})')]
            for col, coltype in self.NEW_DB_COLUMNS.items():
                if col not in cols:
                    c.execute(f'ALTER TABLE {self.table} ADD COLUMN {col} {coltype}')

    # ---------- UI BUILD ----------
    def build(self):
        # --- Scrollable page wrapper (same as the Invoice page) so the table
        # and its scrollbar line are ALWAYS reachable, even on a small screen.
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
            # Page keeps its NATURAL height (so the table + its scroll line
            # never get pushed out of the window); only the width follows
            # the window. If the window is short the page scrolls.
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

        for i, (key, label) in enumerate(self.fields):
            ttk.Label(form, text=label).grid(row=i // 4 * 2, column=i % 4, padx=6, pady=(6, 0), sticky='w')
            v = tk.StringVar()
            self.vars[key] = v
            if key in self.GROWABLE_COMBO_FIELDS:
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
            elif key in self.DIGIT_FIELDS:
                maxlen = self.DIGIT_FIELDS[key]
                vcmd = (self.register(self._make_digit_validator(maxlen)), '%P')
                entry = ttk.Entry(form, textvariable=v, width=28, validate='key', validatecommand=vcmd)
            else:
                entry = ttk.Entry(form, textvariable=v, width=28)
            if key in self.READONLY_FIELDS:
                entry.configure(state='readonly')
            entry.grid(row=i // 4 * 2 + 1, column=i % 4, padx=6, pady=(0, 6), sticky='ew')

        btn_row = ((len(self.fields) - 1) // 4 + 1) * 2
        ttk.Button(form, text='Save', command=self.save).grid(row=btn_row, column=0, padx=6, pady=6)
        ttk.Button(form, text='Clear / New', command=self.clear).grid(row=btn_row, column=1, padx=6, pady=6)
        ttk.Button(form, text='Delete', command=self.delete_selected).grid(row=btn_row, column=2, padx=6, pady=6)
        self.search_var = tk.StringVar()
        ttk.Label(form, text='Search').grid(row=btn_row, column=3, padx=6, pady=6, sticky='e')
        ttk.Entry(form, textvariable=self.search_var, width=24).grid(row=btn_row, column=4, padx=6, pady=6)
        ttk.Button(form, text='Search', command=self.load).grid(row=btn_row + 1, column=0, padx=6, pady=6)
        # NOTE: Export CSV / Save PDF As / Print / WhatsApp / Email buttons
        # intentionally removed for the Customer screen.

        self.tree_columns = [k for k, _ in self.fields] + [k for k, _ in self.ACTION_COLUMNS]

        # ------------------------------------------------------------------
        # TABLE + SCROLLBARS - built exactly like the Invoice "Saved Invoices"
        # table: LabelFrame -> table_area (table + vertical bar on the right)
        # -> horizontal bar (the line) directly UNDER the table.
        # ------------------------------------------------------------------
        listf = ttk.LabelFrame(container, text='Customers')
        listf.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        table_area = ttk.Frame(listf)
        table_area.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        self.tree = ttk.Treeview(
            table_area,
            columns=self.tree_columns,
            show='headings',
            height=self.TABLE_ROWS
        )

        # Fixed widths (stretch=False): total width of all columns is
        # bigger than the window, so the horizontal scrollbar can move it.
        for k, l in self.fields:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=130, minwidth=100, stretch=False)

        for k, l in self.ACTION_COLUMNS:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=105, minwidth=90, anchor='center', stretch=False)

        # RIGHT vertical scrollbar
        vsb = ttk.Scrollbar(table_area, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        # BOTTOM horizontal scrollbar - the line under the table
        hsb = ttk.Scrollbar(listf, orient='horizontal', command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)

        # vertical bar packed first so a wide table can't squeeze it out
        vsb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        hsb.pack(fill='x', padx=6, pady=(0, 6))

        # Mouse wheel:  wheel = up/down,  Shift + wheel = left/right
        def _on_vertical_wheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                self.tree.yview_scroll(-1, 'units')
            elif num == 5:
                self.tree.yview_scroll(1, 'units')
            else:
                self.tree.yview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')
            return 'break'

        def _on_horizontal_wheel(event):
            num = getattr(event, 'num', None)
            if num == 4:
                self.tree.xview_scroll(-1, 'units')
            elif num == 5:
                self.tree.xview_scroll(1, 'units')
            else:
                self.tree.xview_scroll(-1 if getattr(event, 'delta', 0) > 0 else 1, 'units')
            return 'break'

        self.tree.bind('<MouseWheel>', _on_vertical_wheel)
        self.tree.bind('<Shift-MouseWheel>', _on_horizontal_wheel)
        self.tree.bind('<Button-4>', _on_vertical_wheel)
        self.tree.bind('<Button-5>', _on_vertical_wheel)
        self.tree.bind('<Shift-Button-4>', _on_horizontal_wheel)
        self.tree.bind('<Shift-Button-5>', _on_horizontal_wheel)

        self.tree.bind('<Button-1>', self.on_tree_click)

        self._set_auto_datetime()

    def _make_digit_validator(self, maxlen):
        def validator(proposed):
            return proposed == '' or (proposed.isdigit() and len(proposed) <= maxlen)
        return validator

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

    def _set_auto_datetime(self):
        # Fills Date with today's date, and resets the dropdowns to their
        # defaults, when the form is cleared / a new record is started.
        now = datetime.now()
        self.vars['date'].set(now.strftime('%d-%m-%Y'))
        for key, (_, default) in self.COMBO_FIELDS.items():
            self.vars[key].set(default)

    # ---------- DATA ----------
    def clear(self):
        for v in self.vars.values():
            v.set('')
        self.selected_id = None
        self._set_auto_datetime()

    def load(self):
        for x in self.tree.get_children():
            self.tree.delete(x)
        self.current_rows = []
        term = self.search_var.get().strip().lower() if hasattr(self, 'search_var') else ''
        with conn() as c:
            for r in c.execute(f'SELECT * FROM {self.table} ORDER BY id DESC'):
                row = {k: r[k] for k, _ in self.fields}
                if term and term not in ' '.join(str(v or '').lower() for v in row.values()):
                    continue
                self.current_rows.append(row)
                self.tree.insert(
                    '', 'end', iid=str(r['id']),
                    values=[r[k] for k, _ in self.fields] + ['⬇ Download', '✎ Edit', '🗑 Delete'],
                )
        if hasattr(self, 'combo_widgets'):
            self._refresh_growable_combos()

    def save(self):
        keys = [k for k, _ in self.fields]
        vals = [self.vars[k].get().strip() for k in keys]
        by_key = dict(zip(keys, vals))

        if not by_key['name']:
            return messagebox.showerror('Required', 'Name is required')

        if not by_key['date']:
            return messagebox.showerror('Required', 'Date is required')
        try:
            datetime.strptime(by_key['date'], '%d-%m-%Y')
        except ValueError:
            return messagebox.showerror('Invalid Date', 'Date must be in DD-MM-YYYY format')

        # Contact No is now optional: only validated (must be exactly 10
        # digits) if the user actually filled it in. An empty value never
        # blocks Save.
        if by_key['contact_no'] and (not by_key['contact_no'].isdigit() or len(by_key['contact_no']) != 10):
            return messagebox.showerror('Invalid Contact No', 'Contact No must be exactly 10 digits')

        if by_key['phone_no'] and (not by_key['phone_no'].isdigit() or len(by_key['phone_no']) != 10):
            return messagebox.showerror('Invalid Phone No', 'Phone No must be exactly 10 digits')

        if by_key['pincode'] and (not by_key['pincode'].isdigit() or len(by_key['pincode']) != 6):
            return messagebox.showerror('Invalid Pin Code', 'Pin Code must be exactly 6 digits')

        with conn() as c:
            if self.selected_id:
                sets = ','.join(f'{k}=?' for k in keys)
                c.execute(f'UPDATE {self.table} SET {sets} WHERE id=?', vals + [self.selected_id])
            else:
                c.execute(
                    f'INSERT INTO {self.table}({",".join(keys)}) VALUES({",".join("?" for _ in keys)})',
                    vals
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
        col = self.tree.identify_column(event.x)  # '#1', '#2', ... 1-indexed
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
        self.selected_id = int(row_id)
        vals = self.tree.item(row_id, 'values')[:len(self.fields)]
        for (key, _), value in zip(self.fields, vals):
            self.vars[key].set(value)

    def download_row(self, row_id):
        idx = self.tree.index(row_id)
        if idx >= len(self.current_rows):
            return
        row = self.current_rows[idx]
        safe_name = ''.join(ch for ch in str(row.get('name', 'customer')) if ch.isalnum() or ch in (' ', '_', '-')).strip() or 'customer'
        path = filedialog.asksaveasfilename(
            defaultextension='.pdf', filetypes=[('PDF', '*.pdf')],
            initialfile=f'{safe_name}.pdf',
        )
        if not path:
            return
        make_report_pdf('Customer Details', [k for k, _ in self.fields], [row], path)
        messagebox.showinfo('Downloaded', path)

    def delete_row(self, row_id):
        self._delete_by_id(row_id)

    def _delete_by_id(self, row_id):
        if not messagebox.askyesno(
            'Delete Customer',
            'Delete this customer record?\\n\\n'
            'Existing Quotations / Challans / Invoices will NOT be deleted. '
            'They will be kept safely without a customer link.\\n\\n'
            'Do you want to continue?'
        ):
            return

        try:
            with conn() as c:
                # Keep all old billing documents safe.
                # Remove only their customer reference before deleting
                # the customer. This prevents the SQLite foreign-key
                # error while preserving quotation/challan/invoice history.
                c.execute(
                    'UPDATE quotations SET customer_id=NULL WHERE customer_id=?',
                    (row_id,)
                )
                c.execute(
                    'UPDATE challans SET customer_id=NULL WHERE customer_id=?',
                    (row_id,)
                )
                c.execute(
                    'UPDATE invoices SET customer_id=NULL WHERE customer_id=?',
                    (row_id,)
                )

                # Godowns are global now (see database.py), so deleting a
                # customer never touches any Godown record any more.
                c.execute(
                    f'DELETE FROM {self.table} WHERE id=?',
                    (row_id,)
                )

        except sqlite3.IntegrityError as e:
            return messagebox.showerror(
                'Cannot Delete',
                'Customer could not be deleted.\\n\\n'
                f'Database error: {e}'
            )
        except Exception as e:
            return messagebox.showerror(
                'Cannot Delete',
                f'Unexpected database error: {e}'
            )

        if self.selected_id and str(self.selected_id) == str(row_id):
            self.clear()

        self.load()
        messagebox.showinfo(
            'Deleted',
            'Customer deleted successfully.\\n\\n'
            'Existing Quotations / Challans / Invoices are safe.'
        )

    # Kept for compatibility with the base class' double-click binding.
    def pick_row(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.edit_row(sel[0])