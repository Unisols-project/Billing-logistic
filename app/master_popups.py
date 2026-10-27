"""


Save as:  app/master_popups.py
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from database import conn, ensure_godown
from app.customer_tab import CustomerTab
from app.product_tab import ProductTab   # file


# ---------------- helpers ----------------
def _ensure_cols(table, wanted):
    with conn() as c:
        cols = [r['name'] for r in c.execute(f'PRAGMA table_info({table})')]
        for col, typ in wanted.items():
            if col not in cols:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')


def _ensure_godown_tables():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS godowns(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS godown_products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            godown_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            UNIQUE(godown_id, product_id),
            FOREIGN KEY(godown_id) REFERENCES godowns(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE)''')


def _distinct(table, key, seed=()):
    vals = []
    try:
        with conn() as c:
            rows = c.execute(
                f'SELECT DISTINCT {key} FROM {table} '
                f'WHERE {key} IS NOT NULL AND TRIM({key}) != "" ORDER BY {key}')
            vals = [r[0] for r in rows]
    except sqlite3.Error:
        pass
    return list(dict.fromkeys(list(seed) + vals))


def _num_validator(proposed):
    if proposed == '':
        return True
    if proposed.count('.') > 1:
        return False
    return all(ch.isdigit() or ch == '.' for ch in proposed)


def _digit_validator(maxlen):
    return lambda p: p == '' or (p.isdigit() and len(p) <= maxlen)


def _f(s):
    try:
        return float(s or 0)
    except ValueError:
        return 0.0


# ---------------- CUSTOMER FULL FORM ----------------
def open_customer_form(parent, on_saved=None):
    """Customer Master  form. Save on_saved(name) call ."""
    _ensure_cols('customers', CustomerTab.NEW_DB_COLUMNS)
    win = tk.Toplevel(parent)
    win.title('Add Customer')
    win.transient(parent.winfo_toplevel())
    win.grab_set()

    frm = ttk.LabelFrame(win, text='Details')
    frm.pack(fill='both', expand=True, padx=8, pady=8)
    vars_ = {}
    for i, (key, label) in enumerate(CustomerTab.fields):
        ttk.Label(frm, text=label).grid(row=i // 3 * 2, column=i % 3, padx=6, pady=(6, 0), sticky='w')
        v = tk.StringVar()
        vars_[key] = v
        if key == 'category':
            w = ttk.Combobox(frm, textvariable=v, width=26,
                             values=_distinct('customers', 'category', CustomerTab.DEFAULT_CATEGORY_OPTIONS))
        elif key in CustomerTab.COMBO_FIELDS:
            opts, default = CustomerTab.COMBO_FIELDS[key]
            v.set(default)
            w = ttk.Combobox(frm, textvariable=v, values=opts, width=26, state='readonly')
        elif key in CustomerTab.DIGIT_FIELDS:
            vc = (win.register(_digit_validator(CustomerTab.DIGIT_FIELDS[key])), '%P')
            w = ttk.Entry(frm, textvariable=v, width=28, validate='key', validatecommand=vc)
        else:
            w = ttk.Entry(frm, textvariable=v, width=28)
        w.grid(row=i // 3 * 2 + 1, column=i % 3, padx=6, pady=(0, 6), sticky='ew')
    vars_['date'].set(datetime.now().strftime('%d-%m-%Y'))

    def save():
        d = {k: v.get().strip() for k, v in vars_.items()}
        if not d['name']:
            return messagebox.showerror('Required', 'Name is required', parent=win)
        if not d['date']:
            return messagebox.showerror('Required', 'Date is required', parent=win)
        try:
            datetime.strptime(d['date'], '%d-%m-%Y')
        except ValueError:
            return messagebox.showerror('Invalid Date', 'Date must be DD-MM-YYYY', parent=win)
        if not d['contact_no'].isdigit() or len(d['contact_no']) != 10:
            return messagebox.showerror('Invalid Contact No', 'Contact No must be exactly 10 digits', parent=win)
        if d['phone_no'] and (not d['phone_no'].isdigit() or len(d['phone_no']) != 10):
            return messagebox.showerror('Invalid Phone No', 'Phone No must be exactly 10 digits', parent=win)
        if d['pincode'] and (not d['pincode'].isdigit() or len(d['pincode']) != 6):
            return messagebox.showerror('Invalid Pin Code', 'Pin Code must be exactly 6 digits', parent=win)
        with conn() as c:
            old = c.execute('SELECT id FROM customers WHERE lower(name)=lower(?)', (d['name'],)).fetchone()
            if old:
                if not messagebox.askyesno('Exists', '. Update ?', parent=win):
                    return
                sets = ','.join(f'{k}=?' for k in d)
                c.execute(f'UPDATE customers SET {sets} WHERE id=?', list(d.values()) + [old['id']])
            else:
                c.execute(f'INSERT INTO customers({",".join(d)}) VALUES({",".join("?" for _ in d)})',
                          list(d.values()))
        win.destroy()
        if on_saved:
            on_saved(d['name'])

    ttk.Button(win, text='Save', command=save).pack(pady=8)


# ---------------- PRODUCT FULL FORM ----------------
def open_product_form(parent, godown_name='', on_saved=None):
    """
    """
    _ensure_cols('products', ProductTab.NEW_DB_COLUMNS)
    _ensure_godown_tables()
    win = tk.Toplevel(parent)
    win.title('Add Product' + (f'  -  Godown: {godown_name}' if godown_name else ''))
    win.transient(parent.winfo_toplevel())
    win.grab_set()

    frm = ttk.LabelFrame(win, text='Details')
    frm.pack(fill='both', expand=True, padx=8, pady=8)
    vars_ = {}
    growable = ProductTab.GROWABLE_COMBO_FIELDS
    for i, (key, label) in enumerate(ProductTab.fields):
        ttk.Label(frm, text=label).grid(row=i // 4 * 2, column=i % 4, padx=6, pady=(6, 0), sticky='w')
        v = tk.StringVar()
        vars_[key] = v
        if key == 'item_name':
            w = ttk.Entry(frm, textvariable=v, width=28)
        elif key in growable:
            # Unit (and Company Name / Category) stay a normal, editable
            # Combobox here too — type any value or pick one already saved.
            w = ttk.Combobox(frm, textvariable=v, width=26, values=_distinct('products', key, growable[key]))
        elif key in ProductTab.DECIMAL_FIELDS:
            vc = (win.register(_num_validator), '%P')
            w = ttk.Entry(frm, textvariable=v, width=28, validate='key', validatecommand=vc)
        else:
            w = ttk.Entry(frm, textvariable=v, width=28)
        if key in ProductTab.READONLY_FIELDS:
            w.configure(state='readonly')
        w.grid(row=i // 4 * 2 + 1, column=i % 4, padx=6, pady=(0, 6), sticky='ew')

    vars_['date'].set(datetime.now().strftime('%d-%m-%Y'))
    vars_['loading'].set('0')
    if not vars_['unit'].get().strip():
        vars_['unit'].set('Nos')

    def recalc(*_):
        # Total = Quantity x (Wholesale Rate + Loading).
        # Loading is PER UNIT: added to the Wholesale Rate first, THEN
        # Quantity is applied to that combined per-unit rate. This is the
        # ONLY figure calculated here now — there is no separate
        # Amount / AMT field any more (those were removed from
        # ProductTab.fields, which is why referencing them used to crash
        # this popup with a KeyError).
        qty = _f(vars_['qty'].get())
        wholesale = _f(vars_['wholesale_rate'].get())
        loading = max(_f(vars_['loading'].get()), 0)
        vars_['total'].set(f'{qty * (wholesale + loading):.2f}')

    for k in ('qty', 'wholesale_rate', 'loading'):
        vars_[k].trace_add('write', recalc)
    recalc()

    def save():
        d = {k: v.get().strip() for k, v in vars_.items()}
        if not d['item_name']:
            return messagebox.showerror('Required', 'Item Name is required', parent=win)
        if not d['date']:
            return messagebox.showerror('Required', 'Date is required', parent=win)
        try:
            datetime.strptime(d['date'], '%d-%m-%Y')
        except ValueError:
            return messagebox.showerror('Invalid Date', 'Date must be DD-MM-YYYY', parent=win)

        d['unit'] = d.get('unit') or 'Nos'

        # Make sure Total reflects Qty x (Wholesale Rate + Loading) right
        # before saving, same as the main Product Master screen.
        try:
            wholesale = float(d.get('wholesale_rate') or 0)
        except ValueError:
            wholesale = 0.0
        try:
            loading = float(d.get('loading') or 0)
        except ValueError:
            loading = 0.0
        if loading < 0:
            loading = 0.0
        try:
            qty = float(d.get('qty') or 0)
        except ValueError:
            qty = 0.0
        d['wholesale_rate'] = f'{wholesale:.2f}'
        d['loading'] = f'{loading:.2f}'
        d['total'] = f'{qty * (wholesale + loading):.2f}'

        with conn() as c:
            row = c.execute(
                'SELECT id, COALESCE(is_placeholder,0) AS ph FROM products '
                'WHERE LOWER(TRIM(item_name))=LOWER(?) AND LOWER(TRIM(COALESCE(unit,"Nos")))=LOWER(?)',
                (d['item_name'], d['unit'])
            ).fetchone()
            if row and not row['ph']:
                # Product 
                pid = row['id']
                messagebox.showinfo('Exists', ' Product  Godown map .', parent=win)
            elif row:
                # placeholder 
                pid = row['id']
                sets = ','.join(f'{k}=?' for k in d)
                c.execute(f'UPDATE products SET {sets}, is_placeholder=0 WHERE id=?',
                          list(d.values()) + [pid])
            else:
                cur = c.execute(
                    f'INSERT INTO products({",".join(d)}, is_placeholder) '
                    f'VALUES({",".join("?" for _ in d)}, 0)', list(d.values()))
                pid = cur.lastrowid

            if godown_name:
                # ensure_godown() confirms/creates the Godown row FIRST
                # (in its own short transaction), so the id used below is
                # always valid - no more silently-skipped mapping and no
                # FOREIGN KEY constraint failure.
                gid = ensure_godown(godown_name)
                if gid:
                    # Re-check the product row is really there before the
                    # mapping insert (defensive, same reasoning as
                    # product_tab.py's open_item_mapping fix).
                    prow = c.execute('SELECT id FROM products WHERE id=?', (pid,)).fetchone()
                    if prow:
                        c.execute(
                            'INSERT OR IGNORE INTO godown_products(godown_id,product_id) VALUES(?,?)',
                            (gid, pid)
                        )
        win.destroy()
        if on_saved:
            on_saved(d['item_name'])

    ttk.Button(win, text='Save', command=save).pack(pady=8)