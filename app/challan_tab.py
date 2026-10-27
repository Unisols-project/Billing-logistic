import os
import re
import tempfile
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import shutil
from database import conn
from services.pdf_service import make_pdf
from services.send_service import open_whatsapp
from app.document_editor import DocEditor
# Customer Master / Product Master forms (shared file)
from app.master_popups import open_customer_form, open_product_form
# shared calculation helpers (only the ones this screen still needs)
from app.item_calc import num, fnum, product_rate, product_loading, product_qty


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


class ChallanTab(DocEditor):
    table='challans';item_table='challan_items';prefix='DC-';doc_type='challan'
    id_field='challan_id'
    # ONE product = ONE row.  "Challan No." and "Product No." are separate columns.
    # NOTE: the "Weight (kg)" column that used to sit here has been
    # replaced with "Unit" (per request) — Saved Challans now shows what
    # Unit (Kg, Bag, Box, ...) each item is in instead of its weight.
    # weight_kg is still saved on every challan_items row exactly as
    # before; it is simply no longer shown in this particular table.
    #
    # NOTE: text typed after the product in the Product box (e.g. "to pune")
    # is saved ONLY in that challan line's item name - never in Product Master.
    CLIST_COLS = [
        ('number', 'Challan No.'),
        ('sr', 'Product No.'),
        ('date', 'Date'),
        ('customer', 'Customer Name'),
        ('godown', 'Godown'),
        ('payment_mode', 'Payment Mode'),
        ('vehicle', 'Vehicle'),
        ('item', 'Item'),
        ('qty', 'Quantity'),
        ('unit', 'Unit'),
        ('loading', 'Loading/Unit'),
        ('rate', 'Rate/Unit'),
        ('hsn', 'HSN'),
        ('total', 'Total'),
    ]
    # IMPORTANT: GSTIN is intentionally NOT a Saved Challans table column.
    # This screen is WITHOUT GST, so GSTIN must never be shown/sent in Challan data.
    CLIST_ACTIONS=[('dl','Download'),('print','Print'),('edit','Edit'),('delete','Delete'),('sel','Select')]

    # Allowed Payment Mode values (dropdown)
    PAYMENT_MODES=('Cash','Credit','NEFT')

    # index (in self.items) of the item currently being edited; None = adding a new item
    editing_item_idx=None
    edit_mode=False     # True ONLY when Edit is clicked in Saved Challans table
    _skip_autofill=False
    MAX_ITEMS=10        # one challan (one PDF) holds at most 10 products
    _print_copies=1     # how many copies the PDF should contain (set by Print / Download)

    def build(self):
        # Payment Mode column must exist BEFORE anything reads/writes challans
        self._ensure_challan_payment_mode_column()
        self.pay_mode=tk.StringVar(value='Cash')
        self._ensure_challan_vehicle_column()
        self.vehicle_var=tk.StringVar(value='')
        self.gst_mode=tk.StringVar(value='NO_GST')
        # Godown-name -> global godowns.id
        self.godown_id_map={}
        # tracks the bill number that is CURRENTLY loaded/saved on screen, so
        # save_doc() can tell "number was manually changed" apart from
        # "still the same challan being edited" (see save_doc / new_doc /
        # after_load_doc for how this is kept in sync).
        self._loaded_number=''
        # Remembers the Date that was on screen when a saved challan was
        # loaded (Edit button OR typing an existing Challan No.), and
        # whether the person has manually typed into the Date box since.
        # save_doc() uses these to make sure simply ADDING a product to an
        # already-saved challan never silently changes its saved Date -
        # only a deliberate edit of the Date box itself is allowed to.
        self._loaded_date=''
        self._date_manually_edited=False
        # Remembers the Godown that was on screen when a saved challan was
        # loaded, purely as a header-level baseline (see _loaded_number /
        # _loaded_date above for the same pattern). Each PRODUCT's own
        # godown is tracked separately in item['godown'] / challan_items.godown
        # - see add_item() / save_doc() / after_load_doc() / refresh_challans_list().
        self._loaded_godown=''
        # challan ids (str) ticked in the Saved Challans 'Select' column
        self._sel_cids=set()
        super().build()

        self._hide_base_customer_details()

        self._ensure_product_loading_column()
        self._ensure_challan_item_loading_column()
        self._ensure_challan_item_date_column()
        self._ensure_challan_item_godown_column()
        self._ensure_godown_products_table()
        self._ensure_challan_settled_column()

        # The base screen's own Product / Qty / Rate inputs are replaced by the
        # single item row built below.
        self._hide_base_item_inputs()

        self._configure_item_table()

        for w in getattr(self,'doc_top_extra_widgets',[]):w.grid_remove()
        if hasattr(self,'bottom'):self.bottom.pack_forget()

        self.day_var=tk.StringVar()
        self.time=tk.StringVar()
        self.dt.trace_add('write',self._update_day)

        cf=ttk.LabelFrame(self.body,text='Customer Details (auto-fills from Customer master - editable here)')
        cf.pack(fill='x',padx=8,pady=4,before=self.tree)
        self.c_address=tk.StringVar();self.c_contact=tk.StringVar();self.c_email=tk.StringVar()
        self.c_state=tk.StringVar();self.c_gstin=tk.StringVar();self.c_person=tk.StringVar();self.c_godown=tk.StringVar()
        ttk.Label(cf,text='Godown').grid(row=0,column=0,padx=5,pady=(6,0),sticky='w')
        gcell=ttk.Frame(cf)
        gcell.grid(row=1,column=0,padx=5,pady=(0,6),sticky='w')
        self.godown_cb=ttk.Combobox(gcell,textvariable=self.c_godown,width=24,state='normal')
        self.godown_cb.pack(side='left')
        ttk.Button(gcell,text='+',width=2,command=self._add_godown).pack(side='left',padx=(4,0))
        self.godown_cb.bind('<KeyRelease>', self._filter_godown_values)
        self.godown_cb.bind('<<ComboboxSelected>>', self._on_godown_combo_selected)

        # ---- Payment Mode dropdown: Cash / Credit / NEFT ----
        ttk.Label(cf,text='Payment Mode').grid(row=0,column=1,padx=5,pady=(6,0),sticky='w')
        self.pay_mode_cb=ttk.Combobox(cf,textvariable=self.pay_mode,values=self.PAYMENT_MODES,width=14,state='readonly')
        self.pay_mode_cb.grid(row=1,column=1,padx=5,pady=(0,6),sticky='w')
        self.pay_mode_cb.bind('<<ComboboxSelected>>', lambda e: self._refresh_customer_due_total())

        # ---- Vehicle (optional): free text, shown in Saved Challans and on the PDF ----
        ttk.Label(cf,text='Vehicle (optional)').grid(row=0,column=4,padx=5,pady=(6,0),sticky='w')
        self.vehicle_cb=ttk.Combobox(cf,textvariable=self.vehicle_var,values=self._vehicle_names(),width=20,state='normal')
        self.vehicle_cb.grid(row=1,column=4,padx=5,pady=(0,6),sticky='w')
        self.vehicle_cb.bind('<FocusIn>',lambda e:self.vehicle_cb.configure(values=self._vehicle_names()))

        # ---- Customer Pending Total - live, next to Customer ----
        ttk.Label(cf,text='Customer Pending Total').grid(row=0,column=2,padx=5,pady=(6,0),sticky='w')
        self.customer_due_var=tk.StringVar(value='₹0.00')
        ttk.Label(cf,textvariable=self.customer_due_var,font=('Segoe UI',10,'bold'),
                  foreground='#B00020').grid(row=1,column=2,padx=5,pady=(0,6),sticky='w')

        # ---- Today Total - selected customer's challans of TODAY ----
        ttk.Label(cf,text='Today Total').grid(row=0,column=3,padx=5,pady=(6,0),sticky='w')
        self.today_total_var=tk.StringVar(value='₹0.00')
        ttk.Label(cf,textvariable=self.today_total_var,font=('Segoe UI',10,'bold'),
                  foreground='#0A7B2E').grid(row=1,column=3,padx=5,pady=(0,6),sticky='w')

        # ---- ONE ROW: Product | Unit | Quantity | Rate | Loading (per unit) | Total ----
        self.item_loading=tk.StringVar(value='0')   # per unit
        self.item_total=tk.StringVar(value='0.00')
        self.add_btn_text=tk.StringVar(value='Add Item')
        # not shown on screen any more, but still filled from Product master and saved
        self.item_weight=tk.StringVar(value='0')    # weight per unit (kg)
        self.item_unit=tk.StringVar(value='Nos')
        self.item_hsn=tk.StringVar(value='')

        entry=ttk.LabelFrame(self.body,text='Item  (Loading is per unit:  Total = Qty x Rate + Qty x Loading)')
        entry.pack(fill='x',padx=8,pady=4,before=self.tree)
        for i,lab in enumerate(('Product','Unit','Quantity','Rate (₹)','Loading (₹ / unit)','Total (₹)')):
            ttk.Label(entry,text=lab).grid(row=0,column=i,padx=6,pady=(6,0),sticky='w')
        pcell=ttk.Frame(entry)
        pcell.grid(row=1,column=0,padx=6,pady=(0,8),sticky='w')
        self.product_cb=ttk.Combobox(pcell,textvariable=self.product,width=38,state='normal')
        self.product_cb.pack(side='left')
        # type-to-search: typing filters the dropdown list
        self.product_cb.bind('<KeyRelease>', self._on_product_typed)
        self.product_cb.bind('<<ComboboxSelected>>', self._on_product_list_picked, add='+')
        self.product_cb.bind('<Return>', self._commit_product_typed, add='+')
        self.product_cb.bind('<FocusOut>', self._commit_product_typed, add='+')
        # live suggestion list under the box while typing
        self._product_popup=_SuggestPopup(self.product_cb,self._product_matches,self._pick_product_from_popup)
        ttk.Button(pcell,text='+',width=2,command=self._add_product_full).pack(side='left',padx=(4,0))
        self._rebuild_product_map_with_units()
        ttk.Entry(entry,textvariable=self.item_unit,width=12).grid(row=1,column=1,padx=6,pady=(0,8),sticky='w')
        ttk.Entry(entry,textvariable=self.qty,width=9).grid(row=1,column=2,padx=6,pady=(0,8),sticky='w')
        ttk.Entry(entry,textvariable=self.price,width=11).grid(row=1,column=3,padx=6,pady=(0,8),sticky='w')
        ttk.Entry(entry,textvariable=self.item_loading,width=12).grid(row=1,column=4,padx=6,pady=(0,8),sticky='w')
        ttk.Entry(entry,textvariable=self.item_total,width=13,state='readonly').grid(row=1,column=5,padx=6,pady=(0,8),sticky='w')
        ttk.Button(entry,textvariable=self.add_btn_text,command=self.add_item).grid(row=1,column=6,padx=(10,4),pady=(0,8))
        ttk.Button(entry,text='Clear',command=self._on_clear_clicked).grid(row=1,column=7,padx=4,pady=(0,8))

        for v in (self.qty,self.price,self.item_loading):
            v.trace_add('write',self._update_total)
        self.product.trace_add('write',self._schedule_autofill)
        self._update_total()

        # ---- Godown -> Product dropdown filter ----
        self.load_customer_godowns()
        self.c_godown.trace_add('write', self._on_godown_changed_filter_products)
        self._on_godown_changed_filter_products()

        # Customer dropdown gets its "+" button (Product's "+" is already in the item row)
        self._wrap_combo_with_plus(self.customer, self._add_customer_full)
        self._setup_customer_search()

        self.gst_mode.set('NO_GST')

        self.place=tk.StringVar()
        self.from_city=tk.StringVar()
        self.to_city=tk.StringVar()
        self.freight_rate=tk.StringVar(value='0')
        self.rate_type=tk.StringVar(value='Per Kg')
        self.desc=tk.StringVar()

        if hasattr(self,'sendbar'):
            self.sendbar.pack_forget()
            self.sendbar.pack(fill='x',padx=8,pady=4,before=self.tree)
        if hasattr(self, 'tree'):
            self.tree.pack_forget()
        listf=ttk.LabelFrame(self.body,text='Saved Challans  (one row per product - click Download / Print / Edit / Delete in the row; click Select again to un-select)')
        listf.pack(fill='both',expand=True,padx=8,pady=(4,6))

        # ---- Customer Statement: pick a customer, see all their challans,
        # select any number of them, see the total of what's selected. ----
        stmt_bar=ttk.Frame(self.body)
        stmt_bar.pack(fill='x',padx=8,pady=(0,4),before=listf)
        ttk.Button(stmt_bar,text='📄 Customer Statement',command=self.open_customer_statement).pack(side='left')
        # ---- Bulk Change Date: tick challans with the 'Select' column in the
        # Saved Challans table, type ONE new date, click Apply. ----
        ttk.Separator(stmt_bar,orient='vertical').pack(side='left',fill='y',padx=10)
        ttk.Button(stmt_bar,text='Select Today',command=self._select_today_challans).pack(side='left')
        ttk.Button(stmt_bar,text='Select All',command=lambda:self._select_all_challans(True)).pack(side='left',padx=(6,0))
        ttk.Button(stmt_bar,text='Clear Selection',command=lambda:self._select_all_challans(False)).pack(side='left',padx=(6,0))
        self.sel_count_var=tk.StringVar(value='0 product(s) selected')
        ttk.Label(stmt_bar,textvariable=self.sel_count_var).pack(side='left',padx=(10,10))
        ttk.Label(stmt_bar,text='New Date').pack(side='left')
        self.bulk_date_var=tk.StringVar(value=(datetime.now()+timedelta(days=1)).strftime('%d-%m-%Y'))
        ttk.Entry(stmt_bar,textvariable=self.bulk_date_var,width=12).pack(side='left',padx=(6,6))
        ttk.Button(stmt_bar,text='Today',width=7,
                   command=lambda:self.bulk_date_var.set(datetime.now().strftime('%d-%m-%Y'))).pack(side='left',padx=(4,6))
        ttk.Button(stmt_bar,text='📅 Apply Date to Selected',command=self._apply_bulk_date).pack(side='left')

        if hasattr(self,'bottom'):
            self.bottom.pack_forget()
        self.ccols=[k for k,_ in self.CLIST_COLS]+[k for k,_ in self.CLIST_ACTIONS]
        self.visible_ccols=list(self.ccols)
        self.clist=ttk.Treeview(listf,columns=self.ccols,show='headings',height=10)
        widths={'number':100,'sr':80,'date':90,'customer':170,'godown':130,'payment_mode':110,'vehicle':110,'item':200,'qty':80,
                'unit':80,'loading':90,'rate':85,'hsn':100,'total':100}
        for k,l in self.CLIST_COLS:
            self.clist.heading(k,text=l)
            self.clist.column(k,width=widths.get(k,100),anchor='w')
        for k,l in self.CLIST_ACTIONS:
            self.clist.heading(k,text=l)
            self.clist.column(k,width=85,anchor='center',stretch=False)
        self.clist.tag_configure('picked',background='#FFF59D')
        self._update_saved_table_columns()
        xscroll=ttk.Scrollbar(listf,orient='horizontal',command=self.clist.xview)
        yscroll=ttk.Scrollbar(listf,orient='vertical',command=self.clist.yview)
        self.clist.configure(xscrollcommand=xscroll.set,yscrollcommand=yscroll.set)
        xscroll.pack(side='bottom',fill='x',padx=6,pady=(0,6))
        yscroll.pack(side='right',fill='y',pady=(6,0))
        self.clist.pack(side='left',fill='both',expand=True,padx=(6,0),pady=(6,0))
        self.clist.bind('<Button-1>',self.on_clist_click)
        # Challan has no GST - take every GST field/label/button off this screen
        self._hide_gst_widgets()

        # Typing an EXISTING Challan No. into the Number box (without using
        # the Edit button) should load that saved challan automatically, so
        # a new product can be added to it. See _maybe_load_existing_number.
        self._bind_number_autoload()
        # Track manual edits to the Date box - see save_doc()'s DATE GUARD.
        self._bind_date_manual_flag()

    # ---------- Hide the base screen's own Product / Qty / Rate inputs ----------
    def _hide_base_item_inputs(self):
        root=getattr(self,'body',None) or self
        try:
            for var in (self.product,self.qty,self.price):
                for w in self._widgets_for_var(var,root):
                    self._hide_with_label(w)
            for b in self._add_buttons(root):
                self._hide_widget(b)
        except Exception:
            pass

    def _widgets_for_var(self,var,root):
        found=[]
        try:
            children=root.winfo_children()
        except Exception:
            return found
        for w in children:
            try:
                if w.winfo_class() in self._INPUT_CLASSES and str(w.cget('textvariable'))==str(var):
                    found.append(w)
            except Exception:
                pass
            found.extend(self._widgets_for_var(var,w))
        return found

    def _add_buttons(self,root):
        found=[]
        try:
            children=root.winfo_children()
        except Exception:
            return found
        for w in children:
            try:
                if w.winfo_class() in ('TButton','Button'):
                    t=str(w.cget('text') or '').strip().lower().lstrip('+ ').strip()
                    if t.startswith('add'):
                        found.append(w)
            except Exception:
                pass
            found.extend(self._add_buttons(w))
        return found

    def _hide_with_label(self,w):
        try:
            parent=w.master
            mgr=w.winfo_manager()
            if mgr=='grid':
                g=w.grid_info();r=int(g.get('row',0));c=int(g.get('column',0))
                for s in parent.grid_slaves():
                    if s is w or s.winfo_class() not in ('TLabel','Label'):
                        continue
                    gi=s.grid_info();sr=int(gi.get('row',0));sc=int(gi.get('column',0))
                    if (sc==c and sr==r-1) or (sr==r and sc==c-1):
                        self._hide_widget(s)
            elif mgr=='pack':
                slaves=parent.pack_slaves()
                i=slaves.index(w)
                if i>0 and slaves[i-1].winfo_class() in ('TLabel','Label'):
                    self._hide_widget(slaves[i-1])
        except Exception:
            pass
        self._hide_widget(w)

    # ---------- "+ Godown / + New Customer / + New Product" ----------
    def _add_godown(self):
        name = simpledialog.askstring('Add Godown', 'Enter Godown name:', parent=self)
        if not name or not name.strip():
            return
        with conn() as c:
            c.execute('INSERT OR IGNORE INTO godowns(name) VALUES(?)', (name.strip(),))
        self.load_customer_godowns(selected=name.strip())

    def _rebuild_product_map_with_units(self):
        try:
            with conn() as c:
                rows = c.execute('SELECT * FROM products ORDER BY item_name, unit, id').fetchall()
            self.product_map = {
                f"{r['id']} - {r['item_name']}": dict(r)
                for r in rows
                if (r['item_name'] or '').strip() and int(r['is_placeholder'] or 0) == 0
            }
            cb = getattr(self, 'product_cb', None)
            if cb is not None:
                cb['values'] = sorted(self.product_map.keys())
        except Exception:
            pass

    def _filter_godown_values(self, event=None):
        if not hasattr(self, 'godown_cb'):
            return
        typed = self.c_godown.get().strip().lower()
        vals = list(self.godown_id_map.keys()) if hasattr(self, 'godown_id_map') else []
        if typed:
            vals = [v for v in vals if typed in v.lower()]
        self.godown_cb['values'] = sorted(vals)

    def _on_godown_combo_selected(self, event=None):
        self._on_godown_changed_filter_products()

    def _find_product_key_for_current_godown(self, name, unit=None):
        name = (name or '').strip().lower()
        unit = (unit or '').strip().lower()
        gid = self.godown_id_map.get(self.c_godown.get().strip()) if hasattr(self, 'godown_id_map') else None
        candidates = []
        for key, p in getattr(self, 'product_map', {}).items():
            if (p.get('item_name') or '').strip().lower() == name:
                if unit and (p.get('unit') or 'Nos').strip().lower() != unit:
                    continue
                candidates.append((key, p))
        if gid:
            with conn() as c:
                allowed = {r['product_id'] for r in c.execute('SELECT product_id FROM godown_products WHERE godown_id=?', (gid,))}
            candidates = [x for x in candidates if x[1].get('id') in allowed]
        return candidates[0][0] if candidates else None

    def _reload_masters(self):
        for nm in ('load_customers', 'load_products', 'load_masters', 'reload_masters'):
            fn = getattr(self, nm, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        self._rebuild_product_map_with_units()

    def _fallback_rebuild_maps(self):
        try:
            with conn() as c:
                crow = c.execute('SELECT * FROM customers ORDER BY name').fetchall()
                prow = c.execute('SELECT * FROM products ORDER BY item_name').fetchall()
            self.customer_map = {f"{r['id']} - {r['name']}": dict(r) for r in crow}
            self.product_map = {f"{r['id']} - {r['item_name']}": dict(r) for r in prow if int(r['is_placeholder'] or 0) == 0}
            ccb = self._find_combobox_for_var(self.customer, self)
            if ccb:
                ccb['values'] = sorted(self.customer_map.keys())
        except Exception:
            pass

    def _find_key_by(self, mapping, field, name):
        for key, rec in mapping.items():
            if (rec.get(field) or '').strip().lower() == name.strip().lower():
                return key
        return None

    def _add_customer_full(self):
        def done(name):
            self._reload_masters()
            key = self._find_key_by(self.customer_map, 'name', name)
            if not key:
                self._fallback_rebuild_maps()
                key = self._find_key_by(self.customer_map, 'name', name)
            if key:
                self.customer.set(key)
                self.on_customer_selected(user_pick=True)
        open_customer_form(self, on_saved=done)

    def _wrap_combo_with_plus(self, var, command):
        try:
            old = self._find_combobox_for_var(var, self)
            if not old:
                return
            parent = old.master
            mgr = old.winfo_manager()
            wrap = ttk.Frame(parent)
            if mgr == 'grid':
                info = old.grid_info()
                info.pop('in', None)
                old.grid_forget()
                wrap.grid(**info)
            elif mgr == 'pack':
                info = old.pack_info()
                info.pop('in', None)
                slaves = parent.pack_slaves()
                idx = slaves.index(old)
                if idx > 0:
                    info['after'] = slaves[idx - 1]
                elif len(slaves) > 1:
                    info['before'] = slaves[1]
                old.pack_forget()
                wrap.pack(**info)
            else:
                wrap.destroy()
                return
            old.pack(in_=wrap, side='left', fill='x', expand=True)
            old.lift()
            ttk.Button(wrap, text='+', width=2, command=command).pack(side='left', padx=(4, 0))
        except Exception:
            pass

    def _add_product_full(self):
        if not self.c_godown.get().strip():
            if not messagebox.askyesno(
                'Godown select',
                'No Godown is selected.\n\nAdd the product without a Godown?',
                parent=self
            ):
                return

        def done(name):
            self._reload_masters()
            key = self._find_product_key_for_current_godown(name)
            if not key:
                self._fallback_rebuild_maps()
                key = self._find_product_key_for_current_godown(name)
            self._on_godown_changed_filter_products()
            if key and key in self._product_combo_values():
                self.product.set(key)
                fn = getattr(self, 'on_product_selected', None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass

        open_product_form(self, godown_name=self.c_godown.get().strip(), on_saved=done)

    def _product_combo_values(self):
        cb = self._get_product_combobox()
        return list(cb['values']) if cb else []

    # ---------- Type-to-search for the Customer and Product dropdowns ----------
    _IGNORE_KEYS = ('Return', 'Tab', 'Up', 'Down', 'Left', 'Right', 'Escape',
                    'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
                    'Caps_Lock', 'Home', 'End')

    @staticmethod
    def _name_part(key):
        """'5 - Kaju    |    Unit: Kg' -> 'Kaju'   /   '3 - Yash Traders' -> 'Yash Traders'"""
        return str(key).split(' - ', 1)[-1].split('    |', 1)[0].strip()

    _last_autofill_pid = None

    def _split_product_text(self, text):
        """Product box text -> (product_key, note).

        The person may type extra words after the product, e.g.
        '66 - jarhksgg    to pune'.  The product is found by its ID
        and name; whatever is typed after it is the NOTE. The note goes
        only into the challan line (item name), never into Product Master.
        Returns (None, '') when the text does not start with a full,
        valid product (so normal type-to-search keeps working)."""
        text = (text or '').strip()
        m = re.match(r'^(\d+)\s*-\s*(.*)$', text, re.S)
        if not m:
            return None, ''
        pid = int(m.group(1))
        rest = m.group(2)
        for key, p in getattr(self, 'product_map', {}).items():
            if p.get('id') != pid:
                continue
            name = (p.get('item_name') or '').strip()
            if not name or not rest.lower().startswith(name.lower()):
                return None, ''
            rest = rest[len(name):]
            rest = re.sub(r'^\s*\|\s*Unit:\s*\S+', '', rest)
            return key, rest.strip()
        return None, ''

    def _search_keys(self, keys, typed):
        """Names STARTING with the typed text come first, then names that
        merely CONTAIN it. Empty text = the full list."""
        typed = (typed or '').strip().lower()
        keys = list(keys)
        if not typed:
            return keys
        starts, contains = [], []
        for k in keys:
            nm = self._name_part(k).lower()
            if nm.startswith(typed):
                starts.append(k)
            elif typed in nm or str(k).lower().startswith(typed):
                contains.append(k)
        return sorted(starts, key=str.lower) + sorted(contains, key=str.lower)

    # ----- Product -----
    def _product_all_keys_list(self):
        keys = getattr(self, '_product_all_keys', None)
        if not keys:
            keys = sorted(getattr(self, 'product_map', {}).keys())
        return list(keys)

    def _on_product_typed(self, event=None):
        if event is not None and getattr(event, 'keysym', '') in self._IGNORE_KEYS:
            return
        cb = self._get_product_combobox()
        if cb is None:
            return
        pp = getattr(self, '_product_popup', None)
        if self._split_product_text(self.product.get())[0]:
            # a full product is already there (maybe with a note) - leave it alone
            cb['values'] = self._product_all_keys_list()
            if pp is not None:
                pp.hide()
            return
        cb['values'] = self._search_keys(self._product_all_keys_list(), self.product.get())
        if pp is not None:
            pp.refresh()

    def _product_matches(self):
        typed = self.product.get().strip()
        if not typed or typed in getattr(self, 'product_map', {}):
            return []
        if self._split_product_text(typed)[0]:
            return []
        return self._search_keys(self._product_all_keys_list(), typed)

    def _pick_product_from_popup(self, key):
        self.product.set(key)
        self._on_product_list_picked()

    def _on_product_list_picked(self, event=None):
        cb = self._get_product_combobox()
        if cb is not None:
            cb['values'] = self._product_all_keys_list()   # full list again

    def _resolve_product_key(self):
        typed = self.product.get().strip()
        if not typed:
            return None
        if typed in getattr(self, 'product_map', {}):
            return typed
        matches = self._search_keys(self._product_all_keys_list(), typed)
        exact = [k for k in matches if self._name_part(k).lower() == typed.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        return None

    def _commit_product_typed(self, event=None):
        """If the typed text points to exactly ONE product, pick it."""
        try:
            if self._split_product_text(self.product.get())[0]:
                return   # valid product (with or without a note) - keep the text as typed
            key = self._resolve_product_key()
            if key and key != self.product.get().strip():
                self.product.set(key)
        except Exception:
            pass

    # ----- Customer -----
    def _setup_customer_search(self):
        try:
            cb = self._find_combobox_for_var(self.customer, self)
            if not cb:
                return
            self.customer_cb = cb
            cb.configure(state='normal')
            cb.bind('<KeyRelease>', self._on_customer_typed, add='+')
            cb.bind('<<ComboboxSelected>>', self._on_customer_list_picked, add='+')
            cb.bind('<Return>', lambda e: self._commit_customer_typed(e), add='+')
            cb.bind('<FocusOut>', lambda e: self._commit_customer_typed(e, only_if_partial=True), add='+')
            self._customer_popup = _SuggestPopup(cb, self._customer_matches, self._pick_customer_from_popup)
        except Exception:
            pass

    def _customer_all_keys(self):
        return sorted(getattr(self, 'customer_map', {}).keys(), key=str.lower)

    def _on_customer_typed(self, event=None):
        if event is not None and getattr(event, 'keysym', '') in self._IGNORE_KEYS:
            return
        cb = getattr(self, 'customer_cb', None)
        if cb is None:
            return
        cb['values'] = self._search_keys(self._customer_all_keys(), self.customer.get())
        cp = getattr(self, '_customer_popup', None)
        if cp is not None:
            cp.refresh()

    def _customer_matches(self):
        typed = self.customer.get().strip()
        if not typed or typed in getattr(self, 'customer_map', {}):
            return []
        return self._search_keys(self._customer_all_keys(), typed)

    def _pick_customer_from_popup(self, key):
        self.customer.set(key)
        self.on_customer_selected(user_pick=True)
        self._on_customer_list_picked()

    def _on_customer_list_picked(self, event=None):
        cb = getattr(self, 'customer_cb', None)
        if cb is not None:
            cb['values'] = self._customer_all_keys()

    def _commit_customer_typed(self, event=None, only_if_partial=False):
        """If the typed text points to exactly ONE customer, pick it (same
        as choosing it from the dropdown)."""
        try:
            typed = self.customer.get().strip()
            cmap = getattr(self, 'customer_map', {})
            if not typed:
                return
            if typed in cmap:
                if only_if_partial:
                    return
                key = typed
            else:
                matches = self._search_keys(self._customer_all_keys(), typed)
                exact = [k for k in matches if self._name_part(k).lower() == typed.lower()]
                key = exact[0] if len(exact) == 1 else (matches[0] if len(matches) == 1 else None)
            if key:
                self.customer.set(key)
                self.on_customer_selected(user_pick=True)
        except Exception:
            pass

    # ---------- Hide the inherited base "Customer Details" block ----------
    def _hide_base_customer_details(self):
        container=getattr(self,'body',None) or self
        self._hide_labelframe_by_title(container,'Customer Details')

    def _hide_labelframe_by_title(self,widget,title):
        try:
            children=widget.winfo_children()
        except Exception:
            return
        for w in children:
            try:
                if isinstance(w,ttk.LabelFrame) and w.cget('text').strip()==title:
                    w.pack_forget()
                    continue
            except Exception:
                pass
            self._hide_labelframe_by_title(w,title)

    # ---------- Challan = NO GST: remove every GST field from this screen ----------
    _GST_TEXT_CLASSES=('TLabel','Label','TCheckbutton','Checkbutton','TRadiobutton','Radiobutton',
                       'TButton','Button','TLabelframe','Labelframe','TMenubutton','Menubutton')
    _INPUT_CLASSES=('TEntry','Entry','TCombobox','Spinbox','TSpinbox')

    def _hide_gst_widgets(self):
        try:
            root=getattr(self,'body',None) or self
            found=[]
            self._collect_gst_widgets(root,found)
            for w in found:
                self._hide_widget(w)
        except Exception:
            pass

    def _collect_gst_widgets(self,widget,out):
        try:
            children=widget.winfo_children()
        except Exception:
            return
        for w in children:
            try:
                text=str(w.cget('text') or '')
            except Exception:
                text=''
            try:
                cls=w.winfo_class()
            except Exception:
                cls=''
            if 'gst' in text.lower() and cls in self._GST_TEXT_CLASSES:
                out.append(w)
                out.extend(self._input_partners(w))
                continue
            self._collect_gst_widgets(w,out)

    def _input_partners(self,label):
        found=[]
        try:
            parent=label.master
            mgr=label.winfo_manager()
            if mgr=='grid':
                g=label.grid_info();r=int(g.get('row',0));c=int(g.get('column',0))
                for s in parent.grid_slaves():
                    if s is label or s.winfo_class() not in self._INPUT_CLASSES:
                        continue
                    gi=s.grid_info();sr=int(gi.get('row',0));sc=int(gi.get('column',0))
                    if (sc==c and sr==r+1) or (sr==r and sc==c+1):
                        found.append(s)
            elif mgr=='pack':
                slaves=parent.pack_slaves()
                i=slaves.index(label)
                if i+1<len(slaves) and slaves[i+1].winfo_class() in self._INPUT_CLASSES:
                    found.append(slaves[i+1])
        except Exception:
            pass
        return found

    @staticmethod
    def _hide_widget(w):
        try:
            mgr=w.winfo_manager()
            if mgr=='grid':
                w.grid_remove()
            elif mgr=='pack':
                w.pack_forget()
            elif mgr=='place':
                w.place_forget()
        except Exception:
            pass

    # ---------- ONE-TIME DB MIGRATIONS this screen needs ----------
    def _ensure_challan_payment_mode_column(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challans)')]
            if 'payment_mode' not in cols:
                c.execute("ALTER TABLE challans ADD COLUMN payment_mode TEXT")

    def _ensure_challan_vehicle_column(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challans)')]
            if 'vehicle' not in cols:
                c.execute("ALTER TABLE challans ADD COLUMN vehicle TEXT")
            icols=[r['name'] for r in c.execute('PRAGMA table_info(invoices)')]
            if icols and 'vehicle' not in icols:
                c.execute("ALTER TABLE invoices ADD COLUMN vehicle TEXT")

    def _vehicle_names(self):
        # Previously used vehicle names (Challans + Invoices) for the dropdown.
        names=set()
        try:
            with conn() as c:
                for tbl in ('challans','invoices'):
                    try:
                        for r in c.execute(f"SELECT DISTINCT TRIM(vehicle) FROM {tbl} WHERE vehicle IS NOT NULL AND TRIM(vehicle)!=''"):
                            names.add(r[0])
                    except Exception:
                        pass
        except Exception:
            pass
        return sorted(names,key=str.lower)

    def _ensure_product_loading_column(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(products)')]
            if 'default_loading' not in cols:
                c.execute("ALTER TABLE products ADD COLUMN default_loading REAL DEFAULT 0")

    def _ensure_challan_item_loading_column(self):
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challan_items)')]
            if 'loading' not in cols:
                c.execute("ALTER TABLE challan_items ADD COLUMN loading REAL DEFAULT 0")

    def _ensure_challan_item_date_column(self):
        # Each challan_items row remembers its OWN date (the Date box
        # value at the moment that particular product was added). Old rows
        # will have NULL here and fall back to the challan's header date -
        # see refresh_challans_list()'s COALESCE(ci.date, d.date).
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challan_items)')]
            if 'date' not in cols:
                c.execute("ALTER TABLE challan_items ADD COLUMN date TEXT")

    def _ensure_challan_item_godown_column(self):
        # Each challan_items row remembers its OWN godown, exactly like
        # challan_items.date above. Old rows fall back to the challan's
        # header godown - see refresh_challans_list()'s
        # COALESCE(ci.godown, d.godown).
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challan_items)')]
            if 'godown' not in cols:
                c.execute("ALTER TABLE challan_items ADD COLUMN godown TEXT")

    def _ensure_challan_settled_column(self):
        # 'settled' marks a challan as "already applied/saved" from the
        # Customer Statement window (Apply Payment Mode button). A settled
        # challan's rows there get LOCKED. Editing/saving the challan again
        # (save_doc) resets this back to 0.
        with conn() as c:
            cols=[r['name'] for r in c.execute('PRAGMA table_info(challans)')]
            if 'settled' not in cols:
                c.execute("ALTER TABLE challans ADD COLUMN settled INTEGER DEFAULT 0")

    def _ensure_godown_products_table(self):
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

    # ---------- Product -> item row auto-fill + live Total ----------
    def _schedule_autofill(self,*args):
        try:
            self.after_idle(self._autofill_from_product)
        except Exception:
            pass

    def _clear_skip_autofill(self):
        self._skip_autofill=False

    def _autofill_from_product(self):
        if self._skip_autofill:      # we are loading an existing item for Edit - keep its values
            return
        key,_note=self._split_product_text(self.product.get())
        p=self.product_map.get(key) if (key and hasattr(self,'product_map')) else None
        if not p:
            self._last_autofill_pid=None
            return
        # typing a note after the product must not reset Qty / Rate again
        if p.get('id')==self._last_autofill_pid:
            return
        self._last_autofill_pid=p.get('id')
        try:
            with conn() as c:
                row=c.execute('SELECT * FROM products WHERE id=?',(p['id'],)).fetchone()
            if row:
                p=dict(row)   # always the latest Product Master values
        except Exception:
            pass
        self.qty.set(fnum(product_qty(p)))
        self.price.set(fnum(product_rate(p)))
        self.item_loading.set(fnum(product_loading(p)))      # per unit
        self.item_weight.set(fnum(p.get('weight_kg')))       # per unit
        self.item_unit.set(p.get('unit') or 'Nos')
        self.item_hsn.set(p.get('hsn_sac') or '')

    def _update_total(self,*args):
        """Loading is PER UNIT:  Total = Qty x Rate + Qty x Loading."""
        if not hasattr(self,'item_total'):
            return
        try:
            q=num(self.qty.get());r=num(self.price.get());l=num(self.item_loading.get())
            self.item_total.set(f'{q*r+q*l:,.2f}')
        except Exception:
            pass

    def _reset_item_inputs(self):
        self.editing_item_idx=None
        self._last_autofill_pid=None
        if hasattr(self,'add_btn_text'):
            self.add_btn_text.set('Add Item')
        self.qty.set('1')
        self.price.set('')
        self.product.set('')
        self.item_loading.set('0')
        self.item_weight.set('0')
        self.item_unit.set('Nos')
        self.item_hsn.set('')

    def _on_clear_clicked(self):
        """Clear button: in Edit mode = cancel the edit (clean form). Otherwise just clear the item row."""
        if self.edit_mode:
            self.new_doc()
            self.refresh_challans_list()
        else:
            self._reset_item_inputs()

    def _load_item_for_edit(self,idx):
        """Put an existing item back into the item row. 'Update Item' then REPLACES it."""
        it=self.items[idx]
        key=next((k for k,p in self.product_map.items() if p.get('id')==it.get('product_id')),None)
        self._skip_autofill=True
        try:
            self.editing_item_idx=idx
            self._last_autofill_pid=it.get('product_id')
            # restore THIS item's own saved date into the Date box
            if it.get('date'):
                self.dt.set(it.get('date'))
                self._update_day()
                self._date_manually_edited=False
            # restore THIS item's own saved godown into the Godown box
            # (done BEFORE the product is set, because changing the Godown
            # re-filters the product list and would clear the Product box)
            if it.get('godown'):
                self.c_godown.set(it.get('godown'))
                self._on_godown_changed_filter_products(keep=True)
            self.qty.set(fnum(it.get('qty')))
            self.price.set(fnum(it.get('price')))
            self.item_loading.set(fnum(it.get('loading')))
            q=num(it.get('qty'))
            self.item_weight.set(fnum(num(it.get('weight_kg'))/q if q else 0))   # back to per-unit
            self.item_unit.set(it.get('unit') or 'Nos')
            self.item_hsn.set(it.get('hsn_sac') or '')
            # saved item name = product name + note -> put the note back after the product
            shown=key or it.get('item_name') or ''
            if key:
                base=(self.product_map[key].get('item_name') or '').strip()
                saved=(it.get('item_name') or '').strip()
                if base and saved.lower().startswith(base.lower()) and saved[len(base):].strip():
                    shown=key+'    '+saved[len(base):].strip()
            # Product LAST so nothing can clear it
            self.product.set(shown)
            self.add_btn_text.set('Update Item')
        finally:
            self.after_idle(self._clear_skip_autofill)

    # ---------- Godown -> Product dropdown filter ----------
    def _get_product_combobox(self):
        return getattr(self,'product_cb',None)

    def _find_combobox_for_var(self, var, root):
        try:
            children=root.winfo_children()
        except Exception:
            return None
        for w in children:
            try:
                if isinstance(w, ttk.Combobox) and str(w.cget('textvariable'))==str(var):
                    return w
            except Exception:
                pass
            found=self._find_combobox_for_var(var, w)
            if found:
                return found
        return None

    def _on_godown_changed_filter_products(self, *args, keep=False):
        self._rebuild_product_map_with_units()
        cb=self._get_product_combobox()
        if not cb or not hasattr(self,'product_map'):
            return
        godown_name=self.c_godown.get().strip() if hasattr(self,'c_godown') else ''
        godown_id=self.godown_id_map.get(godown_name)
        if not godown_id:
            keys=sorted(self.product_map.keys())
        else:
            with conn() as c:
                allowed_ids={r['product_id'] for r in c.execute(
                    'SELECT product_id FROM godown_products WHERE godown_id=?', (godown_id,)
                )}
            keys=sorted(
                key for key, p in self.product_map.items()
                if p.get('id') in allowed_ids
            )
        cb['values']=keys
        self._product_all_keys=list(keys)
        if not keep:
            pk, _note = self._split_product_text(self.product.get())
            if pk is None or pk not in keys:
                self.product.set('')

    def _update_saved_table_columns(self):
        if not hasattr(self,'clist'):
            return
        base=[k for k,_ in self.CLIST_COLS]
        self.visible_ccols=base+[k for k,_ in self.CLIST_ACTIONS]
        self.clist.configure(displaycolumns=self.visible_ccols)

    def _configure_item_table(self):
        if not hasattr(self, 'tree'):
            return

        cols = ('item_name', 'hsn_sac', 'qty', 'unit', 'weight', 'loading', 'price', 'amount')
        headings = {
            'item_name': 'Item Name',
            'hsn_sac': 'HSN/ SAC',
            'qty': 'Quantity',
            'unit': 'Unit',
            'weight': 'Weight (kg)',
            'loading': 'Loading/Unit (₹)',
            'price': 'Price/ Unit (₹)',
            'amount': 'Amount (₹)',
        }
        widths = {
            'item_name': 220, 'hsn_sac': 100, 'qty': 80, 'unit': 80,
            'weight': 95, 'loading': 110, 'price': 110, 'amount': 115,
        }

        try:
            self.tree.configure(columns=cols, show='headings')
            for col in cols:
                self.tree.heading(col, text=headings[col])
                self.tree.column(
                    col, width=widths[col], minwidth=70,
                    anchor='center' if col != 'item_name' else 'w', stretch=True
                )
        except Exception:
            return

        self._refresh_item_table()

    def _refresh_item_table(self):
        if not hasattr(self, 'tree'):
            return

        try:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
        except Exception:
            return

        for i, item in enumerate(getattr(self, 'items', []), start=1):
            qty = num(item.get('qty'))
            price = num(item.get('price'))
            loading = num(item.get('loading'))
            weight = num(item.get('weight_kg'))
            # loading is PER UNIT
            amount = num(item.get('amount')) if item.get('amount') is not None else qty * (price + loading)

            values = (
                item.get('item_name') or '',
                item.get('hsn_sac') or '',
                self._fmt_num(qty),
                item.get('unit') or '',
                self._fmt_num(weight),
                f'{loading:,.2f}',
                f'{price:,.2f}',
                f'{amount:,.2f}',
            )
            try:
                self.tree.insert('', 'end', iid=f'item_{i}', values=values)
            except Exception:
                try:
                    self.tree.insert('', 'end', values=values)
                except Exception:
                    pass

    @staticmethod
    def _fmt_num(value):
        value = float(value or 0)
        return str(int(value)) if value.is_integer() else f'{value:g}'

    def redraw(self):
        try:
            result = super().redraw()
        except Exception:
            result = None
        self._refresh_item_table()
        self._hide_gst_widgets()
        try:
            self._on_godown_changed_filter_products(keep=True)   # keep product list fresh
        except Exception:
            pass
        return result

    def _update_day(self,*args):
        ds=self.dt.get().strip();day=''
        for fmt in ('%d-%m-%Y','%Y-%m-%d','%d/%m/%Y'):
            try:day=datetime.strptime(ds,fmt).strftime('%A');break
            except Exception:continue
        self.day_var.set(day)

    def next_format_bill_no(self,mode):
        prefix='GST' if str(mode).upper()=='GST' else 'NO_GST'
        with conn() as c:
            rows=c.execute('SELECT number,gst_mode FROM challans').fetchall()
        nums=[]
        for r in rows:
            if str(r['gst_mode'] or 'GST').upper()!=prefix:continue
            m=re.search(r'(\d+)\s*$',str(r['number'] or ''))
            if m:nums.append(int(m.group(1)))
        return str(max(nums,default=0)+1)

    # ---------- Typing an old Challan No. auto-loads that challan ----------
    def _bind_number_autoload(self):
        """Find the Entry/Combobox bound to self.number and, whenever the
        person finishes typing in it (Tab/click away or Enter), check if
        that Challan No. already exists. If it does, load it automatically
        so 'Add Item' appends to it instead of clashing with the saved one."""
        try:
            root = getattr(self, 'body', None) or self
            widgets = self._widgets_for_var(self.number, root)
        except Exception:
            widgets = []
        for w in widgets:
            try:
                w.bind('<FocusOut>', self._maybe_load_existing_number, add='+')
                w.bind('<Return>', self._maybe_load_existing_number, add='+')
            except Exception:
                pass

    def _maybe_load_existing_number(self, event=None):
        typed = self.number.get().strip()
        if not typed or typed == (self._loaded_number or '').strip():
            return
        try:
            with conn() as c:
                row = c.execute(
                    'SELECT id FROM challans WHERE number=? ORDER BY id DESC LIMIT 1',
                    (typed,)
                ).fetchone()
        except Exception:
            row = None
        if not row:
            return   # new number - nothing saved yet, proceed as a new challan

        did = row['id']
        if self.editing_id and int(self.editing_id) == did:
            return   # already the one that's loaded

        if getattr(self, 'items', None):
            # There is an unsaved product already sitting in the item list
            # for what looked like a brand-new challan - ask before
            # discarding it and switching to the old saved challan.
            if not messagebox.askyesno(
                'Challan No. already used',
                f'Challan No. {typed} is already saved.\n\n'
                'Load it so a new product can be added to it?\n'
                '(Any unsaved item currently on this screen will be cleared.)',
                parent=self
            ):
                self.number.set(self._loaded_number or self.next_format_bill_no('NO_GST'))
                return

        self.load_doc_by_id(did)
        self.edit_mode = False   # this is "continue adding", not a forced Edit
        messagebox.showinfo(
            'Challan Loaded',
            f'Challan No. {typed} already exists and has been loaded.\n'
            'Select a Product and click Add Item to add it to this challan.',
            parent=self
        )

    # ---------- Adding a product must never silently change the Date ----------
    def _bind_date_manual_flag(self):
        """Whenever the person actually types into (or picks a value in)
        the Date box themselves, remember that - so save_doc() knows this
        was a deliberate date change and should NOT be reverted."""
        try:
            root = getattr(self, 'body', None) or self
            widgets = self._widgets_for_var(self.dt, root)
        except Exception:
            widgets = []
        for w in widgets:
            try:
                w.bind('<Key>', self._mark_date_edited, add='+')
                w.bind('<<ComboboxSelected>>', self._mark_date_edited, add='+')
            except Exception:
                pass

    def _mark_date_edited(self, event=None):
        self._date_manually_edited = True

    def set_challan_format(self, mode='NO_GST'):
        self.gst_mode.set('NO_GST')
        if not self.editing_id:
            self.number.set(self.next_format_bill_no('NO_GST'))
        self._update_saved_table_columns()
        self.redraw()
        self.refresh_challans_list(show_draft=bool(self.items))

    def new_doc(self):
        self.edit_mode=False
        super().new_doc()
        self.gst_mode.set('NO_GST')
        if hasattr(self,'pay_mode'):
            self.pay_mode.set('Cash')
        if hasattr(self,'vehicle_var'):
            self.vehicle_var.set('')
        self.number.set(self.next_format_bill_no('NO_GST'))
        # brand-new blank challan - sync the "loaded number" tracker so
        # save_doc() knows this is the current baseline number
        self._loaded_number = self.number.get()
        if hasattr(self,'item_total'):
            self._reset_item_inputs()
        self._refresh_item_table()
        self.dt.set(datetime.now().strftime('%d-%m-%Y'))
        self.time.set(datetime.now().strftime('%I:%M %p'))
        self._update_day()
        self._loaded_date = self.dt.get().strip()
        self._date_manually_edited = False
        self._loaded_godown = self.c_godown.get().strip() if hasattr(self,'c_godown') else ''
        for v in (getattr(self,'c_address',None),getattr(self,'c_contact',None),getattr(self,'c_email',None),
                  getattr(self,'c_state',None),getattr(self,'c_gstin',None),getattr(self,'c_person',None)):
            if v is not None:v.set('')
        self._refresh_customer_due_total()

    def load_customer_godowns(self, customer_id=None, selected=''):
        # Godowns are GLOBAL (not tied to a customer) - `godowns` table.
        with conn() as c:
            rows = c.execute('SELECT id, name FROM godowns ORDER BY name').fetchall()
        vals = [r['name'] for r in rows]
        self.godown_id_map = {r['name']: r['id'] for r in rows}
        if hasattr(self, 'godown_cb'):
            self.godown_cb['values'] = vals
            keep = selected or self.c_godown.get().strip()
            self.c_godown.set(keep if keep in vals else '')

    def on_customer_selected(self,e=None,user_pick=None):
        # e is not None  -> user clicked the Customer combobox
        # e is None      -> called from code (load / add customer)
        if user_pick is None:
            user_pick = e is not None
        key=self.customer.get()
        chosen=self.customer_map.get(key)
        # A saved challan is open (NOT Edit mode) and user picked a DIFFERENT customer -> start a NEW challan
        if user_pick and chosen and self.editing_id and not self.edit_mode:
            try:
                with conn() as c:
                    r=c.execute('SELECT customer_id FROM challans WHERE id=?',
                                (int(self.editing_id),)).fetchone()
            except Exception:
                r=None
            if r and r['customer_id']!=chosen['id']:
                self.new_doc()
                self.customer.set(key)
        super().on_customer_selected(e)
        cust=self.customer_map.get(self.customer.get())
        if cust:
            if hasattr(self,'c_address'):self.c_address.set(cust.get('address','') or '')
            if hasattr(self,'c_contact'):self.c_contact.set(cust.get('contact_no','') or '')
            if hasattr(self,'c_email'):self.c_email.set(cust.get('email','') or '')
            if hasattr(self,'c_state'):self.c_state.set(cust.get('state','') or '')
            if hasattr(self,'c_gstin'):self.c_gstin.set(cust.get('gstin','') or '')
            if hasattr(self,'c_person'):self.c_person.set(cust.get('contact_person','') or '')
            if hasattr(self,'place') and not self.place.get():self.place.set(cust.get('state','') or '')
            self.load_customer_godowns(cust['id'])
        self._refresh_customer_due_total()

    def _refresh_today_total(self):
        """Selected customer's total for TODAY: the sum of every product
        row (of any of this customer's challans) whose own date is today's
        date. Cash / Credit / NEFT and settled / unsettled are all counted.
        Today's date comes from the system clock, not from the Date box."""
        if not hasattr(self,'today_total_var'):
            return
        cust=self.customer_map.get(self.customer.get()) if hasattr(self,'customer_map') else None
        if not cust:
            self.today_total_var.set('₹0.00')
            return
        try:
            today=datetime.now().strftime('%d-%m-%Y')
            with conn() as c:
                row=c.execute(
                    "SELECT COALESCE(SUM(ci.amount),0) AS t "
                    "FROM challans d JOIN challan_items ci ON ci.challan_id=d.id "
                    "WHERE d.customer_id=? AND COALESCE(ci.date,d.date)=?",
                    (cust['id'],today)
                ).fetchone()
            self.today_total_var.set(f"₹{float(row['t'] or 0):,.2f}")
        except Exception:
            self.today_total_var.set('₹0.00')

    def _refresh_customer_due_total(self):
        """Show, right next to the Customer field, the total of THIS
        customer's Challans that are NOT YET SETTLED (i.e. haven't been
        applied via the Customer Statement window's "Apply Payment Mode
        to Selected" button) - whatever their Payment Mode is (Cash,
        Credit or NEFT). Editing/saving a settled challan again brings it
        back in (settled resets to 0).
        Also refreshes the "Today Total" box beside it."""
        self._refresh_today_total()
        if not hasattr(self,'customer_due_var'):
            return
        cust=self.customer_map.get(self.customer.get()) if hasattr(self,'customer_map') else None
        if not cust:
            self.customer_due_var.set('₹0.00')
            return
        try:
            with conn() as c:
                row=c.execute(
                    "SELECT COALESCE(SUM(total),0) AS due FROM challans "
                    "WHERE customer_id=? AND COALESCE(settled,0)=0",
                    (cust['id'],)
                ).fetchone()
            self.customer_due_var.set(f"₹{float(row['due'] or 0):,.2f}")
        except Exception:
            self.customer_due_var.set('₹0.00')

    def current_customer(self):
        cust=self.customer_map.get(self.customer.get())
        if not cust:return None
        cust=dict(cust)
        if hasattr(self,'c_address'):
            cust['address']=self.c_address.get().strip() or cust.get('address','')
            cust['contact_no']=self.c_contact.get().strip() or cust.get('contact_no','')
            cust['email']=self.c_email.get().strip() or cust.get('email','')
            cust['state']=self.c_state.get().strip() or cust.get('state','')
            cust['gstin']=self.c_gstin.get().strip() or cust.get('gstin','')
            cust['contact_person']=self.c_person.get().strip() or cust.get('contact_person','')
            cust['godown']=self.c_godown.get().strip()
        return cust

    def _document_customer(self, cust=None):
        """Return customer data for this Challan document.

        Challan is permanently WITHOUT GST. Keep the GSTIN in Customer Master,
        but never pass it into the Challan PDF/document data.
        """
        out = dict(cust or self.current_customer() or {})
        out['gstin'] = ''
        return out

    # ------------------------------------------------------------------
    # NEW: PDF for ONE specific challan id, straight from the database.
    # Print / Download buttons of a row use this, so the PDF is ALWAYS
    # the challan that was clicked - never "the last challan".
    # ------------------------------------------------------------------
    def _pdf_for_challan_id(self, cid, copies=1, path=None):
        """Builds the PDF of the challan with this id directly from the DB.
        Does not touch the screen (no load_doc_by_id / new_doc) and has NO
        'latest challan' fallback."""
        with conn() as c:
            d = c.execute('SELECT * FROM challans WHERE id=?', (int(cid),)).fetchone()
            if not d:
                raise RuntimeError('Challan sapadla nahi.')
            d = dict(d)
            cu = c.execute('SELECT * FROM customers WHERE id=?', (d.get('customer_id'),)).fetchone()
            rows = c.execute(
                'SELECT * FROM challan_items WHERE challan_id=? ORDER BY rowid',
                (int(cid),)
            ).fetchall()

        cust = dict(cu) if cu else {}
        cust['gstin'] = ''          # challan is WITHOUT GST

        items = []
        for r in rows:
            r = dict(r)
            # each item keeps its own godown / date; old rows fall back to the challan header
            r['godown'] = (r.get('godown') or '').strip() or (d.get('godown') or '')
            r['date'] = (r.get('date') or '').strip() or (d.get('date') or '')
            items.append(r)
        if not items:
            raise RuntimeError('Ya challan madhe ekhi product nahi.')

        header = {
            'number': d.get('number') or 'DOC',
            'date': d.get('date') or '',
            'place_of_supply': d.get('place_of_supply') or '',
            'subtotal': float(d.get('subtotal') or 0),
            'cgst': 0.0,
            'sgst': 0.0,
            'freight': float(d.get('freight') or 0),
            'total': float(d.get('total') or 0),
            'description': d.get('description') or '',
            'godown': d.get('godown') or '',
            'gst_mode': 'NO_GST',
            'copies': copies,
            'payment_mode': d.get('payment_mode') or '',
            'vehicle': d.get('vehicle') or '',
        }
        if path is None:
            path = os.path.join(
                tempfile.gettempdir(),
                f'challan_{cid}_{datetime.now().strftime("%H%M%S")}.pdf'
            )
        return make_pdf('challan', header, cust, items, path=path)

    def ensure_pdf(self):
        """Create the Challan PDF without Customer/Item mandatory validation."""
        cust = self.current_customer() or {}
        was_blank = (not cust) and not self.items

        if was_blank:
            did = self.editing_id
            if not did:
                try:
                    with conn() as c:
                        row = c.execute(
                            'SELECT id FROM challans ORDER BY id DESC LIMIT 1'
                        ).fetchone()
                        did = row['id'] if row else None
                except Exception:
                    did = None
            if did:
                try:
                    self.load_doc_by_id(int(did))
                    cust = self.current_customer() or {}
                except Exception:
                    pass

        try:
            sub, cgst, sgst, total = self.totals()
            # WITHOUT GST Challan: GSTIN must NOT go into the Challan PDF.
            # Customer Master GSTIN is kept unchanged.
            doc_cust = self._document_customer(cust)
            self.last_pdf = make_pdf(
                'challan',
                self.pdf_header(sub, cgst, sgst, total),
                doc_cust,
                self.items or []
            )
        except Exception as e:
            messagebox.showerror('PDF', f'Could not create challan PDF:\n{e}')
            return None

        if was_blank:
            saved_pdf = self.last_pdf
            self.new_doc()
            self.last_pdf = saved_pdf

        return self.last_pdf

    def print_current(self, copies=None):
        """Main 'Print' button: how many copie."""
        n = copies if copies else self._ask_copies()
        if not n:
            return
        old = self._print_copies
        self._print_copies = n
        try:
            self._print_current_impl()
        finally:
            self._print_copies = old

    def _selected_challan_id(self):
        """Saved Challans madhe jo challan select kelay tyacha id.
        1) highlight kelela row  2) 'Select' column ne tick kelele rows
        (fakt ekach challan che astil tar). Nasel tar None."""
        try:
            sel = [s for s in self.clist.selection() if not str(s).startswith('draft')]
            if sel:
                return self._split_row(sel[0])[0]
        except Exception:
            pass
        cids = {self._split_row(i)[0] for i in getattr(self, '_sel_cids', set())
                if not str(i).startswith('draft')}
        if len(cids) == 1:
            return cids.pop()
        return None

    def _print_current_impl(self):
        """Main Print button.
        - Screen var items astil (challan load kela / add kela) -> tech print hoto.
        - Nasel tar Saved Challans madhe select kelela challan print hoto.
        'Last challan' kadhich print hot nahi."""
        try:
            if getattr(self, 'items', None):
                sub, cgst, sgst, total = self.totals()
                no = str(self.number.get()).strip() or 'DOC'
                pdf_path = os.path.join(
                    tempfile.gettempdir(),
                    f'challan_{no}_{datetime.now().strftime("%H%M%S")}.pdf'
                )
                pdf = make_pdf(
                    'challan',
                    self.pdf_header(sub, cgst, sgst, total),
                    self._document_customer(self.current_customer() or {}),
                    self.items,
                    path=pdf_path
                )
            else:
                cid = self._selected_challan_id()
                if not cid:
                    raise RuntimeError(
                        'Saved Challans madhe aadhi ek challan select kara '
                        '(row var click kara), kinva row madhla Print button vapra.'
                    )
                pdf = self._pdf_for_challan_id(cid, copies=self._print_copies)
            self.last_pdf = pdf
            os.startfile(pdf)
        except Exception as e:
            messagebox.showerror(
                'Print Failed',
                f'Could not open challan for printing:\n{e}'
            )

    def whatsapp_current(self):
        was_blank = not self.last_pdf and not self.items and not self.current_customer()

        if not self.last_pdf:
            did=self.editing_id or self.doc_map.get(self.existing_doc.get())
            if not did:
                try:
                    with conn() as c:
                        row=c.execute('SELECT id FROM challans ORDER BY id DESC LIMIT 1').fetchone()
                        did=row['id'] if row else None
                except Exception:
                    did=None
            if did:
                self.load_doc_by_id(did)
            else:
                if not self.ensure_pdf():
                    return
        if not self.last_pdf:
            self.last_pdf = self.ensure_pdf()
        if not self.last_pdf:
            return
        cust=self.current_customer() or {}
        phone=simpledialog.askstring('WhatsApp','Enter WhatsApp number',initialvalue=cust.get('contact_no',''))
        if not phone:
            if was_blank:
                saved_pdf=self.last_pdf
                self.new_doc()
                self.last_pdf=saved_pdf
            return
        try:
            result=open_whatsapp(phone,f'Challan {self.number.get()} generated. Total Rs. {self.totals()[3]:.2f}.',self.last_pdf)
            messagebox.showinfo('WhatsApp',result)
        except Exception as e:
            messagebox.showerror('WhatsApp','Could not send challan PDF:\n'+str(e))
        finally:
            if was_blank:
                saved_pdf=self.last_pdf
                self.new_doc()
                self.last_pdf=saved_pdf

    def _auto_sync_route_rate(self):
        """Automatically add/update Challan From/To/Rate/Type in Route Rate Master."""
        try:
            frm = self.from_city.get().strip()
            to = self.to_city.get().strip()
            rate_text = self.freight_rate.get().strip()
            rtype = self.rate_type.get().strip() or 'Per Kg'

            if not frm or not to or not rate_text:
                return
            rate = float(rate_text)
            if rate <= 0:
                return

            with conn() as c:
                existing = c.execute(
                    'SELECT id FROM routes WHERE lower(from_city)=lower(?) '
                    'AND lower(to_city)=lower(?) ORDER BY id DESC LIMIT 1',
                    (frm, to)
                ).fetchone()

                if existing:
                    c.execute(
                        'UPDATE routes SET rate=?,rate_type=? WHERE id=?',
                        (rate, rtype, existing['id'])
                    )
                else:
                    c.execute(
                        'INSERT INTO routes(from_city,to_city,rate,rate_type) VALUES(?,?,?,?)',
                        (frm, to, rate, rtype)
                    )

            try:
                routes_tab = self.app.tab_names.get('Routes')
                if routes_tab is not None and hasattr(routes_tab, 'load'):
                    routes_tab.load()
            except Exception:
                pass
        except (ValueError, TypeError, AttributeError, Exception):
            pass

    def load_route_rate(self):
        with conn() as c:r=c.execute('SELECT rate,rate_type FROM routes WHERE lower(from_city)=lower(?) AND lower(to_city)=lower(?) ORDER BY id DESC LIMIT 1',(self.from_city.get().strip(),self.to_city.get().strip())).fetchone()
        if not r:return messagebox.showwarning('Route','No matching route rate found')
        self.freight_rate.set(str(r['rate']));self.rate_type.set(r['rate_type']);self.redraw()

    def add_route(self):
        """Compatibility method: route sync is now automatic."""
        self._auto_sync_route_rate()

    def after_load_doc(self,doc):
        # Make sure the Date box always reflects the ACTUAL saved Date of
        # the challan being loaded, and remember it as the baseline that
        # save_doc()'s DATE GUARD protects until the person edits it.
        if doc.get('date'):
            self.dt.set(doc.get('date'))
        self.place.set(doc.get('place_of_supply') or '');self.from_city.set(doc.get('from_city') or '');self.to_city.set(doc.get('to_city') or '');self.freight_rate.set(str(doc.get('freight_rate') or 0));self.rate_type.set(doc.get('freight_rate_type') or 'Per Kg');self.desc.set(doc.get('description') or '')
        self.c_godown.set(doc.get('godown') or '')
        self.gst_mode.set('NO_GST')
        self.pay_mode.set(doc.get('payment_mode') or 'Cash')
        _veh=doc.get('vehicle')
        if _veh is None:
            try:
                with conn() as c:
                    _r=c.execute('SELECT vehicle FROM challans WHERE number=? ORDER BY id DESC LIMIT 1',(doc.get('number'),)).fetchone()
                _veh=_r['vehicle'] if _r else ''
            except Exception:
                _veh=''
        self.vehicle_var.set(_veh or '')
        if doc.get('customer_id'): self.load_customer_godowns(doc.get('customer_id'), doc.get('godown') or '')
        self._refresh_customer_due_total()
        if hasattr(self,'item_total'):
            self._reset_item_inputs()
        self.time.set(doc.get('time') or datetime.now().strftime('%I:%M %p'))
        self._update_day()
        # a saved challan was just loaded - this number/date/godown are now
        # the baseline for save_doc()'s "did the user manually change it?" checks
        self._loaded_number = doc.get('number') or self.number.get()
        self._loaded_date = self.dt.get().strip()
        self._date_manually_edited = False
        self._loaded_godown = self.c_godown.get().strip()

        # ---- RESTORE EACH ITEM'S OWN DATE AND GODOWN ----------------
        # The base DocEditor's generic item-loading does not know about our
        # challan_items.date / godown columns, so re-read the real
        # per-item values straight from the DB, in the same row order the
        # items were loaded in, and merge them back into self.items.
        did = self.editing_id or doc.get('id') or doc.get(self.id_field)
        if did and getattr(self, 'items', None):
            try:
                with conn() as c:
                    extra_rows = c.execute(
                        'SELECT date, godown FROM challan_items WHERE challan_id=? ORDER BY rowid ASC',
                        (int(did),)
                    ).fetchall()
                for it, dr in zip(self.items, extra_rows):
                    it['date'] = (dr['date'] or '').strip() or self._loaded_date
                    it['godown'] = (dr['godown'] or '').strip() or self._loaded_godown
            except Exception:
                pass
        # ---------------------------------------------------------------------

    def totals(self):
        sub = sum(float(x.get('amount', 0) or 0) for x in self.items)
        cgst = 0.0
        sgst = 0.0
        kg = sum(float(x.get('weight_kg', 0) or 0) for x in self.items)
        rate = float(self.freight_rate.get() or 0)
        rate_type = self.rate_type.get().lower()
        if rate_type.startswith('per kg'):
            freight = rate * kg
        elif rate_type.startswith('per box'):
            freight = rate * sum(float(x.get('qty', 0) or 0) for x in self.items)
        else:
            freight = rate
        return sub, cgst, sgst, sub + freight

    def _ask_copies(self):
        """Print / Download How many copies """
        return simpledialog.askinteger(
            'Copies',
            'how many copies?\n(2 copies = 1 A4 )',
            parent=self, minvalue=1, maxvalue=10, initialvalue=2
        )

    def pdf_header(self,sub,cgst,sgst,total):
        freight=total-sub-cgst-sgst
        from_city=self.from_city.get().strip() if hasattr(self,'from_city') else ''
        to_city=self.to_city.get().strip() if hasattr(self,'to_city') else ''
        route=f'{from_city} - {to_city}'.strip(' -')
        return {'number':self.number.get(),'date':self.dt.get(),'place_of_supply':self.place.get(),'subtotal':sub,'cgst':cgst,'sgst':sgst,'freight':freight,'total':total,'description':self.desc.get(),'godown':self.c_godown.get(),
                'gst_mode':'NO_GST',
                'copies':getattr(self,'_print_copies',1),
                'payment_mode':self.pay_mode.get() if hasattr(self,'pay_mode') else '',
                'vehicle':self.vehicle_var.get().strip(),
                'day':self.day_var.get() if hasattr(self,'day_var') else '','time':self.time.get() if hasattr(self,'time') else '',
                'from_city':from_city,
                'to_city':to_city,
                'freight_rate':self.freight_rate.get().strip() if hasattr(self,'freight_rate') else '',
                'freight_rate_type':self.rate_type.get().strip() if hasattr(self,'rate_type') else '',
                'route':route}

    def after_import_csv(self,row):
        self.place.set(row.get('place_of_supply') or row.get('state') or self.place.get())
        self.from_city.set(row.get('from_city') or self.from_city.get())
        self.to_city.set(row.get('to_city') or self.to_city.get())
        self.freight_rate.set(row.get('freight_rate') or row.get('freight') or self.freight_rate.get())
        self.rate_type.set(row.get('freight_rate_type') or row.get('rate_type') or self.rate_type.get())
        self.desc.set(row.get('notes') or row.get('description') or self.desc.get())

    def _start_next_challan_keep_inputs(self):
        """Current challan is full (10 products). Start a NEW challan with the
        next Challan No., keep the same Customer / Godown / Payment Mode /
        Date, and keep the product that is currently typed in the item row
        so it becomes product no. 1 of the new challan."""
        keep = {
            'customer': self.customer.get(),
            'godown': self.c_godown.get(),
            'pay': self.pay_mode.get(),
            'vehicle': self.vehicle_var.get(),
            'date': self.dt.get(),
            'place': self.place.get(),
            'product': self.product.get(),
            'qty': self.qty.get(),
            'price': self.price.get(),
            'loading': self.item_loading.get(),
            'weight': self.item_weight.get(),
            'unit': self.item_unit.get(),
            'hsn': self.item_hsn.get(),
        }
        self._skip_autofill = True          # do not overwrite the typed Qty / Rate
        try:
            self.new_doc()                  # new number, empty item list, editing_id=None
            if keep['customer']:
                self.customer.set(keep['customer'])
                self.on_customer_selected()
            self.c_godown.set(keep['godown'])
            self.pay_mode.set(keep['pay'] or 'Cash')
            self.vehicle_var.set(keep['vehicle'])
            self.dt.set(keep['date'])
            self._update_day()
            self._loaded_date = self.dt.get().strip()
            self._date_manually_edited = False
            if keep['place']:
                self.place.set(keep['place'])
            # product LAST (changing godown re-filters the product list)
            self.product.set(keep['product'])
            self.qty.set(keep['qty'])
            self.price.set(keep['price'])
            self.item_loading.set(keep['loading'])
            self.item_weight.set(keep['weight'])
            self.item_unit.set(keep['unit'])
            self.item_hsn.set(keep['hsn'])
            pk, _n = self._split_product_text(keep['product'])
            pp = self.product_map.get(pk) if pk else None
            self._last_autofill_pid = pp.get('id') if pp else None
        finally:
            self.after_idle(self._clear_skip_autofill)

    def add_item(self):
        """Add a product to the challan - or, in Edit mode, UPDATE the selected item.

        Loading is per unit:
            Amount       = Qty x Rate + Qty x Loading
            Total weight = Weight per unit x Qty
        """
        was_edit = self.edit_mode

        # typed (not picked) Customer / Product -> resolve to the single match
        self._commit_customer_typed(only_if_partial=True)
        self._commit_product_typed()

        # 1) If an already-saved Challan is open and the user MANUALLY
        #    changes the Bill/Challan No. without clicking Edit, this is a
        #    completely NEW Challan. Never carry the old items into it.
        # 2) If the Challan No. is NOT changed, keep the existing items and
        #    append ONLY the product currently selected in the Product
        #    dropdown.
        number_changed = (
            self.editing_id
            and not self.edit_mode
            and self.number.get().strip() != (self._loaded_number or '').strip()
        )

        if number_changed:
            self.editing_id = None
            self.items = []
            self.editing_item_idx = None
            self._refresh_item_table()

        # Maximum 10 products per Challan (MAX_ITEMS). Put this check AFTER
        # the new-number reset, otherwise a full old Challan could block
        # creation of a new Bill.
        if not self.edit_mode and len(getattr(self, 'items', [])) >= self.MAX_ITEMS:
            # Current challan already has 10 products (and is already saved).
            # Automatically open a NEW challan with the next number and put
            # this product into it.
            self._start_next_challan_keep_inputs()

        idx = self.editing_item_idx if self.edit_mode else None
        old = self.items[idx] if (idx is not None and 0 <= idx < len(self.items)) else None

        pkey, note = self._split_product_text(self.product.get())
        p = self.product_map.get(pkey) if pkey else None
        if not p and old:
            # product was deleted from the master - keep the item's own details
            p = {'id': old.get('product_id'), 'item_name': old.get('item_name'),
                 'hsn_sac': old.get('hsn_sac'), 'unit': old.get('unit')}
        if not p:
            messagebox.showerror('Item', 'Please select a Product before clicking Add.')
            return
        try:
            q = float(str(self.qty.get()).strip())
            pr = float(str(self.price.get()).strip())
            loading = float(str(self.item_loading.get()).strip() or 0)
            wpu = float(str(self.item_weight.get()).strip() or 0)
            if q <= 0 or pr < 0 or loading < 0 or wpu < 0:
                raise ValueError
        except (ValueError, TypeError):
            messagebox.showerror('Value', 'Quantity (above 0), Rate and Loading must be valid numbers.')
            return

        item = {
            'product_id': p.get('id'),
            # product name + the note typed after it (e.g. "to pune").
            # Saved ONLY in this challan line - Product Master is not changed.
            'item_name': ((p.get('item_name') or '') + (' ' + note if note else '')).strip(),
            'hsn_sac': self.item_hsn.get().strip() or p.get('hsn_sac') or '', 'qty': q,
            'unit': self.item_unit.get().strip() or p.get('unit') or 'Nos', 'price': pr,
            'loading': loading,                      # per unit
            'amount': q * pr + q * loading,
            'weight_kg': wpu * q,
            # THIS product's own date - whatever is in the Date box right
            # now, at the moment it is being added/updated.
            'date': self.dt.get().strip(),
            # THIS product's own godown - whatever is in the Godown box
            # right now. Every other item keeps its own godown.
            'godown': self.c_godown.get().strip(),
        }
        if old is not None:
            self.items[idx] = item          # UPDATE in place - no duplicate
        else:
            self.items.append(item)
        self._reset_item_inputs()
        self.redraw()
        ok = self.save_doc(silent=True)
        if was_edit and ok:
            self.new_doc()                    # edit saved -> clean form, customer cleared
            self.refresh_challans_list()
        else:
            self.refresh_challans_list(show_draft=not self.editing_id)

    def save_doc(self, silent=False):
        """Save/update challan and immediately refresh the Saved Challans table.
        Returns True on success, False on failure."""
        cust = self.current_customer()
        if not cust:
            if self.editing_id:
                try:
                    self.load_doc_by_id(int(self.editing_id))
                    cust = self.current_customer()
                except Exception:
                    cust = None
            if not cust:
                return False
        try:
            # ---- NEW-NUMBER GUARD -----------------------------------------
            # A saved challan is loaded (self.editing_id set) and we are NOT
            # in explicit "Edit" mode. If the person just retyped the
            # Challan No. field, treat this as a brand-new challan: drop
            # editing_id so the INSERT branch below creates a new row
            # instead of overwriting the old one.
            if self.editing_id and not self.edit_mode \
               and self.number.get().strip() != (self._loaded_number or '').strip():
                self.editing_id = None
                self.items = list(self.items)
            # -----------------------------------------------------------------

            # ---- DATE GUARD -------------------------------------------------
            # Simply adding a product to an already-saved challan must NEVER
            # silently change that challan's saved (header) Date. Only
            # restore the original header date if the person did not
            # themselves type a new one into the Date box. Each product's
            # OWN date is separately stored in challan_items.date.
            if self.editing_id and not self._date_manually_edited:
                loaded_date = (self._loaded_date or '').strip()
                if loaded_date and self.dt.get().strip() != loaded_date:
                    self.dt.set(loaded_date)
                    self._update_day()
            # -------------------------------------------------------------------

            gst_rate = 0.0
            freight_rate = float(str(self.freight_rate.get() or 0).strip())
            sub, cgst, sgst, total = self.totals()
            freight = total - sub - cgst - sgst
            tm = self.time.get() if hasattr(self, 'time') else ''
            gmode = 'NO_GST'
            pmode = (self.pay_mode.get() or '').strip() or 'Cash'
            self._auto_sync_route_rate()
            with conn() as c:
                c.execute(
                    'UPDATE customers SET address=?,contact_no=?,email=?,state=?,gstin=?,contact_person=? WHERE id=?',
                    (cust.get('address',''), cust.get('contact_no',''), cust.get('email',''),
                     cust.get('state',''), cust.get('gstin',''), cust.get('contact_person',''), cust['id'])
                )
                if self.editing_id:
                    did = int(self.editing_id)
                    # Editing/re-saving an already-settled challan un-locks
                    # it again in the Customer Statement window (settled=0).
                    c.execute(
                        "UPDATE challans SET number=?,date=?,place_of_supply=?,customer_id=?,godown=?,gst_rate=?,subtotal=?,cgst=?,sgst=?,freight=?,total=?,description=?,from_city=?,to_city=?,freight_rate=?,freight_rate_type=?,time=?,gst_mode=?,payment_mode=?,settled=0 WHERE id=?",
                        (self.number.get().strip(), self.dt.get().strip(), self.place.get().strip(), cust['id'],
                         self.c_godown.get().strip(), gst_rate, sub, cgst, sgst, freight, total,
                         self.desc.get().strip(), self.from_city.get().strip(), self.to_city.get().strip(),
                         freight_rate, self.rate_type.get().strip() or 'Per Kg', tm, gmode, pmode, did)
                    )
                    c.execute('DELETE FROM challan_items WHERE challan_id=?', (did,))
                else:
                    cur = c.execute(
                        "INSERT INTO challans (number,date,place_of_supply,customer_id,godown,gst_rate,subtotal,cgst,sgst,freight,total,description,from_city,to_city,freight_rate,freight_rate_type,time,gst_mode,payment_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.number.get().strip(), self.dt.get().strip(), self.place.get().strip(), cust['id'],
                         self.c_godown.get().strip(), gst_rate, sub, cgst, sgst, freight, total,
                         self.desc.get().strip(), self.from_city.get().strip(), self.to_city.get().strip(),
                         freight_rate, self.rate_type.get().strip() or 'Per Kg', tm, gmode, pmode)
                    )
                    did = cur.lastrowid
                    self.editing_id = did
                for it in self.items:
                    c.execute(
                        "INSERT INTO challan_items (challan_id,product_id,item_name,hsn_sac,qty,unit,price,amount,weight_kg,loading,date,godown) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (did, it['product_id'], it['item_name'], it.get('hsn_sac',''), it['qty'],
                         it.get('unit','Nos'), it['price'], it['amount'], it.get('weight_kg',0), it.get('loading',0),
                         it.get('date') or self.dt.get().strip(),
                         # each item keeps the godown it was actually
                         # added/updated with
                         it.get('godown') or self.c_godown.get().strip())
                    )
            with conn() as c:
                c.execute('UPDATE challans SET vehicle=? WHERE id=?',(self.vehicle_var.get().strip(),did))
            # WITHOUT GST Challan: never send Customer GSTIN to the document/PDF.
            doc_cust = self._document_customer(cust)
            try:
                self.last_pdf = make_pdf(
                    'challan',
                    self.pdf_header(sub, cgst, sgst, total),
                    doc_cust,
                    self.items
                )
            except Exception:
                self.last_pdf = None   # data is saved; PDF is rebuilt on Download / Print
            # save succeeded - this is now the loaded/baseline number, date
            # and godown
            self._loaded_number = self.number.get().strip()
            self._loaded_date = self.dt.get().strip()
            self._date_manually_edited = False
            self._loaded_godown = self.c_godown.get().strip()
            super().load_docs()
            self.refresh_challans_list()
            self._refresh_customer_due_total()
            if not silent:
                messagebox.showinfo('Saved', f'Challan {self.number.get()} saved successfully.')
            return True
        except Exception as e:
            messagebox.showerror('Save / Update Failed', f'Could not save the challan:\n{e}')
            return False

    # ---------- Saved Challans table: ONE ROW PER PRODUCT ----------
    def load_docs(self):
        super().load_docs()
        self.refresh_challans_list()

    def _product_category(self,item):
        pid=item.get('product_id')
        for p in self.product_map.values():
            if p.get('id') == pid:
                return str(p.get('category') or '')
        return ''

    def _draft_values(self, item, sr):
        cust = self.current_customer() or {}
        return (
            self.number.get().strip(),
            str(sr),
            item.get('date') or self.dt.get().strip(),
            cust.get('name') or self.customer.get().split(' - ', 1)[-1],
            item.get('godown') or self.c_godown.get().strip(),
            self.pay_mode.get().strip(),
            self.vehicle_var.get().strip(),
            str(item.get('item_name') or ''),
            fnum(item.get('qty')),
            str(item.get('unit') or ''),
            fnum(item.get('loading')),
            fnum(item.get('price')),
            str(item.get('hsn_sac') or ''),
            f"{float(item.get('amount') or 0):,.2f}",
            'Save first',
            'Save first',
            'Edit',
            'Delete',
            '',
        )

    def refresh_challans_list(self, show_draft=False):
        if not hasattr(self, 'clist'):
            return

        for item_id in self.clist.get_children():
            self.clist.delete(item_id)

        with conn() as c:
            rows = c.execute(
                """
                SELECT d.id AS cid, d.number, d.date, d.godown, d.payment_mode, d.vehicle,
                       d.total AS challan_total,
                       c.name AS customer_name,
                       ci.item_name, ci.qty, ci.unit, ci.loading, ci.price,
                       ci.hsn_sac, ci.amount, ci.rowid AS item_rowid,
                       COALESCE(ci.date, d.date) AS item_date,
                       COALESCE(ci.godown, d.godown) AS item_godown
                FROM challans d
                LEFT JOIN customers c ON c.id = d.customer_id
                LEFT JOIN challan_items ci ON ci.challan_id = d.id
                ORDER BY d.id DESC, ci.rowid ASC
                """
            ).fetchall()

        seq = {}
        for row in rows:
            cid = row['cid']
            has_item = row['item_rowid'] is not None
            if has_item:
                idx = seq.get(cid, 0)
                seq[cid] = idx + 1
                sr = idx + 1
                iid = f'{cid}:{idx}'
                total = row['amount']
                row_date = row['item_date'] or ''
                row_godown = row['item_godown'] or ''
            else:                       # challan with no items - still show it
                idx = -1
                sr = ''
                iid = f'{cid}:-1'
                total = row['challan_total']
                row_date = row['date'] or ''
                row_godown = row['godown'] or ''

            values = (
                row['number'] or '',
                sr,
                row_date,
                row['customer_name'] or '',
                row_godown,
                row['payment_mode'] or '',
                row['vehicle'] or '',
                row['item_name'] or '',
                fnum(row['qty']) if has_item else '',
                (row['unit'] or '') if has_item else '',
                fnum(row['loading']) if has_item else '',
                fnum(row['price']) if has_item else '',
                row['hsn_sac'] or '',
                f"{float(total or 0):,.2f}",
                '⬇ Download',
                '🖶 Print',
                '✎ Edit',
                '✕ Delete',
                '☑' if iid in self._sel_cids else '☐',
            )
            self.clist.insert('', 'end', iid=iid, values=values,
                              tags=('picked',) if iid in self._sel_cids else ())

        if show_draft and self.items:
            for i, it in enumerate(self.items):
                self.clist.insert('', 'end', iid=f'draft{i}',
                                  values=self._draft_values(it, i + 1))
        # forget ticks of rows that no longer exist
        listed = set(self.clist.get_children())
        self._sel_cids = {x for x in getattr(self, '_sel_cids', set()) if x in listed}
        self._update_sel_count()

    @staticmethod
    def _split_row(row_id):
        """'12:3' -> (challan id 12, item position 3).  '12:-1' -> (12, -1)."""
        cid, _, idx = str(row_id).partition(':')
        return int(cid), (int(idx) if idx else -1)

    def on_clist_click(self,event):
        region=self.clist.identify('region',event.x,event.y)
        if region!='cell':return
        col=self.clist.identify_column(event.x)
        row_id=self.clist.identify_row(event.y)
        if not row_id:return
        if str(row_id).startswith('draft'):
            messagebox.showinfo('Not Saved', 'This is the current Add preview. Click Save / Update to permanently save it.')
            return
        idx=int(col.replace('#',''))-1
        if idx<0 or idx>=len(self.visible_ccols):return
        name=self.visible_ccols[idx]
        if name=='dl':self.download_row(row_id)
        elif name=='print':self.print_row(row_id)
        elif name=='wa':self.whatsapp_row(row_id)
        elif name=='mail':self.email_row(row_id)
        elif name=='edit':self.edit_row(row_id)
        elif name=='delete':self.delete_row(row_id)
        elif name=='sel':self._toggle_challan_select(row_id)

    def edit_row(self,row_id):
        """Load the challan and put THIS product back in the item row.
        'Update Item' replaces it - it is never added a second time.
        edit_mode becomes True ONLY here."""
        cid,idx=self._split_row(row_id)
        self.load_doc_by_id(cid)
        self.edit_mode=True                 # only here edit mode starts
        if 0<=idx<len(self.items):
            self._load_item_for_edit(idx)

    def download_row(self,row_id):
        """Download: PDF of EXACTLY the clicked challan, built straight
        from the database (no 'last challan' fallback)."""
        cid,_=self._split_row(row_id)
        n=self._ask_copies()
        if not n:
            return
        try:
            src=self._pdf_for_challan_id(cid, copies=n)
        except Exception as e:
            messagebox.showerror('Download Failed', f'Could not create challan PDF:\n{e}')
            return
        # Save THIS exact PDF directly. (The old generic save_pdf_as() could
        # rebuild the PDF from the screen / the latest challan, so the wrong
        # challan was downloaded.)
        try:
            with conn() as c:
                r=c.execute('SELECT number FROM challans WHERE id=?',(cid,)).fetchone()
            no=str(r['number']) if r and r['number'] else str(cid)
        except Exception:
            no=str(cid)
        dst=filedialog.asksaveasfilename(
            parent=self, defaultextension='.pdf',
            initialfile=f'challan_{no}.pdf', filetypes=[('PDF','*.pdf')]
        )
        if not dst:
            return
        try:
            shutil.copyfile(src, dst)
            messagebox.showinfo('Downloaded', dst, parent=self)
        except Exception as e:
            messagebox.showerror('Download Failed', f'Could not save the PDF:\n{e}', parent=self)

    def print_row(self,row_id):
        """Print: PDF of EXACTLY the clicked challan, built straight from
        the database (no 'last challan' fallback)."""
        cid,_=self._split_row(row_id)
        n=self._ask_copies()
        if not n:
            return
        try:
            pdf=self._pdf_for_challan_id(cid, copies=n)
            self.last_pdf=pdf
            os.startfile(pdf)      # default PDF viewer madhe ughdte
        except Exception as e:
            messagebox.showerror('Print Failed', f'Could not open challan for printing:\n{e}')

    def whatsapp_row(self,row_id):
        cid,_=self._split_row(row_id)
        self.load_doc_by_id(cid)
        self.whatsapp_current()
        self.new_doc()

    def email_row(self,row_id):
        cid,_=self._split_row(row_id)
        self.load_doc_by_id(cid)
        self.email_current()
        self.new_doc()

    def delete_by_id(self, did):
        """Delete a whole Challan, and make sure every 'Total' shown
        anywhere immediately reflects that it's gone."""
        result = super().delete_by_id(did)
        self.refresh_challans_list()
        self._refresh_customer_due_total()
        return result

    def delete_row(self,row_id):
        """Delete only THIS product from the challan.
        If it is the only product, the whole challan is deleted (asks for confirmation)."""
        cid,idx=self._split_row(row_id)
        if idx<0:
            return self.delete_by_id(cid)
        with conn() as c:
            rows=c.execute('SELECT item_name FROM challan_items WHERE challan_id=? ORDER BY rowid',(cid,)).fetchall()
        if idx>=len(rows):
            return
        if len(rows)==1:
            return self.delete_by_id(cid)
        name=rows[idx]['item_name'] or 'this item'
        if not messagebox.askyesno('Delete item',f'Delete "{name}" from this challan?',parent=self):
            return
        self.load_doc_by_id(cid)
        if idx<len(self.items):
            self.items.pop(idx)
        self.redraw()
        self.save_doc(silent=True)
        self.new_doc()
        self.refresh_challans_list()
        self._refresh_customer_due_total()

    # ================= BULK CHANGE DATE (Select column) =================
    # Click "Select" (right of Delete) on any PRODUCT row to tick ONLY that
    # product (yellow). Click it again to un-select it. Tick as many
    # products as needed, type ONE New Date in the toolbar, click
    # "Apply Date to Selected": only the ticked products get the new date.
    # A challan's own (header) date changes only when ALL of its products
    # are ticked. Items, amounts, payment mode, settled flag are NOT touched.
    # self._sel_cids holds the ticked ROW ids ('challan_id:product_index').
    def _update_sel_count(self):
        if hasattr(self, 'sel_count_var'):
            self.sel_count_var.set(f"{len(self._sel_cids)} product(s) selected")

    def _set_row_tick(self, iid, checked):
        try:
            self.clist.set(iid, 'sel', '☑' if checked else '☐')
            self.clist.item(iid, tags=('picked',) if checked else ())
        except Exception:
            pass

    def _toggle_challan_select(self, row_id):
        row_id = str(row_id)
        if row_id in self._sel_cids:
            self._sel_cids.discard(row_id)
            self._set_row_tick(row_id, False)
        else:
            self._sel_cids.add(row_id)
            self._set_row_tick(row_id, True)
        self._update_sel_count()

    def _listed_row_ids(self):
        return [str(i) for i in self.clist.get_children() if not str(i).startswith('draft')]

    def _select_all_challans(self, select):
        for iid in self._listed_row_ids():
            if select:
                self._sel_cids.add(iid)
            else:
                self._sel_cids.discard(iid)
            self._set_row_tick(iid, select)
        self._update_sel_count()

    def _select_today_challans(self):
        """Tick every product row whose Date is today (system date)."""
        today = datetime.now().strftime('%d-%m-%Y')
        for iid in self._listed_row_ids():
            try:
                if str(self.clist.set(iid, 'date')).strip() == today:
                    self._sel_cids.add(iid)
                    self._set_row_tick(iid, True)
            except Exception:
                pass
        self._update_sel_count()

    def _apply_bulk_date(self):
        picked = list(self._sel_cids)
        if not picked:
            messagebox.showwarning('Change Date',
                                   'Please select at least one product first (click "Select" at the end of its row).',
                                   parent=self)
            return
        raw = self.bulk_date_var.get().strip()
        try:
            new_date = datetime.strptime(raw, '%d-%m-%Y').strftime('%d-%m-%Y')
        except ValueError:
            messagebox.showerror('Change Date',
                                 'The date is invalid. Please use the format DD-MM-YYYY (for example 13-10-2026).',
                                 parent=self)
            return

        # group the ticked rows by challan
        by_cid = {}
        for iid in picked:
            cid, idx = self._split_row(iid)
            by_cid.setdefault(cid, set()).add(idx)

        try:
            with conn() as c:
                nums = {}
                for cid in by_cid:
                    r = c.execute('SELECT number FROM challans WHERE id=?', (cid,)).fetchone()
                    nums[cid] = str(r['number']) if r else str(cid)
            shown = ', '.join(sorted(set(nums.values()), key=lambda x: (len(x), x))[:30])
        except Exception:
            shown = ''
        if not messagebox.askyesno(
                'Confirm',
                f'Change the date of {len(picked)} selected product(s) to {new_date}?\n\n'
                f'Challan No.: {shown}\n\n'
                '(Products that are NOT selected will keep their current date.)',
                parent=self):
            return

        try:
            with conn() as c:
                for cid, idxs in by_cid.items():
                    rowids = [r['rid'] for r in c.execute(
                        'SELECT rowid AS rid FROM challan_items WHERE challan_id=? ORDER BY rowid', (cid,))]
                    real = {i for i in idxs if 0 <= i < len(rowids)}
                    for i in real:
                        c.execute('UPDATE challan_items SET date=? WHERE rowid=?', (new_date, rowids[i]))
                    # challan header date moves only if every product of it
                    # was ticked (or the challan has no products at all)
                    if (not rowids and -1 in idxs) or (rowids and len(real) == len(rowids)):
                        c.execute('UPDATE challans SET date=? WHERE id=?', (new_date, cid))
        except Exception as e:
            messagebox.showerror('Change Date', f'Could not change the date:\n{e}', parent=self)
            return

        # If a challan open on the main screen was changed, reset the screen
        # so it does not keep the old date in memory.
        try:
            if self.editing_id and int(self.editing_id) in by_cid:
                self.new_doc()
        except Exception:
            pass
        self._sel_cids = set()
        self.refresh_challans_list()
        self._refresh_customer_due_total()
        messagebox.showinfo('Change Date',
                            f'The date of {len(picked)} product(s) was changed to {new_date}.',
                            parent=self)

    # ================= CUSTOMER STATEMENT =================
    # A small popup: pick a Customer, see EVERY one of their saved
    # Challans - ONE ROW PER PRODUCT (so a challan with kaju, kaju, kaju
    # shows 3 separate rows, each with its own qty / unit / amount).
    # Payment Mode and 'settled' are stored per CHALLAN, so ticking any
    # product row ticks ALL rows of that same challan together. The ONLY
    # thing that locks rows is the challan having already been applied
    # from this window (its 'settled' flag). Editing/re-saving the
    # challan elsewhere unlocks it again.
    def open_customer_statement(self):
        win = tk.Toplevel(self)
        win.title('Customer Statement')
        win.geometry('1050x580')
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
            for c_ in getattr(self, 'customer_map', {}).values():
                nm = (c_.get('name') or '').strip()
                if nm:
                    names.add(nm)
            return sorted(names, key=lambda x: x.lower())

        all_names = _all_customer_names()
        cust_cb = ttk.Combobox(top, textvariable=cust_var, values=all_names, width=28, state='normal')
        cust_cb.pack(side='left', padx=(6, 16))

        # ---- Payment Mode to apply to the SELECTED challans ----
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

        # Total of ALL this customer's rows (any Payment Mode). Drops live
        # as rows get ticked.
        cust_total_var = tk.StringVar(value='Total: ₹0.00')
        ttk.Label(top, textvariable=cust_total_var, font=('Segoe UI', 9, 'bold'),
                  foreground='#B00020').pack(side='left')

        btn_row = ttk.Frame(win)
        btn_row.pack(fill='x', padx=10)

        cols = ('sel', 'number', 'date', 'payment_mode', 'item', 'qty', 'unit', 'total')
        heads = {'sel': '✓', 'number': 'Challan No.', 'date': 'Date',
                 'payment_mode': 'Payment Mode', 'item': 'Item',
                 'qty': 'Quantity', 'unit': 'Unit', 'total': 'Total (₹)'}
        widths = {'sel': 40, 'number': 100, 'date': 90, 'payment_mode': 110,
                  'item': 300, 'qty': 80, 'unit': 80, 'total': 110}
        tree = ttk.Treeview(win, columns=cols, show='headings', height=17, selectmode='none')
        for k in cols:
            tree.heading(k, text=heads[k])
            tree.column(k, width=widths[k],
                        anchor='center' if k in ('sel', 'date', 'payment_mode', 'qty', 'unit', 'total') else 'w')
        tree.tag_configure('picked', background='#FFF59D')   # yellow highlight for ticked rows
        tree.tag_configure('settled', foreground='#888888')  # greyed out - already applied, locked
        yscroll = ttk.Scrollbar(win, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side='right', fill='y', pady=(6, 4))
        tree.pack(fill='both', expand=True, padx=(10, 0), pady=(6, 4))

        bottom = ttk.Frame(win)
        bottom.pack(fill='x', padx=10, pady=(0, 10), side='bottom')
        selected_count_var = tk.StringVar(value='0 challan(s) selected')
        ttk.Label(bottom, textvariable=selected_count_var).pack(side='left')
        ttk.Label(bottom, text='(One row per product. Ticking a row ticks the whole challan. '
                               'A challan locks ONLY once its Payment Mode is applied from '
                               'here - edit it again to unlock.)',
                  foreground='#666666').pack(side='right')

        # state['rows']    -> row iid ('cid:idx') -> amount (₹) of that product row
        # state['cid_of']  -> row iid -> challan id (str)
        # state['groups']  -> challan id (str) -> [row iids of that challan]
        # state['settled'] -> challan id (str) -> True if already applied/locked
        # state['checked'] -> set of ticked challan ids (un-locked ones only)
        # state['all_total'] -> sum of every row of this customer, any mode
        state = {'rows': {}, 'cid_of': {}, 'groups': {}, 'settled': {},
                 'checked': set(), 'all_total': 0.0}

        def update_selected_total():
            tot = 0.0
            for cid in state['checked']:
                for iid in state['groups'].get(cid, []):
                    tot += state['rows'].get(iid, 0.0)
            payment_amount_var.set(f'{tot:,.2f}')
            selected_count_var.set(f"{len(state['checked'])} challan(s) selected")
            remaining = state.get('all_total', 0.0) - tot
            cust_total_var.set(f'Total: ₹{remaining:,.2f}')

        def set_challan_checked(cid, checked):
            # A challan already applied/settled from this window stays locked.
            if state['settled'].get(cid):
                return
            if checked:
                state['checked'].add(cid)
            else:
                state['checked'].discard(cid)
            for iid in state['groups'].get(cid, []):
                tree.set(iid, 'sel', '☑' if checked else '☐')
                tree.item(iid, tags=('picked',) if checked else ())

        def toggle_row(iid):
            cid = state['cid_of'].get(iid)
            if cid is None:
                return
            set_challan_checked(cid, cid not in state['checked'])
            update_selected_total()

        def select_all(select):
            for cid in list(state['groups'].keys()):
                set_challan_checked(cid, select)
            update_selected_total()

        def load_for_customer(*_, silent=False):
            for iid in tree.get_children():
                tree.delete(iid)
            state['rows'] = {}
            state['cid_of'] = {}
            state['groups'] = {}
            state['settled'] = {}
            state['checked'] = set()
            state['all_total'] = 0.0
            name = cust_var.get().strip()
            if not name:
                cust_total_var.set('Total: ₹0.00')
                update_selected_total()
                return

            # ONE ROW PER PRODUCT of every challan of this customer.
            # Nothing is de-duplicated: 3 x kaju = 3 rows.
            # Typed name: exact match first; if none, any customer whose
            # name CONTAINS the typed text (e.g. "Yash" finds "Yash Traders").
            sql = """
                SELECT d.id AS cid, d.number, d.date AS challan_date, d.payment_mode,
                       d.total AS challan_total,
                       COALESCE(d.settled,0) AS settled,
                       ci.item_name, ci.qty, ci.unit, ci.amount,
                       ci.rowid AS item_rowid,
                       COALESCE(ci.date, d.date) AS item_date
                FROM challans d
                LEFT JOIN customers cu ON cu.id = d.customer_id
                LEFT JOIN challan_items ci ON ci.challan_id = d.id
                WHERE {where}
                ORDER BY d.id DESC, ci.rowid ASC
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
            seq = {}
            for r in rows:
                cid = str(r['cid'])
                has_item = r['item_rowid'] is not None
                if has_item:
                    idx = seq.get(cid, 0)
                    seq[cid] = idx + 1
                    amt = float(r['amount'] or 0)
                    row_date = r['item_date'] or ''
                    item_name = r['item_name'] or ''
                    qty_txt = fnum(r['qty'])
                    unit_txt = r['unit'] or ''
                else:                       # challan with no items - still show it
                    idx = -1
                    amt = float(r['challan_total'] or 0)
                    row_date = r['challan_date'] or ''
                    item_name = ''
                    qty_txt = ''
                    unit_txt = ''
                iid = f'{cid}:{idx}'
                mode = (r['payment_mode'] or '').strip()
                is_settled = bool(int(r['settled'] or 0))
                all_total += amt
                state['rows'][iid] = amt
                state['cid_of'][iid] = cid
                state['groups'].setdefault(cid, []).append(iid)
                state['settled'][cid] = is_settled
                tree.insert('', 'end', iid=iid, values=(
                    '—' if is_settled else '☐', r['number'] or '', row_date,
                    mode, item_name, qty_txt, unit_txt, f'{amt:,.2f}'
                ))
                if is_settled:
                    tree.item(iid, tags=('settled',))

            state['all_total'] = all_total
            update_selected_total()

            if not rows and not silent:
                messagebox.showinfo(
                    'Customer Statement',
                    f'"{name}" has no Challans yet.',
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
                    'Please select at least one Challan row first (click on it).',
                    parent=win
                )
                return
            with conn() as c:
                for cid in checked:
                    # Apply the chosen Payment Mode AND lock the challan
                    # (settled=1) until it is edited/re-saved elsewhere.
                    c.execute('UPDATE challans SET payment_mode=?,settled=1 WHERE id=?', (mode, int(cid)))
            # Reflect everywhere: main Saved Challans table, the Customer
            # Pending Total on the main Challan form, and this window.
            self.refresh_challans_list()
            self._refresh_customer_due_total()
            messagebox.showinfo(
                'Payment Updated',
                f'{len(checked)} Challan(s) updated to Payment Mode "{mode}" successfully.',
                parent=win
            )
            load_for_customer()

        tree.bind('<Button-1>', on_tree_click)
        typing_job = {'id': None}

        def on_cust_typed(event=None):
            # ignore keys that don't change the text
            if event is not None and event.keysym in ('Return', 'Tab', 'Up', 'Down', 'Left', 'Right',
                                                       'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Escape'):
                return
            typed = cust_var.get().strip().lower()
            vals = [n for n in all_names if typed in n.lower()] if typed else list(all_names)
            cust_cb['values'] = vals
            # debounce: load challans ~0.4s after the person stops typing
            if typing_job['id'] is not None:
                try:
                    win.after_cancel(typing_job['id'])
                except Exception:
                    pass
            typing_job['id'] = win.after(400, lambda: load_for_customer(silent=True))

        cust_cb.bind('<KeyRelease>', on_cust_typed)
        cust_cb.bind('<<ComboboxSelected>>', lambda e: load_for_customer())
        cust_cb.bind('<Return>', lambda e: load_for_customer())
        cust_cb.bind('<FocusOut>', lambda e: load_for_customer(silent=True))

        # If a customer is already selected on the main Challan screen,
        # open the statement pre-filled for that same customer.
        current = self.customer_map.get(self.customer.get()) if hasattr(self, 'customer_map') else None
        if current and (current.get('name') or '').strip():
            cust_var.set(current.get('name').strip())
            load_for_customer()

        cust_cb.focus_set()