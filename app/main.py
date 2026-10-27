import tkinter as tk
from client_license import LicenseManager, ActivationGUI
from login import show_login
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import date, datetime
import csv, os, shutil, webbrowser
from database import conn, init_db, next_number
from config import APP_NAME, DEFAULT_GST_RATE, COMPANY
from services.pdf_service import make_pdf, make_report_pdf
from services.send_service import open_whatsapp, send_email_or_compose, print_pdf_in_browser
from app.master_base import MasterBase
from app.customer_tab import CustomerTab
from app.product_tab import ProductTab
# from app.quotation_tab import DocumentTab
from app.challan_tab import ChallanTab
from app.invoice_tab import InvoiceTab
from app.Settings_tab import SettingsTab

class App(tk.Tk):
    # UI closely follows the supplied Universal Solutions dashboard reference.
    COLORS = {
        'navy': '#032B4C',
        'navy2': '#062F53',
        'blue': '#0877D8',
        'blue_hover': '#0668BD',
        'page': '#F7F9FD',
        'white': '#FFFFFF',
        'text': '#0F172A',
        'muted': '#334155',
        'border': '#DFE5EE',
    }

    def __init__(self):
        super().__init__()
        self.title('JAY BHAVANI TRANSPORT - Billing System')
        self.geometry('1536x900')
        self.minsize(1180, 720)
        init_db()
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.configure(bg=self.COLORS['page'])
        self.configure_styles()

        shell = tk.Frame(self, bg=self.COLORS['page'])
        shell.pack(fill='both', expand=True)

        self.sidebar = tk.Frame(shell, bg=self.COLORS['navy'], width=258)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        right = tk.Frame(shell, bg=self.COLORS['page'])
        right.pack(side='left', fill='both', expand=True)
        self.right_panel = right
        self.sidebar_visible = True

        topbar = tk.Frame(right, bg=self.COLORS['white'], height=44,
                          highlightbackground=self.COLORS['border'], highlightthickness=1)
        topbar.pack(fill='x')
        topbar.pack_propagate(False)
        self.menu_toggle_btn = tk.Button(
            topbar, text='☰', font=('Segoe UI', 13, 'bold'), bd=0, relief='flat',
            bg='white', fg=self.COLORS['text'], activebackground='#EEF2F8',
            cursor='hand2', command=self.toggle_sidebar)
        self.menu_toggle_btn.pack(side='left', padx=(14, 10))
        tk.Label(topbar, text='User: Admin', bg='white', fg=self.COLORS['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side='right', padx=(8, 18))
        self.user_icon = tk.Canvas(topbar, width=24, height=24, bg='white', highlightthickness=0)
        self.user_icon.pack(side='right')
        self._draw_user_icon(self.user_icon)

        content = tk.Frame(right, bg=self.COLORS['page'])
        content.pack(fill='both', expand=True)
        self.nb = ttk.Notebook(content, style='Hidden.TNotebook')
        self.nb.pack(fill='both', expand=True)
        self.tab_names = {}
        tabs = [
            (HomeTab, 'Home'), (CustomerTab, 'Customers'), (ProductTab, 'Products'),
            (RouteTab, 'Routes'), 
            # (DocumentTab, 'Quotation'),

            (ChallanTab, 'Delivery Challan'), (InvoiceTab, 'Tax Invoice (Bill)'),
            (ReportsTab, 'Reports'), (SettingsTab, 'Settings'),
        ]
        for cls, name in tabs:
            frame = cls(self.nb, self)
            self.nb.add(frame, text=name)
            self.tab_names[name] = frame
        self.build_sidebar()
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self.refresh_sidebar())

    def configure_styles(self):
        self.style.configure('Main.TFrame', background=self.COLORS['page'])
        self.style.configure('App.TFrame', background=self.COLORS['page'])
        self.style.configure('Hidden.TNotebook', background=self.COLORS['page'], borderwidth=0,
                             tabmargins=(0, 0, 0, 0))
        self.style.layout('Hidden.TNotebook.Tab', [])
        self.style.configure('TLabelframe', background='white', foreground='#1F2937',
                             bordercolor=self.COLORS['border'], relief='solid')
        self.style.configure('TLabelframe.Label', background='white', foreground='#111827',
                             font=('Segoe UI', 10, 'bold'))
        self.style.configure('TLabel', background='white', foreground=self.COLORS['muted'],
                             font=('Segoe UI', 9))
        self.style.configure('TEntry', fieldbackground='white', foreground='#172033',
                             bordercolor='#CBD5E1', lightcolor='#4F8CFF', darkcolor='#CBD5E1', padding=5)
        self.style.configure('TCombobox', fieldbackground='white', foreground='#172033',
                             bordercolor='#CBD5E1', arrowsize=14, padding=5)
        self.style.configure('TButton', font=('Segoe UI', 9, 'bold'), foreground='white',
                             background=self.COLORS['blue'], borderwidth=0, padding=(12, 7))
        self.style.map('TButton', background=[('active', self.COLORS['blue_hover']), ('pressed', '#055495')])
        self.style.configure('Treeview', background='white', fieldbackground='white',
                             foreground='#172033', rowheight=30, bordercolor='#D8E0EC',
                             borderwidth=1, font=('Segoe UI', 9))
        self.style.configure('Treeview.Heading', background='#F0F2F6', foreground='#172033',
                             font=('Segoe UI', 9, 'bold'), padding=8)
        self.style.map('Treeview', background=[('selected', '#CFE5FF')],
                       foreground=[('selected', '#082F52')])

    def build_sidebar(self):
        sb = self.sidebar
        brand = tk.Frame(sb, bg=self.COLORS['navy'])
        brand.pack(fill='x', padx=18, pady=(22, 6))
        self.draw_logo(brand).pack(side='left')
        name = tk.Frame(brand, bg=self.COLORS['navy'])
        name.pack(side='left', padx=10)
        tk.Label(name, text='JAY BHAVANI ', bg=self.COLORS['navy'], fg='white',
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        tk.Label(name, text='TRANSPORT', bg=self.COLORS['navy'], fg='white',
                 font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 1))
        tk.Label(sb, text='Billing & Invoice System', bg=self.COLORS['navy'], fg='white',
                 font=('Segoe UI', 9)).pack(pady=(0, 14))

        self.nav_buttons = {}
        self.nav_icons = {}
        # 'children' (when present) turns an item into an expandable Masters-style
        # menu; each child is (label, target, icon) and is rendered indented
        # underneath the parent when the parent is clicked.
        items = [
            ('Home', 'Home', '\u2302', None),
            ('Masters', None, '\u25A4', [
                ('Customer', 'Customers', '\u2022'),
                ('Product', 'Products', '\u2022'),
            ]),
            ('Quotation', 'Quotation', '\u270E', None),
            ('Delivery Challan', 'Delivery Challan', '\u25A3', None),
            ('Tax Invoice (Bill)', 'Tax Invoice (Bill)', '\u25A5', None),
            ('Route Rate Master', 'Route Rate Master', '\u2690', None),
            ('Reports', 'Reports', '\u25A8', None),
            ('Settings', 'Settings', '\u2699', None),
            ('Backup', 'Backup', '\u2601', None),
            ('Exit', 'Exit', '\u2715', None),
        ]
        self.master_targets = {'Customers', 'Products'}
        self.submenu_frames = {}
        self.submenu_open = {}
        for label, target, icon, children in items:
            row = tk.Frame(sb, bg=self.COLORS['navy'], height=40)
            row.pack(fill='x', padx=8, pady=1)
            row.pack_propagate(False)
            icon_lbl = tk.Label(row, text=icon, bg=self.COLORS['navy'], fg='white',
                                font=('Segoe UI Symbol', 13), width=3)
            icon_lbl.pack(side='left')

            if children:
                arrow_lbl = tk.Label(row, text='▾', bg=self.COLORS['navy'], fg='white',
                                     font=('Segoe UI', 9), width=2)
                arrow_lbl.pack(side='right', padx=(0, 6))
                btn = tk.Button(row, text=label, anchor='w', bd=0, relief='flat',
                                font=('Segoe UI', 10), fg='white', bg=self.COLORS['navy'],
                                activebackground=self.COLORS['blue'], activeforeground='white',
                                padx=0, command=lambda t=label: self.toggle_submenu(t))
                btn.pack(side='left', fill='both', expand=True)
                self.nav_buttons[label] = btn
                self.nav_icons[label] = icon_lbl
                self.submenu_open[label] = False

                sub_frame = tk.Frame(sb, bg=self.COLORS['navy2'])
                self.submenu_frames[label] = (sub_frame, arrow_lbl)
                for c_label, c_target, c_icon in children:
                    c_row = tk.Frame(sub_frame, bg=self.COLORS['navy2'], height=36)
                    c_row.pack(fill='x', padx=(20, 8), pady=1)
                    c_row.pack_propagate(False)
                    c_icon_lbl = tk.Label(c_row, text=c_icon, bg=self.COLORS['navy2'], fg='white',
                                          font=('Segoe UI Symbol', 11), width=2)
                    c_icon_lbl.pack(side='left')
                    c_btn = tk.Button(c_row, text=c_label, anchor='w', bd=0, relief='flat',
                                      font=('Segoe UI', 9), fg='white', bg=self.COLORS['navy2'],
                                      activebackground=self.COLORS['blue'], activeforeground='white',
                                      padx=0, command=lambda t=c_target: self.sidebar_action(t))
                    c_btn.pack(side='left', fill='both', expand=True)
                    self.nav_buttons[c_target] = c_btn
                    self.nav_icons[c_target] = c_icon_lbl
                continue

            btn = tk.Button(row, text=label, anchor='w', bd=0, relief='flat',
                            font=('Segoe UI', 10), fg='white', bg=self.COLORS['navy'],
                            activebackground=self.COLORS['blue'], activeforeground='white',
                            padx=0, command=lambda t=target: self.sidebar_action(t))
            btn.pack(side='left', fill='both', expand=True)
            self.nav_buttons[target] = btn
            self.nav_icons[target] = icon_lbl

        sep = tk.Frame(sb, bg='#56708A', height=1)
        sep.pack(fill='x', side='bottom', padx=18, pady=(0, 78))
        self.clock_label = tk.Label(sb, bg=self.COLORS['navy'], fg='white', justify='left',
                                    font=('Segoe UI', 9, 'bold'))
        self.clock_label.pack(side='bottom', anchor='w', padx=22, pady=18)
        self.update_clock()
        self.refresh_sidebar()

    def update_clock(self):
        today = date.today()
        self.clock_label.configure(text=today.strftime('%d %b %Y') + '\n' +
                                    today.strftime('%a %I:%M:%S %p'))
        self.after(1000, self.update_clock)

    def draw_logo(self, parent):
        c = tk.Canvas(parent, width=50, height=58, bg=self.COLORS['navy'], highlightthickness=0)
        c.create_polygon(25, 2, 47, 10, 44, 36, 25, 55, 6, 36, 3, 10,
                        fill='#0D65B8', outline='#72B7FF', width=2)
        c.create_polygon(25, 9, 39, 14, 37, 33, 25, 46, 13, 33, 11, 14,
                        fill='#0A3D70', outline='')
        c.create_text(25, 28, text='US', fill='white', font=('Segoe UI', 16, 'bold'))
        return c

    def _draw_user_icon(self, c):
        c.create_oval(9, 3, 16, 10, outline='#0B3A63', width=1.5)
        c.create_arc(5, 11, 20, 24, start=0, extent=180, outline='#0B3A63', width=1.5)

    def toggle_sidebar(self):
        # Click the ☰ icon to open (show) or close (hide) the whole sidebar.
        if self.sidebar_visible:
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side='left', fill='y', before=self.right_panel)
        self.sidebar_visible = not self.sidebar_visible

    def toggle_submenu(self, label):
        is_open = self.submenu_open.get(label, False)
        if is_open:
            self.close_submenu(label)
        else:
            # Accordion behaviour: opening one submenu auto-closes any others.
            self.close_all_submenus(except_label=label)
            self.open_submenu(label)

    def open_submenu(self, label):
        sub_frame, arrow_lbl = self.submenu_frames[label]
        if not self.submenu_open.get(label, False):
            sub_frame.pack(fill='x', after=arrow_lbl.master)
            arrow_lbl.configure(text='▴')
            self.submenu_open[label] = True

    def close_submenu(self, label):
        sub_frame, arrow_lbl = self.submenu_frames[label]
        if self.submenu_open.get(label, False):
            sub_frame.pack_forget()
            arrow_lbl.configure(text='▾')
            self.submenu_open[label] = False

    def close_all_submenus(self, except_label=None):
        for label in list(self.submenu_frames):
            if label != except_label:
                self.close_submenu(label)

    def sidebar_action(self, target):
        if target == 'Route Rate Master':
            target = 'Routes'
        if target in self.master_targets:
            self.open_submenu('Masters')
        else:
            self.close_all_submenus()
        if target in self.tab_names:
            self.nb.select(self.tab_names[target])
            self.refresh_current_tab()
            return
        if target == 'Exit':
            self.destroy()
            return
        if target == 'Backup':
            self.open_folder('data')
            return
        if target == 'Logout':
            messagebox.showinfo('Logout', 'Admin session is active.')
        else:
            messagebox.showinfo(target, f'{target} coming soon.')

    def refresh_sidebar(self):
        current = self.nb.tab(self.nb.select(), 'text') if self.nb.tabs() else 'Home'
        aliases = {'Routes': 'Route Rate Master'}
        active = aliases.get(current, current)
        if current in self.master_targets:
            self.open_submenu('Masters')
        else:
            self.close_all_submenus()
        for target, btn in self.nav_buttons.items():
            if target == 'Masters':
                is_active = current in self.master_targets
            else:
                is_active = target == active
            base_font_size = 9 if target in self.master_targets else 10
            idle_bg = btn.master.cget('bg')
            btn.configure(bg=self.COLORS['blue'] if is_active else idle_bg,
                          font=('Segoe UI', base_font_size, 'bold' if is_active else 'normal'))
            self.nav_icons[target].configure(bg=self.COLORS['blue'] if is_active else idle_bg)

    def refresh_current_tab(self):
        tab = self.nb.nametowidget(self.nb.select())
        for method in ('load_challans', 'load_invoices', 'refresh_refs', 'load'):
            if hasattr(tab, method):
                getattr(tab, method)()
        if hasattr(tab, 'redraw'):
            tab.redraw()

    def open_folder(self, folder):
        path = os.path.abspath(folder)
        os.makedirs(path, exist_ok=True)
        os.startfile(path)


class HomeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(style='Main.TFrame')
        self.build()

    def build(self):
        # --- Scrollable wrapper so long content is never hidden ---
        outer = tk.Frame(self, bg=self.app.COLORS['page'])
        outer.pack(fill='both', expand=True)

        canvas = tk.Canvas(outer, bg=self.app.COLORS['page'], highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')

        page = tk.Frame(canvas, bg=self.app.COLORS['page'])
        page_window = canvas.create_window((0, 0), window=page, anchor='nw')

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

        # Header area from the supplied reference.
        header = tk.Frame(page, bg=self.app.COLORS['page'])
        header.pack(fill='x', padx=28, pady=(26, 18))
        intro = tk.Frame(header, bg=self.app.COLORS['page'])
        intro.pack(side='left', fill='x', expand=True)
        tk.Label(intro, text='Welcome, Admin 👋', bg=self.app.COLORS['page'], fg='#0F172A',
                 font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        tk.Label(intro, text='Manage your business easily and efficiently.',
                 bg=self.app.COLORS['page'], fg='#111827', font=('Segoe UI', 11)).pack(anchor='w', pady=(9, 0))

        self.info_card(header, "Today's Date", date.today().strftime('%d-%m-%Y'),
                       date.today().strftime('%A'), '#2D83DA', 'calendar').pack(side='left', padx=8)
        self.info_card(header, 'Financial Year', self.financial_year(), '', '#6C7FC5', 'year').pack(side='left', padx=8)

        panel = tk.Frame(page, bg='white', highlightbackground=self.app.COLORS['border'], highlightthickness=1)
        panel.pack(fill='both', expand=True, padx=14, pady=(0, 0))

        stats = tk.Frame(panel, bg='white')
        stats.pack(fill='x', padx=26, pady=(22, 18))
        data = self.dashboard_data()
        cards = [
            ('Total Quotations', data['quotations'], 'This Month', '#2D83DA', '#EEF5FF', 'quote'),
            ('Total Challans', data['challans'], 'This Month', '#4BAA43', '#F0F9EA', 'truck'),
            ('Total Invoices', data['invoices'], 'This Month', '#7D55C7', '#F5EEFF', 'invoice'),
            ('Total Sales (This Month)', self.money(data['month_sales']), 'Inclusive of Tax', '#D98213', '#FFF4E2', 'rupee'),
        ]
        for title, value, sub, color, bg, icon in cards:
            self.stat_card(stats, title, value, sub, color, bg, icon).pack(side='left', fill='x', expand=True, padx=10)

        quick = tk.Frame(panel, bg='white', highlightbackground=self.app.COLORS['border'], highlightthickness=1)
        quick.pack(fill='x', padx=26, pady=(10, 18))
        tk.Label(quick, text='Quick Actions', bg='white', fg='#111827',
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=20, pady=(10, 8))
        actions = [
            ('New Quotation', 'Quotation', '#EEF5FF', '#2D83DA', 'quote'),
            ('New Challan', 'Delivery Challan', '#EEF9F5', '#138B78', 'truck'),
            ('New Invoice\n(From Challan)', 'Tax Invoice (Bill)', '#F4EDFF', '#7D55C7', 'invoice'),
            ('Customer Master', 'Customers', '#FFF1F5', '#C74772', 'people'),
            ('Product Master', 'Products', '#FFF7E8', '#D98213', 'box'),
            ('Route Master', 'Routes', '#EEF9FD', '#2AA5C6', 'route'),
        ]
        actions_row = tk.Frame(quick, bg='white')
        actions_row.pack(fill='x', padx=10, pady=(0, 14))
        for label, target, bg, color, icon in actions:
            card = tk.Frame(actions_row, bg=bg, highlightbackground='#E2E8F0', highlightthickness=1,
                            width=170, height=92, cursor='hand2')
            card.pack(side='left', fill='x', expand=True, padx=6)
            card.pack_propagate(False)
            self.action_icon(card, icon, color).pack(pady=(10, 3))
            tk.Label(card, text=label, bg=bg, fg='#0F172A', font=('Segoe UI', 9, 'bold'),
                     justify='center').pack()
            card.bind('<Button-1>', lambda e, t=target: self.app.sidebar_action(t))
            for child in card.winfo_children():
                child.bind('<Button-1>', lambda e, t=target: self.app.sidebar_action(t))

        tk.Label(panel, text='Recent Documents', bg='white', fg='#111827',
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=42, pady=(4, 8))
        table_wrap = tk.Frame(panel, bg='white')
        table_wrap.pack(fill='x', padx=42)
        self.tree = ttk.Treeview(table_wrap, columns=('type', 'number', 'party', 'date', 'amount', 'status'),
                                 show='headings', height=6)
        for key, label, width in [
            ('type', 'Type', 110), ('number', 'Number', 130), ('party', 'Party Name', 280),
            ('date', 'Date', 130), ('amount', 'Amount (₹)', 150), ('status', 'Status', 110)
        ]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor='w' if key in ('type', 'number', 'party', 'status') else 'center')
        self.tree.pack(fill='x')
        self.load_recent()

        bottom = tk.Frame(panel, bg='white')
        bottom.pack(fill='x', padx=26, pady=22)
        self.wide_card(bottom, 'Total Sales (This Financial Year)', self.money(data['year_sales']), 'bar').pack(
            side='left', fill='x', expand=True, padx=8)
        self.wide_card(bottom, 'Total Outstanding', self.money(data['outstanding']), 'pie').pack(
            side='left', fill='x', expand=True, padx=8)

        tk.Label(page, text='© 2025 JAY BHAVANI TRANSPORT. All Rights Reserved.', bg=self.app.COLORS['page'],
                 fg='#334155', font=('Segoe UI', 8)).pack(fill='x', pady=8)

    def financial_year(self):
        y = date.today().year
        if date.today().month < 4:
            return f'{y-1} - {y}'
        return f'{y} - {y+1}'

    def info_card(self, parent, title, value, sub, color, icon):
        f = tk.Frame(parent, bg='white', highlightbackground=self.app.COLORS['border'],
                     highlightthickness=1, width=258, height=84)
        f.pack_propagate(False)
        self.action_icon(f, icon, color, size=34).place(x=16, y=24)
        tk.Label(f, text=title, bg='white', fg='#111827', font=('Segoe UI', 9)).place(x=65, y=12)
        tk.Label(f, text=value, bg='white', fg='#0F172A', font=('Segoe UI', 13, 'bold')).place(x=65, y=34)
        if sub:
            tk.Label(f, text=sub, bg='white', fg='#334155', font=('Segoe UI', 8)).place(x=65, y=60)
        return f

    def stat_card(self, parent, title, value, sub, color, bg, icon):
        # Taller card + tighter internal spacing so the subtitle ("This Month" etc.)
        # always has room and is never clipped at the bottom/top edge.
        f = tk.Frame(parent, bg='white', highlightbackground=self.app.COLORS['border'],
                     highlightthickness=1, height=132)
        f.pack_propagate(False)
        self.action_icon(f, icon, color, bg=bg, size=54).pack(side='left', padx=14, pady=14)
        body = tk.Frame(f, bg='white')
        body.pack(side='left', fill='both', expand=True, pady=(16, 16))
        tk.Label(body, text=title, bg='white', fg='#111827', font=('Segoe UI', 9),
                 wraplength=170, justify='left').pack(anchor='w')
        tk.Label(body, text=str(value), bg='white', fg='#0F172A', font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(6, 0))
        if sub:
            tk.Label(body, text=sub, bg='white', fg='#334155', font=('Segoe UI', 9)).pack(anchor='w', pady=(6, 0))
        return f

    def wide_card(self, parent, title, value, icon):
        f = tk.Frame(parent, bg='white', highlightbackground=self.app.COLORS['border'],
                     highlightthickness=1, height=78)
        f.pack_propagate(False)
        self.action_icon(f, icon, '#2D5A88', bg='#F8FAFC', size=44).place(x=18, y=16)
        tk.Label(f, text=title, bg='white', fg='#111827', font=('Segoe UI', 10)).place(x=72, y=13)
        tk.Label(f, text=value, bg='white', fg='#0F172A', font=('Segoe UI', 15, 'bold')).place(x=72, y=38)
        return f

    def action_icon(self, parent, kind, color, bg='#FFFFFF', size=46):
        c = tk.Canvas(parent, width=size, height=size, bg=parent.cget('bg'), highlightthickness=0)
        pad = 2
        c.create_oval(pad, pad, size-pad, size-pad, fill=bg, outline='')
        s = size / 46.0
        def line(x1,y1,x2,y2,w=2):
            c.create_line(x1*s,y1*s,x2*s,y2*s,fill=color,width=w*s,capstyle='round')
        if kind in ('quote', 'invoice'):
            c.create_rectangle(15*s,10*s,31*s,35*s, outline=color, width=max(1,int(2*s)))
            line(19,17,27,17); line(19,23,27,23); line(19,29,25,29)
            if kind == 'quote':
                line(31,27,37,27); line(34,24,34,30)
        elif kind == 'truck':
            c.create_rectangle(10*s,17*s,29*s,31*s, outline=color, width=max(1,int(2*s)))
            c.create_rectangle(29*s,21*s,36*s,31*s, outline=color, width=max(1,int(2*s)))
            c.create_oval(14*s,28*s,20*s,34*s, outline=color, width=max(1,int(2*s)))
            c.create_oval(29*s,28*s,35*s,34*s, outline=color, width=max(1,int(2*s)))
        elif kind == 'people':
            c.create_oval(17*s,11*s,27*s,21*s, outline=color, width=max(1,int(2*s)))
            c.create_arc(11*s,20*s,33*s,39*s, start=0, extent=180, outline=color, width=max(1,int(2*s)))
            c.create_oval(29*s,15*s,36*s,22*s, outline=color, width=max(1,int(2*s)))
        elif kind == 'box':
            c.create_polygon(11*s,17*s,23*s,10*s,35*s,17*s,23*s,24*s, fill='', outline=color)
            line(11,17,11,31); line(35,17,35,31); line(11,31,23,38); line(35,31,23,38); line(23,24,23,38)
        elif kind == 'route':
            c.create_line(12*s,31*s,22*s,21*s,fill=color,width=max(1,int(2*s)))
            c.create_line(22*s,21*s,33*s,14*s,fill=color,width=max(1,int(2*s)))
            c.create_oval(8*s,27*s,16*s,35*s,outline=color,width=max(1,int(2*s)))
            c.create_oval(29*s,10*s,37*s,18*s,outline=color,width=max(1,int(2*s)))
        elif kind == 'rupee':
            c.create_text(size/2, size/2, text='₹', fill=color, font=('Segoe UI', int(24*s), 'bold'))
        elif kind == 'calendar':
            c.create_rectangle(13*s,13*s,33*s,35*s,outline=color,width=max(1,int(2*s)))
            line(13,20,33,20); line(19,10,19,17); line(27,10,27,17)
        elif kind == 'year':
            c.create_rectangle(12*s,14*s,34*s,34*s,outline=color,width=max(1,int(2*s)))
            line(17,24,21,28); line(21,28,30,19)
        elif kind == 'bar':
            c.create_rectangle(13*s,27*s,18*s,35*s,fill=color,outline=color)
            c.create_rectangle(21*s,18*s,26*s,35*s,fill=color,outline=color)
            c.create_rectangle(29*s,10*s,34*s,35*s,fill=color,outline=color)
            line(10,36,38,36,1)
        elif kind == 'pie':
            c.create_oval(11*s,11*s,35*s,35*s,outline=color,width=max(1,int(2*s)))
            c.create_arc(11*s,11*s,35*s,35*s,start=0,extent=115,fill=color,outline=color)
            line(23,23,23,11); line(23,23,35,23)
        return c

    def dashboard_data(self):
        # BUG FIX: every date column in this app (quotations.date,
        # challans.date, invoices.date) is stored as DD-MM-YYYY (e.g.
        # "04-09-2026"), but this method was comparing it against
        # date.today().isoformat() which is YYYY-MM-DD (e.g. "2026-09-04").
        # A plain string BETWEEN on two completely different formats almost
        # never matches, so "Total Challans/Quotations/Invoices (This
        # Month)" on the Home page were showing 0 (or wrong) counts even
        # when records existed. Fix: convert the DD-MM-YYYY date column to
        # YYYYMMDD (same trick already used in the Reports tab) before
        # comparing it to the bounds.
        first = date.today().replace(day=1).strftime('%Y%m%d')
        today = date.today().strftime('%Y%m%d')
        date_expr = "substr(date,7,4)||substr(date,4,2)||substr(date,1,2)"
        with conn() as c:
            q = c.execute(f'SELECT COUNT(*) n FROM quotations WHERE {date_expr} BETWEEN ? AND ?', (first, today)).fetchone()['n']
            ch = c.execute(f'SELECT COUNT(*) n FROM challans WHERE {date_expr} BETWEEN ? AND ?', (first, today)).fetchone()['n']
            inv = c.execute(f'SELECT COUNT(*) n FROM invoices WHERE {date_expr} BETWEEN ? AND ?', (first, today)).fetchone()['n']
            month = c.execute(f'SELECT COALESCE(SUM(total),0) n FROM invoices WHERE {date_expr} BETWEEN ? AND ?', (first, today)).fetchone()['n']
            year = c.execute('SELECT COALESCE(SUM(total),0) n FROM invoices').fetchone()['n']
            out = c.execute('SELECT COALESCE(SUM(balance),0) n FROM invoices').fetchone()['n']
        return {'quotations': q, 'challans': ch, 'invoices': inv,
                'month_sales': month, 'year_sales': year, 'outstanding': out}

    def load_recent(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        with conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT 'INVOICE' type,i.number,c.name party,i.date,i.total amount,'Paid' status FROM invoices i JOIN customers c ON c.id=i.customer_id "
                "UNION ALL SELECT 'CHALLAN',ch.number,c.name,ch.date,ch.total,'Done' FROM challans ch JOIN customers c ON c.id=ch.customer_id "
                "UNION ALL SELECT 'QUOTATION',q.number,c.name,q.date,q.total,'Created' FROM quotations q JOIN customers c ON c.id=q.customer_id "
                "ORDER BY 4 DESC LIMIT 5")]
        for row in rows:
            self.tree.insert('', 'end', values=(row['type'], row['number'], row['party'], row['date'],
                                                self.money(row['amount']), row['status']))

    def money(self, value):
        return f'₹ {float(value or 0):,.2f}'

