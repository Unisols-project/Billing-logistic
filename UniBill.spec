# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += [('assets', 'assets')]  

# =========================================================
# PACKAGES TO COLLECT
# =========================================================

PACKAGES = [
    "cryptography",
    "Crypto",
    "cffi",
    "reportlab",
    "PIL",
    "numpy",
    "psutil",
    "playwright",
]

# =========================================================
# HIDDEN IMPORTS
# =========================================================

hiddenimports = []


for package in PACKAGES:
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass


# =========================================================
# DATA FILES + BINARIES
# =========================================================

datas = []
binaries = []


for package in PACKAGES:
    try:
        d, b, h = collect_all(package)

        datas += d
        binaries += b
        hiddenimports += h

    except Exception:
        pass


# =========================================================
# YOUR PROJECT MODULES
# =========================================================

hiddenimports += [
    "client_license",
    "config",
    "database",
    "license",
    "login",
]


# Remove duplicates
hiddenimports = list(dict.fromkeys(hiddenimports))


# =========================================================
# ANALYSIS
# =========================================================

a = Analysis(
    ["run.py"],

    pathex=[],

    binaries=binaries,

    datas=datas,

    hiddenimports=hiddenimports,

    hookspath=[],

    hooksconfig={},

    runtime_hooks=[],

    excludes=[],

    noarchive=False,
)


# =========================================================
# PYZ
# =========================================================

pyz = PYZ(
    a.pure
)


# =========================================================
# EXE
# =========================================================

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],

    name="UniBill",

    debug=False,

    bootloader_ignore_signals=False,

    strip=False,

    upx=True,

    console=False,
    icon='assets/logo.ico'
)