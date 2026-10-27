"""
Settings screen — single dedicated file.

Lets the user change, from inside the app (no code editing needed):
  - Company Name / Address / Phone / Email / GSTIN / PAN / State
  - Bank Details text (shown on every PDF, e.g. Quotation)
  - QR / Scanner image, e.g. UPI QR code (shown in Bank Details on the
    Quotation PDF)
  - Email (SMTP) login used for the "Email" button on Quotation/Challan/
    Invoice screens

Everything is saved to data/settings.json via config.save_settings() and is
reloaded automatically the next time the app starts. Because config.COMPANY
and config.EMAIL are plain dicts, changes here also apply immediately to any
PDF generated afterwards in the same session -- no restart required.

Note: Company Logo support has been removed entirely - no logo is printed
on any PDF anymore, and there is no logo setting anywhere in this screen.

The QR/Scanner image is copied into an `assets/` folder inside the project
so the saved path keeps working even if the original picked file is later
moved or deleted from its original location.
"""
import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import config
from config import COMPANY, EMAIL

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.vars = {}
        self.scanner_path = tk.StringVar(value=COMPANY.get('scanner_path', ''))
        self.build()
        self.load()

    # ---------- UI BUILD ----------
    def build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True, padx=8, pady=8)

        # ---- Company details ----
        co = ttk.LabelFrame(wrap, text='Company Details (shown on every Quotation / Invoice / Challan PDF)')
        co.pack(fill='x', pady=(0, 8))
        fields = [
            ('name', 'Company Name', 30), ('phone', 'Phone', 20), ('email', 'Email', 26),
            ('gstin', 'GSTIN', 20), ('pan', 'PAN', 16), ('state', 'State', 18),
        ]
        for i, (key, label, width) in enumerate(fields):
            ttk.Label(co, text=label).grid(row=(i // 3) * 2, column=i % 3, padx=6, pady=(6, 0), sticky='w')
            v = tk.StringVar()
            self.vars[key] = v
            ttk.Entry(co, textvariable=v, width=width).grid(row=(i // 3) * 2 + 1, column=i % 3, padx=6, pady=(0, 8), sticky='ew')

        ttk.Label(co, text='Address (multi-line)').grid(row=4, column=0, padx=6, pady=(0, 0), sticky='w')
        self.address_txt = tk.Text(co, width=60, height=3)
        self.address_txt.grid(row=5, column=0, columnspan=3, padx=6, pady=(0, 8), sticky='ew')

        ttk.Label(co, text='Bank Details (multi-line, e.g. Name / Account No. / IFSC / Holder Name)').grid(row=6, column=0, padx=6, pady=(0, 0), sticky='w')
        self.bank_txt = tk.Text(co, width=60, height=4)
        self.bank_txt.grid(row=7, column=0, columnspan=3, padx=6, pady=(0, 8), sticky='ew')

        # ---- QR / Scanner image (no logo anymore - removed entirely) ----
        img = ttk.LabelFrame(wrap, text='QR / Scanner Image (used on the Quotation PDF)')
        img.pack(fill='x', pady=(0, 8))
        ttk.Label(img, text='QR / Scanner Image').grid(row=0, column=0, padx=6, pady=6, sticky='w')
        ttk.Entry(img, textvariable=self.scanner_path, width=52, state='readonly').grid(row=0, column=1, padx=6, pady=6, sticky='ew')
        ttk.Button(img, text='Browse...', command=self.browse_scanner).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(img, text='Preview', command=lambda: self.preview_image(self.scanner_path.get())).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(img, text='Clear', command=lambda: self.scanner_path.set('')).grid(row=0, column=4, padx=6, pady=6)
        ttk.Label(img, text='Tip: any PNG / JPG works. It is copied into the project\'s assets/ folder automatically.').grid(row=1, column=0, columnspan=5, padx=6, pady=(0, 6), sticky='w')

        # ---- Email (SMTP) ----
        em = ttk.LabelFrame(wrap, text='Email (SMTP) — used by the "Email" button. Leave blank to just open your mail app instead.')
        em.pack(fill='x', pady=(0, 8))
        efields = [('smtp_host', 'SMTP Host', 20), ('smtp_port', 'SMTP Port', 10),
                   ('username', 'Email / Username', 26), ('password', 'App Password', 22)]
        for i, (key, label, width) in enumerate(efields):
            ttk.Label(em, text=label).grid(row=0, column=i, padx=6, pady=(6, 0), sticky='w')
            v = tk.StringVar()
            self.vars[key] = v
            show = '*' if key == 'password' else ''
            ttk.Entry(em, textvariable=v, width=width, show=show).grid(row=1, column=i, padx=6, pady=(0, 8), sticky='ew')
        self.use_tls = tk.BooleanVar(value=True)
        ttk.Checkbutton(em, text='Use TLS', variable=self.use_tls).grid(row=1, column=len(efields), padx=6)

        # ---- Save ----
        btn_row = ttk.Frame(wrap)
        btn_row.pack(fill='x', pady=6)
        ttk.Button(btn_row, text='Save Settings', command=self.save).pack(side='left', padx=4)
        ttk.Button(btn_row, text='Reload', command=self.load).pack(side='left', padx=4)
        self.status_lbl = ttk.Label(btn_row, text='')
        self.status_lbl.pack(side='left', padx=10)

    # ---------- DATA ----------
    def load(self):
        for key in ('name', 'phone', 'email', 'gstin', 'pan', 'state'):
            self.vars[key].set(COMPANY.get(key, ''))
        self.address_txt.delete('1.0', 'end')
        self.address_txt.insert('1.0', COMPANY.get('address', ''))
        self.bank_txt.delete('1.0', 'end')
        self.bank_txt.insert('1.0', COMPANY.get('bank', ''))
        self.scanner_path.set(COMPANY.get('scanner_path', ''))
        for key in ('smtp_host', 'smtp_port', 'username', 'password'):
            self.vars[key].set(str(EMAIL.get(key, '') or ''))
        self.use_tls.set(bool(EMAIL.get('use_tls', True)))
        self.status_lbl.config(text='')

    def browse_scanner(self):
        self._browse_image(self.scanner_path, 'scanner')

    def _browse_image(self, target_var, kind):
        path = filedialog.askopenfilename(
            title=f'Select {kind} image',
            filetypes=[('Image files', '*.png *.jpg *.jpeg *.gif *.bmp'), ('All files', '*.*')],
        )
        if not path:
            return
        os.makedirs(ASSETS_DIR, exist_ok=True)
        ext = os.path.splitext(path)[1] or '.png'
        dest = os.path.join(ASSETS_DIR, f'{kind}{ext}')
        try:
            shutil.copyfile(path, dest)
        except Exception as e:
            return messagebox.showerror('Copy failed', str(e))
        target_var.set(dest)

    def preview_image(self, path):
        if not path or not os.path.exists(path):
            return messagebox.showinfo('Preview', 'No image selected yet.')
        try:
            os.startfile(path)
        except Exception:
            import webbrowser
            webbrowser.open(f'file://{os.path.abspath(path)}')

    def save(self):
        name = self.vars['name'].get().strip()
        if not name:
            return messagebox.showerror('Required', 'Company Name is required')

        COMPANY['name'] = name
        COMPANY['phone'] = self.vars['phone'].get().strip()
        COMPANY['email'] = self.vars['email'].get().strip()
        COMPANY['gstin'] = self.vars['gstin'].get().strip()
        COMPANY['pan'] = self.vars['pan'].get().strip()
        COMPANY['state'] = self.vars['state'].get().strip()
        COMPANY['address'] = self.address_txt.get('1.0', 'end').strip()
        COMPANY['bank'] = self.bank_txt.get('1.0', 'end').strip()
        COMPANY['scanner_path'] = self.scanner_path.get().strip()

        EMAIL['smtp_host'] = self.vars['smtp_host'].get().strip()
        port_raw = self.vars['smtp_port'].get().strip()
        try:
            EMAIL['smtp_port'] = int(port_raw) if port_raw else 587
        except ValueError:
            return messagebox.showerror('Invalid Port', 'SMTP Port must be a number')
        EMAIL['username'] = self.vars['username'].get().strip()
        EMAIL['password'] = self.vars['password'].get()
        EMAIL['use_tls'] = bool(self.use_tls.get())

        config.save_settings()
        self.status_lbl.config(text='Saved ✓')
        messagebox.showinfo('Settings', 'Settings saved. New Quotation/Invoice/Challan PDFs will use these details immediately.')