class RouteTab(MasterBase):
    table = 'routes'
    fields = [
        ('date', 'Date'),
        ('from_city', 'From City'), ('to_city', 'To City'),
        ('rate', 'Rate'), ('rate_type', 'Rate Type'),
    ]
    # New DB columns this screen needs; added automatically if missing.
    NEW_DB_COLUMNS = {'date': 'TEXT'}
    # Extra columns shown at the END of the table for row actions.
    ACTION_COLUMNS = [('dl', 'Download'), ('edit', 'Edit'), ('delete', 'Delete')]
    READONLY_FIELDS = set()

    def __init__(self, parent, app):
        self._ensure_columns()
        super().__init__(parent, app)

    # ---------- ONE-TIME DB MIGRATION (routes table only) ----------
    def _ensure_columns(self):
        with conn() as c:
            cols = [r['name'] for r in c.execute(f'PRAGMA table_info({self.table})')]
            for col, coltype in self.NEW_DB_COLUMNS.items():
                if col not in cols:
                    c.execute(f'ALTER TABLE {self.table} ADD COLUMN {col} {coltype}')

    # ---------- UI BUILD ----------
    def build(self):
        form = ttk.LabelFrame(self, text='Details')
        form.pack(fill='x', padx=8, pady=8)

        for i, (key, label) in enumerate(self.fields):
            ttk.Label(form, text=label).grid(row=i // 4 * 2, column=i % 4, padx=6, pady=(6, 0), sticky='w')
            v = tk.StringVar()
            self.vars[key] = v
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
        ttk.Button(form, text='WhatsApp', command=self.whatsapp_current).grid(row=btn_row + 1, column=1, padx=6, pady=6)
        ttk.Button(form, text='Email', command=self.email_current).grid(row=btn_row + 1, column=2, padx=6, pady=6)
        # NOTE: Export CSV / Save PDF As / Print buttons intentionally removed.

        self.tree_columns = [k for k, _ in self.fields] + [k for k, _ in self.ACTION_COLUMNS]
        self.tree = ttk.Treeview(self, columns=self.tree_columns, show='headings', height=20)
        for k, l in self.fields:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=110)
        for k, l in self.ACTION_COLUMNS:
            self.tree.heading(k, text=l)
            self.tree.column(k, width=90, anchor='center', stretch=False)
        self.tree.pack(fill='both', expand=True, padx=8, pady=8)
        self.tree.bind('<Button-1>', self.on_tree_click)

        self._set_auto_date()


    # ---------- DATA ----------
    def _set_auto_date(self):
        if 'date' in self.vars and not self.vars['date'].get().strip():
            self.vars['date'].set(datetime.now().strftime('%d-%m-%Y'))

    def clear(self):
        for v in self.vars.values():
            v.set('')
        self.selected_id = None
        self._set_auto_date()

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
                    values=[r[k] for k, _ in self.fields] + ['\u2B07 Download', '\u270E Edit', '\U0001F5D1 Delete'],
                )

    def save(self):
        keys = [k for k, _ in self.fields]
        vals = [self.vars[k].get().strip() for k in keys]
        by_key = dict(zip(keys, vals))

        if not by_key['from_city'] or not by_key['to_city']:
            return messagebox.showerror('Required', 'From City and To City are required')

        if not by_key['date']:
            return messagebox.showerror('Required', 'Date is required')

        try:
            datetime.strptime(by_key['date'], '%d-%m-%Y')
        except ValueError:
            return messagebox.showerror('Invalid Date', 'Date must be in DD-MM-YYYY format')

        with conn() as c:
            if self.selected_id:
                sets = ','.join(f'{k}=?' for k in keys)
                c.execute(f'UPDATE {self.table} SET {sets} WHERE id=?', vals + [self.selected_id])
            else:
                c.execute(f'INSERT INTO {self.table}({",".join(keys)}) VALUES({",".join("?" for _ in keys)})', vals)
        self.clear()
        self.load()

    def delete_selected(self):
        if not self.selected_id:
            return messagebox.showerror('Delete', 'Load a record first (click Edit on a row, or select one)')
        self._delete_by_id(self.selected_id)

    # ---------- ROW ACTIONS (Download / Edit / Delete in the table) ----------
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
        self.selected_id = int(row_id)
        vals = self.tree.item(row_id, 'values')[:len(self.fields)]
        for (key, _), value in zip(self.fields, vals):
            self.vars[key].set(value)

    def download_row(self, row_id):
        idx = self.tree.index(row_id)
        if idx >= len(self.current_rows):
            return
        row = self.current_rows[idx]
        safe_name = f"{row.get('from_city', '')}_{row.get('to_city', '')}".strip('_') or 'route'
        safe_name = ''.join(ch for ch in safe_name if ch.isalnum() or ch in (' ', '_', '-')).strip() or 'route'
        path = filedialog.asksaveasfilename(
            defaultextension='.pdf', filetypes=[('PDF', '*.pdf')],
            initialfile=f'{safe_name}.pdf',
        )
        if not path:
            return
        make_report_pdf('Route Details', [k for k, _ in self.fields], [row], path)
        messagebox.showinfo('Downloaded', path)

    def delete_row(self, row_id):
        self._delete_by_id(row_id)

    def _delete_by_id(self, row_id):
        if not messagebox.askyesno('Delete', 'Delete this route record? This cannot be undone.'):
            return
        with conn() as c:
            c.execute(f'DELETE FROM {self.table} WHERE id=?', (row_id,))
        if self.selected_id and str(self.selected_id) == str(row_id):
            self.clear()
        self.load()

    # Kept for compatibility with the base class' double-click binding.
    def pick_row(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.edit_row(sel[0])

class ReportsTab(ttk.Frame):
    ACTION_COLUMNS = [('dl', 'Download')]

    # Friendly column headings (used instead of the raw DB/column key).
    # Any column not listed here just falls back to showing its raw key,
    # same as before.
    COLUMN_LABELS = {
        'customer_name': 'Customer Name',
        'product': 'Product',
        'gstin': 'GSTIN',
        'bill_no': 'Bill No.',
        'date': 'Date',
        'qty': 'Quantity',
        'loading': 'Loading',
        'rate': 'Rate',
        'total': 'Total',
        'godown': 'Godown',
        'item': 'Item',
    }
    # Which (label_column, value_column, chart_title) to plot for each report.
    CHART_SPEC = {
        'billing': ('date', 'total', 'Total by Date'),
        'gst': ('product', 'amount', 'Amount by Product'),
        'customer_month': ('customer', 'total', 'Total by Customer'),
        'material': ('item_name', 'amount', 'Amount by Item'),
        'all_products': ('item_name', 'price', 'Price by Product'),
        'customer_report': ('customer', 'grand_total', 'Business by Customer'),
        'srv_report': ('date', 'total', 'SRV/Challan Total by Date'),
    }

    def __init__(self,parent,app):super().__init__(parent);self.app=app;self.build()

    def build(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=8)
        today = date.today()
        # NOTE: date fields start BLANK (not "this month only") so every
        # report shows ALL saved records by default. Earlier this defaulted
        # to the current month, so any invoice dated outside that window
        # silently produced an empty table with no explanation at all -
        # that's what made it look like "reports have nothing in them".
        # User can still narrow the range by typing dates and clicking a
        # report button again.
        self.f = tk.StringVar(value='')
        self.t = tk.StringVar(value='')

        # ---- Row 1: date filters ----
        row1 = ttk.Frame(top)
        row1.pack(fill='x')
        ttk.Label(row1, text='From (DD-MM-YYYY)').pack(side='left')
        ttk.Entry(row1, textvariable=self.f, width=12).pack(side='left', padx=4)
        ttk.Label(row1, text='To (DD-MM-YYYY)').pack(side='left')
        ttk.Entry(row1, textvariable=self.t, width=12).pack(side='left', padx=4)

        # ---- Row 2: Search box + Search button ----
        # Kept on its own row, on the LEFT, so it is always fully visible and
        # never gets pushed off-screen / hidden when the window is resized
        # smaller (which used to happen when everything shared one row).
        row2 = ttk.Frame(top)
        row2.pack(fill='x', pady=(6, 0))
        self.search = tk.StringVar()
        ttk.Label(row2, text='Search').pack(side='left', padx=(0, 2))
        ttk.Entry(row2, textvariable=self.search, width=24).pack(side='left', padx=2)
        ttk.Button(row2, text='Search', command=self.apply_search).pack(side='left', padx=4)

        # ---- Row 3: report buttons + Email, in a horizontally scrollable strip ----
        # If the window becomes narrow, these buttons scroll instead of
        # disappearing or squeezing out the Search row above.
        row3_outer = ttk.Frame(top)
        row3_outer.pack(fill='x', pady=(6, 0))
        row3_canvas = tk.Canvas(row3_outer, height=42, highlightthickness=0)
        row3_hscroll = ttk.Scrollbar(row3_outer, orient='horizontal', command=row3_canvas.xview)
        row3_canvas.configure(xscrollcommand=row3_hscroll.set)
        row3_canvas.pack(side='top', fill='x', expand=True)
        row3_hscroll.pack(side='top', fill='x')
        row3 = ttk.Frame(row3_canvas)
        row3_canvas.create_window((0, 0), window=row3, anchor='nw')

        def _row3_configure(event):
            row3_canvas.configure(scrollregion=row3_canvas.bbox('all'))
        row3.bind('<Configure>', _row3_configure)

        def _row3_mousewheel(event):
            delta = -1 * (event.delta // 120) if event.delta else 0
            if delta == 0:
                delta = -1 if getattr(event, 'num', None) == 4 else 1
            row3_canvas.xview_scroll(delta, 'units')

        def _bind_row3_wheel(_):
            row3_canvas.bind_all('<Shift-MouseWheel>', _row3_mousewheel)

        def _unbind_row3_wheel(_):
            row3_canvas.unbind_all('<Shift-MouseWheel>')

        row3_canvas.bind('<Enter>', _bind_row3_wheel)
        row3_canvas.bind('<Leave>', _unbind_row3_wheel)

        # NOTE: "Billing Report" button removed on request - the billing()
        # method itself is left in place (unused) in case it's needed again
        # later, it's just no longer reachable from the UI.
        # NOTE: "All Material" report button removed on request - the
        # material() method itself is left in place (unused) in case it's
        # needed again later, it's just no longer reachable from the UI.
        for text, cmd in [('GST Report', self.gst),
                           ('Customer-Month Report', self.customer_month),
                           ('All Products', self.all_products),
                           ('Customer Report', self.customer_report), ('SRV / Challan Report', self.srv_report)]:
            ttk.Button(row3, text=text, command=cmd).pack(side='left', padx=4, pady=4)
        # NOTE: Print A4 / WhatsApp / Email buttons intentionally removed.

        body=ttk.Frame(self);body.pack(fill='both',expand=True,padx=8,pady=8)
        self.tree_columns=[]
        # Report table wrapped with its own vertical + horizontal scrollbars
        # so it can always be scrolled, no matter how many rows/columns a
        # report produces.
        table_frame=ttk.Frame(body)
        table_frame.pack(fill='both',expand=True,side='top')
        self.tree=ttk.Treeview(table_frame,show='headings')
        tree_yscroll=ttk.Scrollbar(table_frame,orient='vertical',command=self.tree.yview)
        tree_xscroll=ttk.Scrollbar(table_frame,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_yscroll.set,xscrollcommand=tree_xscroll.set)
        tree_yscroll.pack(side='right',fill='y')
        tree_xscroll.pack(side='bottom',fill='x')
        self.tree.pack(fill='both',expand=True,side='top')
        self.tree.bind('<Button-1>',self.on_tree_click)

        chart_box=ttk.LabelFrame(body,text='Chart')
        chart_box.pack(fill='x',pady=(8,0))
        self.chart_canvas=tk.Canvas(chart_box,height=220,bg='white',highlightthickness=0)
        self.chart_canvas.pack(fill='x',padx=6,pady=6)
        self.chart_canvas.bind('<Configure>',lambda e:self.draw_chart())

        self.current=[];self.all_rows=[];self.cols=[];self.report_title='Report';self.current_report=None

    # ---------- helpers ----------
    def _date_bounds(self):
        frm_raw=self.f.get().strip();to_raw=self.t.get().strip();frm=to=None
        try:
            if frm_raw:frm=datetime.strptime(frm_raw,'%d-%m-%Y').strftime('%Y%m%d')
            if to_raw:to=datetime.strptime(to_raw,'%d-%m-%Y').strftime('%Y%m%d')
        except ValueError:
            messagebox.showerror('Invalid Date','From/To must be in DD-MM-YYYY format (e.g. 01-09-2026)')
            return None
        return frm,to

    def _date_where(self,column,frm,to):
        expr=f"substr({column},7,4)||substr({column},4,2)||substr({column},1,2)"
        clauses=[];params=[]
        if frm:clauses.append(f'{expr} >= ?');params.append(frm)
        if to:clauses.append(f'{expr} <= ?');params.append(to)
        return (' WHERE '+' AND '.join(clauses)) if clauses else '',params

    def show(self,cols,rows):
        self.tree.delete(*self.tree.get_children())
        self.tree_columns=list(cols)+[k for k,_ in self.ACTION_COLUMNS]
        self.tree['columns']=self.tree_columns
        self.cols=cols;self.all_rows=rows;self.current=self.filtered_rows(rows)
        for c in cols:self.tree.heading(c,text=self.COLUMN_LABELS.get(c,c));self.tree.column(c,width=130)
        for k,l in self.ACTION_COLUMNS:self.tree.heading(k,text=l);self.tree.column(k,width=100,anchor='center',stretch=False)
        for idx,r in enumerate(self.current):
            self.tree.insert('','end',iid=str(idx),values=[r.get(c,'') for c in cols]+['\u2B07 Download'])
        self.draw_chart()
        # Tell the user WHY the table is empty instead of just showing a
        # blank table with no explanation - the #1 cause of "report me kuch
        # nahi ata" complaints.
        if not self.current:
            if self.all_rows and self.search.get().strip():
                messagebox.showinfo('No Match','No rows match your search text. Clear the Search box to see all records.')
            elif self.report_title in ('Billing Report','GST Report','Customer Month Report','All Material Report','SRV / Challan Report'):
                if self.report_title=='SRV / Challan Report':
                    body=('SRV / Challan Report: no matching records.\n\n'
                          'This report reads from Delivery Challan (SRV) entries only.\n'
                          'Save at least one Challan first, and if you typed a From/To\n'
                          'date, make sure it is DD-MM-YYYY and covers your challan date.')
                elif self.report_title=='Customer Month Report':
                    body=(f'{self.report_title}: no matching records.\n\n'
                          'This report is built from SAVED INVOICES (Tax Invoice / Bill tab) only.\n'
                          'If you have only saved Quotations/Challans and no Invoice yet,\n'
                          'save/generate an Invoice first, or check your From/To date.')
                else:
                    body=(f'{self.report_title}: no matching records.\n\n'
                          'This report combines saved Invoices AND SRV/Challans (Delivery\n'
                          'Challans not yet converted to an Invoice). Save at least one of\n'
                          'either first, and if you typed a From/To date, make sure it is\n'
                          'DD-MM-YYYY and actually covers that record\'s date.')
                messagebox.showinfo('No Records Found', body)

    def filtered_rows(self,rows):
        term=self.search.get().strip().lower()
        if not term:return rows
        return [r for r in rows if term in ' '.join(str(v or '').lower() for v in r.values())]

    def apply_search(self):
        if not self.cols:return
        self.show(self.cols,self.all_rows)

    # ---------- row actions (Download column) ----------
    def on_tree_click(self,event):
        region=self.tree.identify('region',event.x,event.y)
        if region!='cell':return
        col=self.tree.identify_column(event.x);row_id=self.tree.identify_row(event.y)
        if not row_id:return
        col_index=int(col.replace('#',''))-1
        if col_index<0 or col_index>=len(self.tree_columns):return
        if self.tree_columns[col_index]=='dl':self.download_row(row_id)

    def download_row(self,row_id):
        idx=int(row_id)
        if idx>=len(self.current):return
        row=self.current[idx]
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF','*.pdf')],
                                           initialfile=f'{self.report_title.replace(" ","_")}_row_{idx+1}.pdf')
        if not path:return
        make_report_pdf(self.report_title,list(self.cols),[row],path)
        messagebox.showinfo('Downloaded',path)

    # ---------- chart ----------
    def draw_chart(self):
        self.chart_canvas.delete('all')
        label_key,value_key,title=self.CHART_SPEC.get(self.current_report,(None,None,''))
        if not label_key or not value_key or not self.current:
            return
        totals={}
        for r in self.current:
            label=str(r.get(label_key) or '\u2014')
            try:val=float(r.get(value_key) or 0)
            except (TypeError,ValueError):val=0
            totals[label]=totals.get(label,0)+val
        items=sorted(totals.items(),key=lambda kv:kv[1],reverse=True)[:12]
        if not items:return
        self.update_idletasks()
        W=max(self.chart_canvas.winfo_width(),400);H=220
        pad_left,pad_bottom,pad_top,pad_right=10,50,26,10
        max_val=max(v for _,v in items) or 1
        avg_val=sum(v for _,v in items)/len(items)
        bar_area_w=W-pad_left-pad_right
        bar_w=bar_area_w/len(items)
        self.chart_canvas.create_text(pad_left,10,anchor='nw',text=f'{title} (Top {len(items)})',font=('Segoe UI',9,'bold'))
        # Green = at/above the average of the values shown, Red = below
        # average, so the chart highlights the strong vs weak items at a
        # glance instead of every bar being the same flat colour.
        GREEN='#2E9E4F';RED='#D64545'
        for i,(label,val) in enumerate(items):
            x0=pad_left+i*bar_w+4;x1=x0+bar_w-8
            bar_h=(H-pad_top-pad_bottom)*(val/max_val)
            y1=H-pad_bottom;y0=y1-bar_h
            color=GREEN if val>=avg_val else RED
            self.chart_canvas.create_rectangle(x0,y0,x1,y1,fill=color,outline='')
            short=label if len(label)<=10 else label[:9]+'\u2026'
            self.chart_canvas.create_text((x0+x1)/2,y1+12,text=short,font=('Segoe UI',7),anchor='n')
            self.chart_canvas.create_text((x0+x1)/2,y0-8,text=f'{val:,.0f}',font=('Segoe UI',7),anchor='s')

    # ---------- reports ----------
    def _challan_date_where(self,frm,to,extra_clause='ch.id NOT IN (SELECT challan_id FROM invoice_challans)'):
        # Same DD-MM-YYYY date filter as _date_where, but for the challans
        # (SRV) table, plus always excluding challans already converted to
        # an Invoice (so combined reports never double-count the same
        # business once as SRV and once as Invoice).
        expr="substr(ch.date,7,4)||substr(ch.date,4,2)||substr(ch.date,1,2)"
        clauses=[extra_clause] if extra_clause else []
        params=[]
        if frm:clauses.append(f'{expr} >= ?');params.append(frm)
        if to:clauses.append(f'{expr} <= ?');params.append(to)
        return (' WHERE '+' AND '.join(clauses)) if clauses else '',params

    def billing(self):
        # Combines saved Invoices with SRV/Challans that have NOT yet been
        # converted to an Invoice, so a business that only fills Challans
        # (SRV) still sees its numbers here instead of an empty report.
        bounds=self._date_bounds()
        if bounds is None:return
        frm,to=bounds
        where_sql_i,params_i=self._date_where('i.date',frm,to)
        where_sql_ch,params_ch=self._challan_date_where(frm,to)
        sql=(f"SELECT 'Invoice' doc_type,i.number,i.date,c.name customer,i.subtotal,i.cgst,i.sgst,i.freight,i.total,i.payment_mode,i.received,i.balance "
             f"FROM invoices i JOIN customers c ON c.id=i.customer_id{where_sql_i} "
             f"UNION ALL "
             f"SELECT 'SRV/Challan' doc_type,ch.number,ch.date,c2.name customer,ch.subtotal,ch.cgst,ch.sgst,ch.freight,ch.total,'' payment_mode,0 received,0 balance "
             f"FROM challans ch JOIN customers c2 ON c2.id=ch.customer_id{where_sql_ch} "
             f"ORDER BY date DESC")
        with conn() as c:rows=[dict(r) for r in c.execute(sql,params_i+params_ch)]
        self.report_title='Billing Report';self.current_report='billing'
        self.show(['doc_type','number','date','customer','subtotal','cgst','sgst','freight','total','payment_mode','received','balance'],rows)

    def gst(self):
        # GST Report:
        # Date, Bill No., Customer Name, Product, GSTIN,
        # Quantity, Loading, Rate, Total + Download.
        #
        # GST Report is based on TAX INVOICES only.
        # SRV/Delivery Challans are shown separately in srv_report().
        bounds=self._date_bounds()
        if bounds is None:return
        frm,to=bounds
        where_sql,params=self._date_where('i.date',frm,to)

        sql=(f"SELECT i.date AS date,"
             f"i.number AS bill_no,"
             f"c.name AS customer_name,"
             f"ii.item_name AS product,"
             f"COALESCE(c.gstin,'') AS gstin,"
             f"COALESCE(ii.qty,0) AS qty,"
             f"COALESCE(ii.loading,0) AS loading,"
             f"COALESCE(ii.price,0) AS rate,"
             f"COALESCE(ii.amount,0) AS total "
             f"FROM invoice_items ii "
             f"JOIN invoices i ON i.id=ii.invoice_id "
             f"JOIN customers c ON c.id=i.customer_id"
             f"{where_sql} "
             f"ORDER BY i.id DESC, ii.id ASC")

        with conn() as c:
            rows=[dict(r) for r in c.execute(sql,params)]

        self.report_title='GST Report'
        self.current_report='gst'
        self.show(
            ['date','bill_no','customer_name','product','gstin',
             'qty','loading','rate','total'],
            rows
        )

    def customer_month(self):
        bounds=self._date_bounds()
        if bounds is None:return
        frm,to=bounds
        where_sql,params=self._date_where('i.date',frm,to)
        sql=f"SELECT c.name customer,substr(i.date,4,7) month,COUNT(*) bills,SUM(i.total) total FROM invoices i JOIN customers c ON c.id=i.customer_id{where_sql} GROUP BY c.name,substr(i.date,4,7)"
        with conn() as c:rows=[dict(r) for r in c.execute(sql,params)]
        self.report_title='Customer Month Report';self.current_report='customer_month'
        self.show(['customer','month','bills','total'],rows)

    def material(self):
        # Combines Invoice items with items from SRV/Challans that have
        # NOT yet been converted to an Invoice.
        bounds=self._date_bounds()
        if bounds is None:return
        frm,to=bounds
        where_sql_i,params_i=self._date_where('i.date',frm,to)
        where_sql_ch,params_ch=self._challan_date_where(frm,to)
        sql=(f"SELECT 'Invoice' doc_type,i.number invoice_no,i.date,c.name customer,ii.item_name,ii.hsn_sac,ii.qty,ii.unit,ii.price,ii.amount,ii.weight_kg "
             f"FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id JOIN customers c ON c.id=i.customer_id{where_sql_i} "
             f"UNION ALL "
             f"SELECT 'SRV/Challan' doc_type,ch.number invoice_no,ch.date,c2.name customer,ci.item_name,ci.hsn_sac,ci.qty,ci.unit,ci.price,ci.amount,ci.weight_kg "
             f"FROM challan_items ci JOIN challans ch ON ch.id=ci.challan_id JOIN customers c2 ON c2.id=ch.customer_id{where_sql_ch} "
             f"ORDER BY date DESC")
        with conn() as c:rows=[dict(r) for r in c.execute(sql,params_i+params_ch)]
        self.report_title='All Material Report';self.current_report='material'
        self.show(['doc_type','invoice_no','date','customer','item_name','hsn_sac','qty','unit','price','amount','weight_kg'],rows)

    def all_products(self):
        # Shows the FULL products master, regardless of whether a product
        # has ever been used in an invoice (unlike "All Material" above).
        with conn() as c:rows=[dict(r) for r in c.execute('SELECT item_name,hsn_sac,unit,price,weight_kg FROM products ORDER BY item_name')]
        self.report_title='All Products Report';self.current_report='all_products'
        self.show(['item_name','hsn_sac','unit','price','weight_kg'],rows)

    def customer_report(self):
        # Pulls straight from the CUSTOMER MASTER (all fields including
        # District / Pin Code / Phone No), plus how much business each
        # customer has done across Quotations, Challans (SRV) and Invoices.
        with conn() as c:
            rows=[dict(r) for r in c.execute(
                "SELECT c.id,c.name customer,c.address,c.contact_no,c.email,c.state,"
                "COALESCE(c.district,'') district,COALESCE(c.pincode,'') pincode,"
                "c.gstin,c.contact_person,COALESCE(c.phone_no,'') phone_no,"
                "(SELECT COUNT(*) FROM quotations q WHERE q.customer_id=c.id) quotations,"
                "(SELECT COUNT(*) FROM challans ch WHERE ch.customer_id=c.id) srv_challans,"
                "(SELECT COUNT(*) FROM invoices i WHERE i.customer_id=c.id) invoices,"
                "COALESCE((SELECT SUM(i.total) FROM invoices i WHERE i.customer_id=c.id),0) grand_total "
                "FROM customers c ORDER BY c.name"
            )]
        self.report_title='Customer Report';self.current_report='customer_report'
        self.show(['customer','address','contact_no','email','state','district','pincode','gstin','contact_person','phone_no','quotations','srv_challans','invoices','grand_total'],rows)

    def srv_report(self):
        # SRV / Challan Report:
        # Date, Bill No., Customer Name, Godown, Item,
        # Qty, Loading, Rate, Total + Download.
        #
        # One row per challan item. GST-related columns are intentionally
        # not included in this report.
        bounds=self._date_bounds()
        if bounds is None:return
        frm,to=bounds
        where_sql,params=self._date_where('ch.date',frm,to)

        sql=(f"SELECT ch.date AS date,"
             f"ch.number AS bill_no,"
             f"c.name AS customer_name,"
             f"COALESCE(ch.godown,'') AS godown,"
             f"ci.item_name AS item,"
             f"COALESCE(ci.qty,0) AS qty,"
             f"COALESCE(ci.loading,0) AS loading,"
             f"COALESCE(ci.price,0) AS rate,"
             f"COALESCE(ci.amount,0) AS total "
             f"FROM challan_items ci "
             f"JOIN challans ch ON ch.id=ci.challan_id "
             f"JOIN customers c ON c.id=ch.customer_id"
             f"{where_sql} "
             f"ORDER BY ch.id DESC, ci.id ASC")

        with conn() as c:
            rows=[dict(r) for r in c.execute(sql,params)]

        self.report_title='SRV / Challan Report'
        self.current_report='srv_report'
        self.show(
            ['date','bill_no','customer_name','godown','item',
             'qty','loading','rate','total'],
            rows
        )

    def export(self):
        if not self.current:return messagebox.showerror('Report','Run a report first')
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')]);
        if not path:return
        with open(path,'w',newline='',encoding='utf-8-sig') as f:w=csv.DictWriter(f,fieldnames=self.cols);w.writeheader();w.writerows(self.current)
        messagebox.showinfo('Exported',path)
    def export_pdf(self,path=None,notify=True):
        if not self.current:return messagebox.showerror('Report','Run a report first')
        path=path or filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
        if not path:return
        make_report_pdf(self.report_title,self.cols,self.current,path)
        if notify:messagebox.showinfo('Exported',path)
        return path
    def email_current(self):
        path=os.path.abspath(os.path.join('exports','report_send.pdf'))
        if not self.export_pdf(path,False):return
        to=simpledialog.askstring('Email','Enter email address')
        if not to:return
        try:
            msg=send_email_or_compose(to,self.report_title,'Please find the report PDF attached/saved.',path);messagebox.showinfo('Email',msg)
        except Exception as e:messagebox.showerror('Email not sent',str(e))


if __name__ == "__main__":
    if not show_login():
        raise SystemExit

    lm = LicenseManager()

    # Already activated
    if lm.check_license():

        app = App()
        app.mainloop()

    else:

        # Show activation window
        ActivationGUI()

        # Check again after activation
        lm = LicenseManager()

        if lm.check_license():

            app = App()
            app.mainloop()
