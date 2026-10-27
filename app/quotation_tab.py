# from datetime import datetime
# import tkinter as tk
# from tkinter import ttk, messagebox
# from database import conn
# from services.pdf_service import make_pdf
# from app.document_editor import DocEditor

# class DocumentTab(DocEditor):
#     # Quotation-only extras:
#     #  - Shipping amount (own line on the Quotation PDF: Sub Total/Tax/Shipping/Total)
#     #  - Date in DD-MM-YYYY format, Day + Time auto-filled & read-only (same
#     #    convention as the Customer / Product screens)
#     #  - Customer Details (Address/Contact/Email/State/GSTIN/Contact Person)
#     #    editable right here - also updates the Customer master record
#     #  - ONE single "Saved Quotations" table (like Customer/Product) with
#     #    Download / Edit / Delete built into the row itself - no separate
#     #    "Edit Existing" dropdown needed for Quotation.
#     QLIST_COLS=[('number','No'),('date','Date'),('day','Day'),('time','Time'),
#                 ('item','Item'),('hsn','HSN'),('qty','Qty'),('unit','Unit'),('price','Price'),
#                 ('amount','Amount'),('weight','Weight kg'),
#                 ('customer','Customer'),('address','Address'),('contact_no','Contact No'),
#                 ('email','Email'),('state','State / Place of Supply'),('gstin','GSTIN'),
#                 ('contact_person','Contact Person'),('subtotal','Sub Total'),
#                 ('tax','Tax'),('shipping','Shipping'),('total','Total')]
#     QLIST_ACTIONS=[('dl','Download'),('edit','Edit'),('delete','Delete')]

