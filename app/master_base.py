"""
Shared base class used by all Master screens (Customer, Product, Route, etc.)
Kept in its own file so every master tab file can simply do:
    from app.master_base import MasterBase
"""
import csv, os, webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from database import conn
from services.pdf_service import make_report_pdf
from services.send_service import open_whatsapp, send_email_or_compose, print_pdf_in_browser


class MasterBase(ttk.Frame):
    table = ''
    fields = []
    # Subclasses can hide specific action buttons by listing their keys here,
    # e.g. hidden_actions = {'export_csv', 'export_pdf', 'print'}
    hidden_actions = frozenset()

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.vars = {}
        self.selected_id = None
        self.current_rows = []
        self.build()
        self.load()

    def build(self):
        form = ttk.LabelFrame(self, text='Details')
        form.pack(fill='x', padx=8, pady=8)
        for i, (key, label) in enumerate(self.fields):
            ttk.Label(form, text=label).grid(row=i // 4 * 2, column=i % 4, padx=6, pady=(6, 0), sticky='w')
            v = tk.StringVar()
            self.vars[key] = v
            ttk.Entry(form, textvariable=v, width=28).grid(row=i // 4 * 2 + 1, column=i % 4, padx=6, pady=(0, 6), sticky='ew')
        ttk.Button(form, text='Save', command=self.save).grid(
            row=((len(self.fields) - 1) // 4 + 1) * 2, column=0, padx=6, pady=6)
        ttk.Button(form, text='Clear', command=self.clear).grid(
            row=((len(self.fields) - 1) // 4 + 1) * 2, column=1, padx=6, pady=6)
        self.search_var = tk.StringVar()
        ttk.Label(form, text='Search').grid(row=((len(self.fields) - 1) // 4 + 1) * 2, column=2, padx=6, pady=6, sticky='e')
        ttk.Entry(form, textvariable=self.search_var, width=24).grid(row=((len(self.fields) - 1) // 4 + 1) * 2, column=3, padx=6, pady=6)
        ttk.Button(form, text='Search', command=self.load).grid(row=((len(self.fields) - 1) // 4 + 1) * 2, column=4, padx=6, pady=6)
        action_row = ((len(self.fields) - 1) // 4 + 2) * 2
        actions = [
            ('export_csv', 'Export CSV', self.export_csv),
            ('export_pdf', 'Save PDF As', self.export_pdf),
            ('print', 'Print', self.print_current),
            ('whatsapp', 'WhatsApp', self.whatsapp_current),
            ('email', 'Email', self.email_current),
        ]
        col = 0
        for key, text, cmd in actions:
            if key in self.hidden_actions:
                continue
            ttk.Button(form, text=text, command=cmd).grid(row=action_row, column=col, padx=6, pady=6)
            col += 1
        self.tree = ttk.Treeview(self, columns=[x[0] for x in self.fields], show='headings', height=20)
        for k, l in self.fields:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=140)
        self.tree.pack(fill='both', expand=True, padx=8, pady=8)
        self.tree.bind('<Double-1>', self.pick_row)

    def clear(self):
        for v in self.vars.values():
            v.set('')
        self.selected_id = None

    def save(self):
        keys = [k for k, _ in self.fields]
        vals = [self.vars[k].get().strip() for k in keys]
        if not vals[0]:
            return messagebox.showerror('Required', f'{self.fields[0][1]} is required')
        with conn() as c:
            if self.selected_id:
                sets = ','.join(f'{k}=?' for k in keys)
                c.execute(f'UPDATE {self.table} SET {sets} WHERE id=?', vals + [self.selected_id])
            else:
                c.execute(f'INSERT INTO {self.table}({",".join(keys)}) VALUES({",".join("?" for _ in keys)})', vals)
        self.clear()
        self.load()

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
                self.tree.insert('', 'end', iid=str(r['id']), values=[r[k] for k, _ in self.fields])

    def pick_row(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_id = int(sel[0])
        vals = self.tree.item(sel[0], 'values')
        for (key, _), value in zip(self.fields, vals):
            self.vars[key].set(value)

    def export_csv(self):
        if not self.current_rows:
            return messagebox.showerror('Export', 'No data to export')
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        cols = [k for k, _ in self.fields]
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(self.current_rows)
        messagebox.showinfo('Exported', path)

    def export_pdf(self, path=None):
        if not self.current_rows:
            messagebox.showerror('Export', 'No data to export')
            return None
        path = path or filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF', '*.pdf')])
        if not path:
            return None
        make_report_pdf(f'{self.table.title()} Report', [k for k, _ in self.fields], self.current_rows, path)
        messagebox.showinfo('Exported', path)
        return path

    def print_current(self):
        path = os.path.abspath(os.path.join('exports', f'{self.table}_report_print.pdf'))
        if self.export_pdf(path):
            print_pdf_in_browser(path)

    def whatsapp_current(self):
        # Same behaviour as Invoice/Challan's WhatsApp: build the PDF first,
        # then send with a friendly success/error popup.
        path = os.path.abspath(os.path.join('exports', f'{self.table}_report_send.pdf'))
        if not self.export_pdf(path):
            return
        phone = simpledialog.askstring('WhatsApp', 'Enter WhatsApp number')
        if not phone:
            return
        try:
            result = open_whatsapp(phone, f'{self.table.title()} report PDF saved at: {path}', path)
            messagebox.showinfo('WhatsApp', result)
        except Exception as e:
            messagebox.showerror('WhatsApp', 'Could not send report PDF:\n' + str(e))

    def email_current(self):
        path = os.path.abspath(os.path.join('exports', f'{self.table}_report_send.pdf'))
        if not self.export_pdf(path):
            return
        to = simpledialog.askstring('Email', 'Enter email address')
        if not to:
            return
        try:
            msg = send_email_or_compose(to, f'{self.table.title()} Report', 'Please find the report PDF attached/saved.', path)
            messagebox.showinfo('Email', msg)
        except Exception as e:
            messagebox.showerror('Email not sent', str(e))