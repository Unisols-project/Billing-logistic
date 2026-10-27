import json, os, sys

APP_NAME = 'JAY BHAVANI TRANSPORT Billing'


def _writable_base_dir():
    """
    Folder for things that must be READ/WRITE and PERSIST across runs
    (settings.json, and database.py's 'data' folder): the real .exe's
    own folder, not the temp bundle.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resource_base_dir():
    """
    Folder for READ-ONLY bundled resources (e.g. assets/payment_qr.png)
    that PyInstaller packs INSIDE the exe. At runtime these are extracted
    to sys._MEIPASS (a temp folder) - NOT next to the exe. Using the wrong
    base here means bundled images/icons won't be found after packaging.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _writable_base_dir()
RESOURCE_DIR = _resource_base_dir()
SETTINGS_PATH = os.path.join(BASE_DIR, 'data', 'settings.json')

# ---------------------------------------------------------------------------
# Company (letterhead) details — DEFAULTS.
#
# These values are printed on every Invoice and Challan. They are used the
# first time the app runs (before data/settings.json exists) and as a
# fallback for any field that is missing from settings.json. Once the user
# saves changes from the Settings screen, those changes are written to
# data/settings.json and are loaded from there on every future start -
# i.e. Settings > Save Settings now PERMANENTLY changes these values.
# ---------------------------------------------------------------------------
COMPANY = {
    'name': 'JAY BHAVANI TRANSPORT',
    'scanner_path': os.path.join(RESOURCE_DIR, 'assets', 'payment_qr.png'),
    'address': 'Sairaj Colony, Near Jashani Treader, Tapkir Nagar, Kalewadi, Pimpri Pune-17',
    'phone': '9657619660',
    'email': '',
    'gstin': '27AHNPT5635N1ZF',
    'pan': '',
    'state': '27-Maharashtra',
    'bank': 'BANK Name: BANK OF BARODA, KALEWADI\nA/C NO.: 46180200000559\nIFSC Code: BARB0KALEWA',
}
DEFAULT_GST_RATE = 5.0  # matches the 2.5% CGST + 2.5% SGST reference bill
EMAIL = {'smtp_host':'smtp.gmail.com','smtp_port':587,'username':'','password':'','use_tls':True}


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        return
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # All company fields saved by the Settings screen are loaded here,
        # so changes made in Settings > Save Settings persist across restarts.
        COMPANY.update(data.get('company', {}))
        EMAIL.update(data.get('email', {}))
    except Exception:
        pass


def save_settings():
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    # Persist every company field (name, address, phone, email, gstin, pan,
    # state, bank, scanner_path) so Settings > Save Settings is permanent.
    data = {'company': COMPANY, 'email': EMAIL}
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

load_settings()