#     def build(self):
#         super().build()
#         for w in getattr(self,'doc_top_extra_widgets',[]):w.grid_remove()  # single table replaces this
#         if hasattr(self,'bottom'):self.bottom.pack_forget()
#         extra=ttk.LabelFrame(self.body,text='Shipping');extra.pack(fill='x',padx=8,pady=4,before=self.tree)
#         self.shipping=tk.StringVar(value='0')
#         ttk.Label(extra,text='Shipping (Rs.)').grid(row=0,column=0,padx=6,pady=(6,0),sticky='w')
#         ttk.Entry(extra,textvariable=self.shipping,width=14).grid(row=1,column=0,padx=6,pady=(0,6))
#         # ---- Day / Time (auto, read-only - same as Customer/Product screens) ----
#         dtf=ttk.LabelFrame(self.body,text='Day / Time (auto - shown on Quotation PDF)');dtf.pack(fill='x',padx=8,pady=4,before=self.tree)
#         self.day_var=tk.StringVar()
#         ttk.Label(dtf,text='Day (auto from Date)').grid(row=0,column=0,padx=6,pady=(6,0),sticky='w')
#         ttk.Entry(dtf,textvariable=self.day_var,width=14,state='readonly').grid(row=1,column=0,padx=6,pady=(0,6))
#         self.time=tk.StringVar()
#         ttk.Label(dtf,text='Time (auto)').grid(row=0,column=1,padx=6,pady=(6,0),sticky='w')
#         ttk.Entry(dtf,textvariable=self.time,width=14,state='readonly').grid(row=1,column=1,padx=6,pady=(0,6))
#         ttk.Label(dtf,text='Date format: DD-MM-YYYY  (e.g. 31-08-2026)').grid(row=0,column=2,rowspan=2,padx=16,sticky='w')
#         self.dt.trace_add('write',self._update_day)
#         # ---- Customer Details - editable HERE, also updates Customer master ----
#         cf=ttk.LabelFrame(self.body,text='Customer Details (editable here - also updates Customer master & shown on PDF)')
#         cf.pack(fill='x',padx=8,pady=4,before=self.tree)
#         self.c_address=tk.StringVar();self.c_contact=tk.StringVar();self.c_email=tk.StringVar()
#         self.c_state=tk.StringVar();self.c_gstin=tk.StringVar();self.c_person=tk.StringVar()
#         self.place=tk.StringVar()
#         cfields=[('Address',self.c_address,26),('Contact No',self.c_contact,13),('Email',self.c_email,20),
#                  ('State',self.c_state,13),('GSTIN',self.c_gstin,17),('Contact Person',self.c_person,17),
#                  ('Place of Supply',self.place,17)]
#         for i,(lab,var,w) in enumerate(cfields):
#             r=(i//4)*2;c=i%4
#             ttk.Label(cf,text=lab).grid(row=r,column=c,padx=5,pady=(6,0),sticky='w')
#             ttk.Entry(cf,textvariable=var,width=w).grid(row=r+1,column=c,padx=5,pady=(0,6))
#         if hasattr(self,'sendbar'):
#             self.sendbar.pack_forget()
#             self.sendbar.pack(fill='x',padx=8,pady=4,before=self.tree)
#         self.tree.pack_forget()
#         # ---- Saved Quotations: ONE table, all fields, Download/Edit/Delete in the row ----
#         listf=ttk.LabelFrame(self.body,text='Saved Quotations  (click Download / Edit / Delete in the row)')
#         listf.pack(fill='both',expand=True,padx=8,pady=(4,6))
#         # Keep the item table (Add Item results) visible between the Item entry
#         # row and the Saved Quotations list - this was being hidden (pack_forget)
#         # and never shown again, which made "Add Item" look like it did nothing.
#         self.tree.pack(fill='x',padx=8,pady=(4,6),before=listf)
#         # Keep the bottom bar (Save/Update, New, Import/Export CSV, Delete Doc,
#         # Save PDF As, Remove Selected, Total) visible too - it was hidden with
#         # pack_forget() above and never re-packed, so Save/Update was unusable.
#         if hasattr(self,'bottom'):
#             self.bottom.pack(fill='x',padx=8,pady=6,before=listf)
#             # "Delete Doc" is redundant here - the Saved Quotations table below
#             # already has a per-row "✕ Delete" action - so hide just this one
#             # button from the bottom bar (Challan/Invoice tabs are unaffected).
#             for w in self.bottom.winfo_children():
#                 try:
#                     if w.cget('text')=='Delete Doc':w.pack_forget()
#                 except Exception:pass
#         self.qcols=[k for k,_ in self.QLIST_COLS]+[k for k,_ in self.QLIST_ACTIONS]
#         self.qlist=ttk.Treeview(listf,columns=self.qcols,show='headings',height=7)
#         # A quotation row can have MULTIPLE items - they are joined together
#         # with ", " into a single cell (item/hsn/qty/unit/price/amount). The
#         # default 105px width was too narrow, so with 2-3+ items the text got
#         # cut off and it looked like only one item had been added. Widen those
#         # columns so several items are actually readable (the horizontal
#         # scrollbar below still lets you see the rest of the row).
#         QLIST_WIDTHS={'item':320,'hsn':160,'qty':130,'unit':110,'price':150,'amount':150,
#                       'weight':100,'address':170,'email':170,'customer':150}
#         for k,l in self.QLIST_COLS:self.qlist.heading(k,text=l);self.qlist.column(k,width=QLIST_WIDTHS.get(k,105))
#         for k,l in self.QLIST_ACTIONS:self.qlist.heading(k,text=l);self.qlist.column(k,width=85,anchor='center',stretch=False)
#         xscroll=ttk.Scrollbar(listf,orient='horizontal',command=self.qlist.xview)
#         self.qlist.configure(xscrollcommand=xscroll.set)
#         self.qlist.pack(fill='x',padx=6,pady=(6,0));xscroll.pack(fill='x',padx=6,pady=(0,6))
#         self.qlist.bind('<Button-1>',self.on_qlist_click)
#     def _update_day(self,*args):
#         ds=self.dt.get().strip();day=''
#         for fmt in ('%d-%m-%Y','%Y-%m-%d','%d/%m/%Y'):
#             try:day=datetime.strptime(ds,fmt).strftime('%A');break
#             except Exception:continue
#         self.day_var.set(day)
#     def new_doc(self):
#         super().new_doc()
#         self.dt.set(datetime.now().strftime('%d-%m-%Y'))
#         self.time.set(datetime.now().strftime('%I:%M %p'))
#         self._update_day()
#         for v in (getattr(self,'c_address',None),getattr(self,'c_contact',None),getattr(self,'c_email',None),
#                   getattr(self,'c_state',None),getattr(self,'c_gstin',None),getattr(self,'c_person',None),
#                   getattr(self,'place',None)):
#             if v is not None:v.set('')
#     def on_customer_selected(self,e=None):
#         super().on_customer_selected(e)
#         cust=self.customer_map.get(self.customer.get())
#         if cust:
#             if hasattr(self,'c_address'):self.c_address.set(cust.get('address','') or '')
#             if hasattr(self,'c_contact'):self.c_contact.set(cust.get('contact_no','') or '')
#             if hasattr(self,'c_email'):self.c_email.set(cust.get('email','') or '')
#             if hasattr(self,'c_state'):self.c_state.set(cust.get('state','') or '')
#             if hasattr(self,'c_gstin'):self.c_gstin.set(cust.get('gstin','') or '')
#             if hasattr(self,'c_person'):self.c_person.set(cust.get('contact_person','') or '')
#             if hasattr(self,'place') and not self.place.get():self.place.set(cust.get('state','') or '')
#     def current_customer(self):
#         cust=self.customer_map.get(self.customer.get())
#         if not cust:return None
#         cust=dict(cust)
#         if hasattr(self,'c_address'):
#             cust['address']=self.c_address.get().strip() or cust.get('address','')
#             cust['contact_no']=self.c_contact.get().strip() or cust.get('contact_no','')
#             cust['email']=self.c_email.get().strip() or cust.get('email','')
#             cust['state']=self.c_state.get().strip() or cust.get('state','')
#             cust['gstin']=self.c_gstin.get().strip() or cust.get('gstin','')
#             cust['contact_person']=self.c_person.get().strip() or cust.get('contact_person','')
#         return cust
#     def after_load_doc(self,doc):
#         self.shipping.set(str(doc.get('shipping') or 0))
#         if hasattr(self,'place'):self.place.set(doc.get('place_of_supply') or '')
#         self.time.set(doc.get('time') or datetime.now().strftime('%I:%M %p'))
#         self._update_day()
#     def after_import_csv(self,row):
#         self.shipping.set(row.get('shipping') or self.shipping.get())
#         self.place.set(row.get('place_of_supply') or row.get('state') or self.place.get())
#     def totals(self):
#         sub,cgst,sgst,total=super().totals()
#         ship=self.csv_float(self.shipping.get(),0) if hasattr(self,'shipping') else 0
#         return sub,cgst,sgst,total+ship
#     def pdf_header(self,sub,cgst,sgst,total):
#         h=super().pdf_header(sub,cgst,sgst,total)
#         h['shipping']=self.csv_float(self.shipping.get(),0) if hasattr(self,'shipping') else 0
#         h['day']=self.day_var.get() if hasattr(self,'day_var') else ''
#         h['time']=self.time.get() if hasattr(self,'time') else ''
#         h['place_of_supply']=self.place.get() if hasattr(self,'place') else ''
#         return h
#     def save_doc(self):
#         cust=self.current_customer()
#         if not cust or not self.items:return messagebox.showerror('Required','Customer and items required')
#         with conn() as c:
#             c.execute('UPDATE customers SET address=?,contact_no=?,email=?,state=?,gstin=?,contact_person=? WHERE id=?',
#                       (cust['address'],cust['contact_no'],cust['email'],cust['state'],cust['gstin'],cust['contact_person'],cust['id']))
#         sub,cgst,sgst,total=self.totals();ship=self.csv_float(self.shipping.get(),0)
#         tm=self.time.get() if hasattr(self,'time') else ''
#         with conn() as c:
#             if self.editing_id:
#                 did=self.editing_id
#                 c.execute('UPDATE quotations SET number=?,date=?,place_of_supply=?,customer_id=?,gst_rate=?,subtotal=?,cgst=?,sgst=?,shipping=?,total=?,notes=?,time=? WHERE id=?',
#                           (self.number.get(),self.dt.get(),self.place.get(),cust['id'],float(self.gst.get()),sub,cgst,sgst,ship,total,self.notes.get(),tm,did))
#                 c.execute('DELETE FROM quotation_items WHERE quotation_id=?',(did,))
#             else:
#                 cur=c.execute('INSERT INTO quotations(number,date,place_of_supply,customer_id,gst_rate,subtotal,cgst,sgst,shipping,total,notes,time) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
#                                (self.number.get(),self.dt.get(),self.place.get(),cust['id'],float(self.gst.get()),sub,cgst,sgst,ship,total,self.notes.get(),tm))
#                 did=cur.lastrowid;self.editing_id=did
#             for it in self.items:
#                 c.execute('INSERT INTO quotation_items(quotation_id,product_id,item_name,hsn_sac,qty,unit,price,amount,weight_kg) VALUES(?,?,?,?,?,?,?,?,?)',
#                           (did,it['product_id'],it['item_name'],it['hsn_sac'],it['qty'],it['unit'],it['price'],it['amount'],it['weight_kg']))
#         self.refresh_refs()
#         self.last_pdf=make_pdf('quotation',self.pdf_header(sub,cgst,sgst,total),cust,self.items)
#         self.load_docs();messagebox.showinfo('Saved',f'Saved and PDF created:\n{self.last_pdf}')
#     # ---------- Saved Quotations table (single table, Download/Edit/Delete in-row) ----------
#     def load_docs(self):
#         super().load_docs()
#         self.refresh_quotations_list()
#     def refresh_quotations_list(self):
#         if not hasattr(self,'qlist'):return
#         for x in self.qlist.get_children():self.qlist.delete(x)
#         with conn() as c:
#             rows=c.execute('SELECT q.id,q.number,q.date,q.time,q.place_of_supply,q.subtotal,q.cgst,q.sgst,q.shipping,q.total,'
#                             'c.name,c.address,c.contact_no,c.email,c.state,c.gstin,c.contact_person,'
#                             '(SELECT GROUP_CONCAT(qi.item_name,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS items,'
#                             '(SELECT GROUP_CONCAT(qi.hsn_sac,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS hsns,'
#                             '(SELECT GROUP_CONCAT(qi.qty,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS qtys,'
#                             '(SELECT GROUP_CONCAT(qi.unit,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS units,'
#                             '(SELECT GROUP_CONCAT(qi.price,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS prices,'
#                             '(SELECT GROUP_CONCAT(qi.amount,", ") FROM quotation_items qi WHERE qi.quotation_id=q.id) AS amounts,'
#                             '(SELECT COALESCE(SUM(qi.weight_kg),0) FROM quotation_items qi WHERE qi.quotation_id=q.id) AS weight '
#                             'FROM quotations q JOIN customers c ON c.id=q.customer_id ORDER BY q.id DESC').fetchall()
#         for r in rows:
#             day=''
#             for fmt in ('%d-%m-%Y','%Y-%m-%d','%d/%m/%Y'):
#                 try:day=datetime.strptime((r['date'] or '').strip(),fmt).strftime('%A');break
#                 except Exception:continue
#             tax=float(r['cgst'] or 0)+float(r['sgst'] or 0)
#             vals=(r['number'],r['date'],day,r['time'] or '',
#                   r['items'] or '',r['hsns'] or '',r['qtys'] or '',r['units'] or '',r['prices'] or '',r['amounts'] or '',
#                   f"{float(r['weight'] or 0):,.2f}",
#                   r['name'],r['address'] or '',r['contact_no'] or '',
#                   r['email'] or '',r['place_of_supply'] or r['state'] or '',r['gstin'] or '',r['contact_person'] or '',
#                   f"{float(r['subtotal'] or 0):,.2f}",f"{tax:,.2f}",f"{float(r['shipping'] or 0):,.2f}",
#                   f"{float(r['total'] or 0):,.2f}",'⬇ Download','✎ Edit','✕ Delete')
#             self.qlist.insert('','end',iid=str(r['id']),values=vals)
#     def on_qlist_click(self,event):
#         region=self.qlist.identify('region',event.x,event.y)
#         if region!='cell':return
#         col=self.qlist.identify_column(event.x)
#         row_id=self.qlist.identify_row(event.y)
#         if not row_id:return
#         idx=int(col.replace('#',''))-1
#         if idx<0 or idx>=len(self.qcols):return
#         name=self.qcols[idx]
#         if name=='dl':self.download_row(row_id)
#         elif name=='edit':self.edit_row(row_id)
#         elif name=='delete':self.delete_row(row_id)
#     def edit_row(self,row_id):
#         self.load_doc_by_id(int(row_id))
#     def download_row(self,row_id):
#         self.load_doc_by_id(int(row_id));self.save_pdf_as()
#     def delete_row(self,row_id):
#         self.delete_by_id(int(row_id))