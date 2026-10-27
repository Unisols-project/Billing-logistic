import csv, os, shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date
from database import conn, next_number
from config import DEFAULT_GST_RATE
from services.pdf_service import make_pdf
from services.send_service import open_whatsapp, send_email_or_compose, print_pdf_in_browser

class DocEditor(ttk.Frame):
    table='quotations'; item_table='quotation_items'; prefix='QTN-'; doc_type='quotation'
    id_field='quotation_id'
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.items=[];self.customer_map={};self.product_map={};self.doc_map={};self.editing_id=None;self.last_pdf='';self.build();self.refresh_refs();self.load_docs();self.new_doc()
    def build(self):
        # ---- Scrollable wrapper: with Quotation's extra sections (Shipping,
        # Day/Time, Customer Details, Saved Quotations table) the content can be
        # taller than the window, which used to push the Print/WhatsApp/Email
        # buttons below the visible area. Wrapping everything in a scrollable
        # canvas guarantees those buttons are always reachable. ----
        outer = tk.Frame(self)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')
        container = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=container, anchor='nw')

        def _on_container_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        container.bind('<Configure>', _on_container_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(win, width=event.width)
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
        self.body = container  # subclasses (Quotation/Challan) add their extra sections here

        top=ttk.LabelFrame(container,text='Document');top.pack(fill='x',padx=8,pady=6)
        self.number=tk.StringVar();self.dt=tk.StringVar(value=str(date.today()));self.customer=tk.StringVar();self.gst=tk.StringVar(value=str(DEFAULT_GST_RATE));self.notes=tk.StringVar();self.existing_doc=tk.StringVar()
        labels=[('No',self.number),('Date',self.dt),('Customer',self.customer),('GST %',self.gst)]
        for i,(lab,var) in enumerate(labels):ttk.Label(top,text=lab).grid(row=0,column=i,padx=5,sticky='w');
        ttk.Entry(top,textvariable=self.number,width=18).grid(row=1,column=0,padx=5,pady=4);ttk.Entry(top,textvariable=self.dt,width=18).grid(row=1,column=1,padx=5,pady=4)
        self.customer_cb=ttk.Combobox(top,textvariable=self.customer,width=32,state='readonly');self.customer_cb.grid(row=1,column=2,padx=5,pady=4);ttk.Entry(top,textvariable=self.gst,width=12).grid(row=1,column=3,padx=5,pady=4)
        lbl_edit=ttk.Label(top,text='Edit Existing');lbl_edit.grid(row=0,column=4,padx=5,sticky='w')
        self.doc_cb=ttk.Combobox(top,textvariable=self.existing_doc,width=34,state='readonly');self.doc_cb.grid(row=1,column=4,padx=5,pady=4)
        load_btn=ttk.Button(top,text='Load',command=self.load_selected_doc);load_btn.grid(row=1,column=5,padx=5)
        self.doc_top_extra_widgets=[lbl_edit,self.doc_cb,load_btn]
        # ---- Customer Details (read-only, auto-filled on customer select) ----
        # Shows the FULL customer master record - including District, Pin
        # Code and Phone No, which previously only existed on the Customer
        # Master screen and were invisible here.
        custdet=ttk.LabelFrame(container,text='Customer Details');custdet.pack(fill='x',padx=8,pady=(0,6))
        self.cd_address=tk.StringVar();self.cd_contact_no=tk.StringVar();self.cd_email=tk.StringVar();self.cd_state=tk.StringVar();self.cd_district=tk.StringVar();self.cd_pincode=tk.StringVar();self.cd_gstin=tk.StringVar();self.cd_contact_person=tk.StringVar();self.cd_phone_no=tk.StringVar()
        cd_fields=[('Address',self.cd_address,26),('Contact No',self.cd_contact_no,14),('Email',self.cd_email,20),('State',self.cd_state,14),
                   ('District',self.cd_district,14),('Pin Code',self.cd_pincode,10),('GSTIN',self.cd_gstin,18),('Contact Person',self.cd_contact_person,16),('Phone No',self.cd_phone_no,14)]
        for i,(lab,var,w) in enumerate(cd_fields):
            r=(i//5)*2;c=i%5
            ttk.Label(custdet,text=lab).grid(row=r,column=c,padx=4,pady=(4,0),sticky='w')
            ttk.Entry(custdet,textvariable=var,width=w,state='readonly').grid(row=r+1,column=c,padx=4,pady=(0,4),sticky='w')
        self.sendbar=ttk.LabelFrame(container,text='Print / WhatsApp / Email')
        self.sendbar.pack(fill='x',padx=8,pady=4)
        ttk.Button(self.sendbar,text='Print',command=self.print_current).pack(side='left',padx=6,pady=6)
        ttk.Button(self.sendbar,text='WhatsApp',command=self.whatsapp_current).pack(side='left',padx=6,pady=6)
        ttk.Button(self.sendbar,text='Email',command=self.email_current).pack(side='left',padx=6,pady=6)
        itemf=ttk.LabelFrame(container,text='Item');itemf.pack(fill='x',padx=8,pady=6)
        self.product=tk.StringVar();self.qty=tk.StringVar(value='1');self.price=tk.StringVar();
        self.product_cb=ttk.Combobox(itemf,textvariable=self.product,width=40,state='readonly');self.product_cb.grid(row=0,column=0,padx=5,pady=7);self.product_cb.bind('<<ComboboxSelected>>',self.pick_product)
        ttk.Entry(itemf,textvariable=self.qty,width=12).grid(row=0,column=1,padx=5);ttk.Entry(itemf,textvariable=self.price,width=15).grid(row=0,column=2,padx=5);ttk.Button(itemf,text='Add',command=self.add_item).grid(row=0,column=3,padx=5)
        self.tree=ttk.Treeview(container,columns=('item','hsn','qty','unit','price','amount'),show='headings',height=14)
        for k,l,w in [('item','Item Name',280),('hsn','HSN/ SAC',110),('qty','Quantity',90),('unit','Unit',90),('price','Price/ Unit (₹)',125),('amount','Amount (₹)',125)]:
            self.tree.heading(k,text=l)
            self.tree.column(k,width=w,minwidth=70,anchor='center' if k!='item' else 'w',stretch=True)
        self.tree.pack(fill='both',padx=8,pady=6)
        self.bottom=ttk.Frame(container);self.bottom.pack(fill='x',padx=8,pady=6);self.total_lbl=ttk.Label(self.bottom,text='Total: 0.00',font=('Segoe UI',12,'bold'));self.total_lbl.pack(side='right',padx=10)
        ttk.Button(self.bottom,text='New',command=self.new_doc).pack(side='left',padx=4);ttk.Button(self.bottom,text='Import CSV',command=self.import_csv).pack(side='left',padx=4);ttk.Button(self.bottom,text='Export CSV',command=self.export_csv).pack(side='left',padx=4);ttk.Button(self.bottom,text='Save / Update',command=self.save_doc).pack(side='left',padx=4);ttk.Button(self.bottom,text='Delete Doc',command=self.delete_doc).pack(side='left',padx=4);ttk.Button(self.bottom,text='Save PDF As',command=self.save_pdf_as).pack(side='left',padx=4)
        # ---- Print / WhatsApp / Email: same as Route Rate Master (MasterBase) ----
        self.bottom_send_buttons=[]
        for text,cmd in [('Print',self.print_current),('WhatsApp',self.whatsapp_current),('Email',self.email_current)]:
            btn=ttk.Button(self.bottom,text=text,command=cmd)
            btn.pack(side='left',padx=4)
            self.bottom_send_buttons.append(btn)
        ttk.Button(self.bottom,text='Remove Selected',command=self.remove_item).pack(side='left',padx=4)
        self.customer_cb.bind('<<ComboboxSelected>>',self.on_customer_selected)
    def on_customer_selected(self,e=None):
        cust=self.customer_map.get(self.customer.get())
        if cust:
            if hasattr(self,'wa_number'):self.wa_number.set(cust.get('contact_no','') or '')
            if hasattr(self,'email_to'):self.email_to.set(cust.get('email','') or '')
            self._fill_customer_details(cust)
    def _fill_customer_details(self,cust):
        if not hasattr(self,'cd_address'):return
        self.cd_address.set(cust.get('address','') or '');self.cd_contact_no.set(cust.get('contact_no','') or '');self.cd_email.set(cust.get('email','') or '');self.cd_state.set(cust.get('state','') or '')
        self.cd_district.set(cust.get('district','') or '');self.cd_pincode.set(cust.get('pincode','') or '');self.cd_gstin.set(cust.get('gstin','') or '');self.cd_contact_person.set(cust.get('contact_person','') or '');self.cd_phone_no.set(cust.get('phone_no','') or '')
    def current_customer(self):
        return self.customer_map.get(self.customer.get())
    def refresh_refs(self):
        with conn() as c:
            cust=c.execute('SELECT * FROM customers ORDER BY name').fetchall();prod=c.execute('SELECT * FROM products ORDER BY item_name').fetchall()
        self.customer_map={f"{r['id']} - {r['name']}":dict(r) for r in cust};self.product_map={f"{r['id']} - {r['item_name']}":dict(r) for r in prod}
        self.customer_cb['values']=list(self.customer_map);self.product_cb['values']=list(self.product_map)
    def load_docs(self):
        with conn() as c:
            rows=c.execute(f'SELECT d.id,d.number,d.date,c.name FROM {self.table} d JOIN customers c ON c.id=d.customer_id ORDER BY d.id DESC').fetchall()
        self.doc_map={f"{r['number']} | {r['date']} | {r['name']}":r['id'] for r in rows};self.doc_cb['values']=list(self.doc_map)
    def new_doc(self):self.editing_id=None;self.last_pdf='';self.items=[];self.number.set(next_number(self.table,self.prefix));self.dt.set(str(date.today()));self.existing_doc.set('');self._clear_customer_details();self.redraw()
    def _clear_customer_details(self):
        if not hasattr(self,'cd_address'):return
        for v in (self.cd_address,self.cd_contact_no,self.cd_email,self.cd_state,self.cd_district,self.cd_pincode,self.cd_gstin,self.cd_contact_person,self.cd_phone_no):v.set('')
    def customer_key(self,cid):
        for k,v in self.customer_map.items():
            if v['id']==cid:return k
        return ''
    def load_selected_doc(self):
        did=self.doc_map.get(self.existing_doc.get())
        if not did:return messagebox.showerror('Load','Select a saved document')
        self.load_doc_by_id(did)
    def load_doc_by_id(self,did):
        with conn() as c:
            row=c.execute(f'SELECT * FROM {self.table} WHERE id=?',(did,)).fetchone()
            if not row:return messagebox.showerror('Load','Document not found (maybe deleted)')
            doc=dict(row)
            self.items=[dict(r) for r in c.execute(f'SELECT * FROM {self.item_table} WHERE {self.id_field}=?',(did,)).fetchall()]
        self.editing_id=did;self.number.set(doc.get('number',''));self.dt.set(doc.get('date',''));self.customer.set(self.customer_key(doc.get('customer_id')));self.gst.set(str(doc.get('gst_rate') or DEFAULT_GST_RATE));self.notes.set(doc.get('notes','') or doc.get('description','') or '');self.after_load_doc(doc);self.on_customer_selected();self.redraw()
    def after_load_doc(self,doc): pass
    def pick_product(self,e=None):
        p=self.product_map.get(self.product.get());
        if p:self.price.set(str(p['price']))
    def add_item(self):
        p=self.product_map.get(self.product.get())
        if not p:return messagebox.showerror('Item','Select product')
        try:q=float(self.qty.get());pr=float(self.price.get())
        except:return messagebox.showerror('Value','Qty/Price invalid')
        self.items.append({'product_id':p['id'],'item_name':p['item_name'],'hsn_sac':p['hsn_sac'],'qty':q,'unit':p['unit'],'price':pr,'amount':q*pr,'weight_kg':float(p['weight_kg'] or 0)*q});self.redraw()
    def import_csv(self):
        path=filedialog.askopenfilename(filetypes=[('CSV','*.csv'),('All files','*.*')])
        if not path:return
        rows=self.read_csv_rows(path)
        if not rows:return messagebox.showerror('CSV','CSV file is empty')
        first=rows[0];cust=self.upsert_customer_from_row(first)
        if cust:
            self.refresh_refs();self.customer.set(self.customer_key(cust['id']))
        self.dt.set(first.get('date') or first.get('bill_date') or first.get('challan_date') or self.dt.get())
        if first.get('number') or first.get('invoice_no') or first.get('challan_no'):
            self.number.set(first.get('number') or first.get('invoice_no') or first.get('challan_no'))
        imported=[]
        for row in rows:
            item=self.item_from_csv_row(row)
            if item:imported.append(item)
        if not imported:return messagebox.showerror('CSV','No item rows found. Use columns like item_name, hsn_sac, qty, unit, price, amount.')
        self.items=imported;self.after_import_csv(first);self.redraw()
        messagebox.showinfo('Imported',f'{len(imported)} items imported from CSV')
    def read_csv_rows(self,path):
        with open(path,'r',newline='',encoding='utf-8-sig') as f:
            return [{(k or '').strip().lower().replace(' ','_'): (v or '').strip() for k,v in row.items()} for row in csv.DictReader(f)]
    def upsert_customer_from_row(self,row):
        name=row.get('customer') or row.get('customer_name') or row.get('party') or row.get('party_name')
        if not name:return None
        vals={'name':name,'address':row.get('address') or row.get('customer_address') or row.get('party_address') or '','contact_no':row.get('contact_no') or row.get('phone') or row.get('whatsapp') or row.get('whatsapp_no') or '','email':row.get('email') or row.get('mail') or '','state':row.get('state') or row.get('place_of_supply') or '','gstin':row.get('gstin') or row.get('gst_no') or '','contact_person':row.get('contact_person') or ''}
        with conn() as c:
            old=c.execute('SELECT * FROM customers WHERE lower(name)=lower(?)',(name,)).fetchone()
            if old:
                c.execute("UPDATE customers SET address=COALESCE(NULLIF(?,''),address),contact_no=COALESCE(NULLIF(?,''),contact_no),email=COALESCE(NULLIF(?,''),email),state=COALESCE(NULLIF(?,''),state),gstin=COALESCE(NULLIF(?,''),gstin),contact_person=COALESCE(NULLIF(?,''),contact_person) WHERE id=?",(vals['address'],vals['contact_no'],vals['email'],vals['state'],vals['gstin'],vals['contact_person'],old['id']))
                return dict(c.execute('SELECT * FROM customers WHERE id=?',(old['id'],)).fetchone())
            cur=c.execute('INSERT INTO customers(name,address,contact_no,email,state,gstin,contact_person) VALUES(?,?,?,?,?,?,?)',(vals['name'],vals['address'],vals['contact_no'],vals['email'],vals['state'],vals['gstin'],vals['contact_person']))
            return dict(c.execute('SELECT * FROM customers WHERE id=?',(cur.lastrowid,)).fetchone())
    def item_from_csv_row(self,row):
        name=row.get('item_name') or row.get('item') or row.get('product') or row.get('description')
        if not name:return None
        qty=self.csv_float(row.get('qty') or row.get('quantity'),1);price=self.csv_float(row.get('price') or row.get('rate') or row.get('price_unit'),0);amount=self.csv_float(row.get('amount'),qty*price);unit=row.get('unit') or 'Nos';hsn=row.get('hsn_sac') or row.get('hsn') or row.get('sac') or '';weight=self.csv_float(row.get('weight_kg') or row.get('weight'),0)
        with conn() as c:
            p=c.execute('SELECT * FROM products WHERE lower(item_name)=lower(?)',(name,)).fetchone()
            if not p:
                cur=c.execute('INSERT INTO products(item_name,hsn_sac,unit,price,weight_kg) VALUES(?,?,?,?,?)',(name,hsn,unit,price,weight))
                pid=cur.lastrowid
            else:
                pid=p['id'];hsn=hsn or p['hsn_sac'];unit=unit or p['unit'];weight=weight or float(p['weight_kg'] or 0)
        return {'product_id':pid,'item_name':name,'hsn_sac':hsn,'qty':qty,'unit':unit,'price':price,'amount':amount,'weight_kg':weight*qty if weight else 0}
    def csv_float(self,value,default=0):
        try:return float(str(value).replace(',','')) if value not in (None,'') else default
        except:return default
    def after_import_csv(self,row): pass
    def remove_item(self):
        sel=self.tree.selection();
        if sel:self.items.pop(self.tree.index(sel[0]));self.redraw()
    def export_csv(self):
        if not self.items:return messagebox.showerror('Export','Add or load items first')
        cust=self.customer_map.get(self.customer.get(),{})
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'{self.doc_type}_{self.number.get()}.csv',filetypes=[('CSV','*.csv')])
        if not path:return
        cols=['doc_type','number','date','customer_name','customer_address','contact_no','email','state','gstin','contact_person','gst_rate','place_of_supply','from_city','to_city','freight_rate','freight_rate_type','notes','item_name','hsn_sac','qty','unit','price','amount','weight_kg']
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
            for it in self.items:
                row={'doc_type':self.doc_type,'number':self.number.get(),'date':self.dt.get(),'customer_name':cust.get('name',''),'customer_address':cust.get('address',''),'contact_no':cust.get('contact_no',''),'email':cust.get('email',''),'state':cust.get('state',''),'gstin':cust.get('gstin',''),'contact_person':cust.get('contact_person',''),'gst_rate':self.gst.get(),'notes':self.notes.get(),'item_name':it.get('item_name',''),'hsn_sac':it.get('hsn_sac',''),'qty':it.get('qty',0),'unit':it.get('unit',''),'price':it.get('price',0),'amount':it.get('amount',0),'weight_kg':it.get('weight_kg',0)}
                for attr in ('place','from_city','to_city','freight_rate','rate_type'):
                    if hasattr(self,attr):row['freight_rate_type' if attr=='rate_type' else attr]=getattr(self,attr).get()
                w.writerow(row)
        messagebox.showinfo('Exported',path)
    def delete_doc(self):
        did=self.editing_id or self.doc_map.get(self.existing_doc.get())
        if not did:return messagebox.showerror('Delete','Load or select a saved document first')
        self.delete_by_id(did)
    def delete_by_id(self,did):
        if not messagebox.askyesno('Delete',f'Delete this {self.doc_type}?'):return
        with conn() as c:
            if self.table=='challans':c.execute('DELETE FROM invoice_challans WHERE challan_id=?',(did,))
            c.execute(f'DELETE FROM {self.item_table} WHERE {self.id_field}=?',(did,))
            c.execute(f'DELETE FROM {self.table} WHERE id=?',(did,))
        if self.editing_id==did:self.new_doc()
        self.load_docs();messagebox.showinfo('Deleted','Document deleted')
    def totals(self):
        sub=sum(x['amount'] for x in self.items);g=float(self.gst.get() or 0);tax=sub*g/100;return sub,tax/2,tax/2,sub+tax
    def redraw(self):
        for x in self.tree.get_children():self.tree.delete(x)
        for it in self.items:
            qty=float(it.get('qty') or 0)
            price=float(it.get('price') or 0)
            amount=float(it.get('amount') if it.get('amount') is not None else qty*price)
            self.tree.insert('', 'end', values=(
                it.get('item_name',''),
                it.get('hsn_sac',''),
                int(qty) if qty.is_integer() else qty,
                it.get('unit',''),
                f"{price:,.2f}",
                f"{amount:,.2f}"
            ))
        try:self.total_lbl.config(text=f'Total: {self.totals()[3]:,.2f}')
        except:pass
    def save_doc(self):
        cust=self.customer_map.get(self.customer.get());
        if not cust or not self.items:return messagebox.showerror('Required','Customer and items required')
        sub,cgst,sgst,total=self.totals()
        with conn() as c:
            if self.editing_id:
                did=self.editing_id;c.execute(f'UPDATE {self.table} SET number=?,date=?,customer_id=?,gst_rate=?,subtotal=?,cgst=?,sgst=?,total=?,notes=? WHERE id=?',(self.number.get(),self.dt.get(),cust['id'],float(self.gst.get()),sub,cgst,sgst,total,self.notes.get(),did));c.execute(f'DELETE FROM {self.item_table} WHERE {self.id_field}=?',(did,))
            else:
                cur=c.execute(f'INSERT INTO {self.table}(number,date,customer_id,gst_rate,subtotal,cgst,sgst,total,notes) VALUES(?,?,?,?,?,?,?,?,?)',(self.number.get(),self.dt.get(),cust['id'],float(self.gst.get()),sub,cgst,sgst,total,self.notes.get()));did=cur.lastrowid;self.editing_id=did
            for it in self.items:c.execute(f'INSERT INTO {self.item_table}({self.id_field},product_id,item_name,hsn_sac,qty,unit,price,amount,weight_kg) VALUES(?,?,?,?,?,?,?,?,?)',(did,it['product_id'],it['item_name'],it['hsn_sac'],it['qty'],it['unit'],it['price'],it['amount'],it['weight_kg']))
        self.last_pdf=make_pdf(self.doc_type,self.pdf_header(sub,cgst,sgst,total),cust,self.items)
        self.load_docs();messagebox.showinfo('Saved',f'Saved and PDF created:\n{self.last_pdf}')
    def pdf_header(self,sub,cgst,sgst,total):
        return {'number':self.number.get(),'date':self.dt.get(),'gst_rate':float(self.gst.get()),'subtotal':sub,'cgst':cgst,'sgst':sgst,'total':total,'notes':self.notes.get()}
    def ensure_pdf(self):
        cust=self.current_customer()
        if not cust or not self.items:messagebox.showerror('Required','Customer and items required');return None
        sub,cgst,sgst,total=self.totals();self.last_pdf=make_pdf(self.doc_type,self.pdf_header(sub,cgst,sgst,total),cust,self.items);return self.last_pdf
    def save_pdf_as(self):
        src=self.ensure_pdf()
        if not src:return
        dst=filedialog.asksaveasfilename(defaultextension='.pdf',initialfile=os.path.basename(src),filetypes=[('PDF','*.pdf')])
        if dst:shutil.copyfile(src,dst);messagebox.showinfo('Downloaded',dst)
    def print_current(self):
        path=self.ensure_pdf()
        if path:print_pdf_in_browser(path)
    def contact_default(self, key):
        cust=self.current_customer() or {}
        return cust.get(key,'') or ''
    def whatsapp_current(self):
        path=self.ensure_pdf()
        if not path:return
        phone=simpledialog.askstring('WhatsApp','Enter WhatsApp number',initialvalue=self.contact_default('contact_no'))
        if phone:
            open_whatsapp(phone,f'{self.doc_type.title()} {self.number.get()} generated. Total Rs. {self.totals()[3]:.2f}. PDF saved at: {path}',path)
    def email_current(self):
        path=self.ensure_pdf()
        if not path:return
        to=simpledialog.askstring('Email','Enter email address',initialvalue=self.contact_default('email'))
        if not to:return
        try:
            msg=send_email_or_compose(to,f'{self.doc_type.title()} {self.number.get()}',f'Please find attached {self.doc_type.title()} {self.number.get()}.',path)
            messagebox.showinfo('Email',msg)
        except Exception as e:
            messagebox.showerror('Email not sent',str(e))