"""
license.py
-----------
7-day trial + unique per-machine license key activation, for the
Inventory Management System (Tkinter desktop app).

Used from main.py as:

    from license import init_trial, require_valid_license_tkinter
    ...
    init_trial()
    require_valid_license_tkinter(self)   # self = the Tk root window

HOW IT WORKS
============
1. First run  -> trial starts, activation date stored in ".license.json"
   (a small separate file next to license.py — never touches your
   database.db / data files, so user data is always safe).
2. Within 7 days -> app opens normally.
3. After 7 days -> a modal "Activate License" window pops up showing the
   user's unique Machine ID, before any other window/page is built.
     - If the user closes that window without a valid key -> app exits.
     - If the user enters the correct key for their Machine ID -> app
       unlocks permanently and continues loading normally.
4. To generate a key for a user: they send you their Machine ID (shown
   on the Activate window), and you run (on your own computer only):

        python keygen.py <machine_id>

   keygen.py must NEVER be included in the .exe you distribute.
"""

import os
import sys
import json
import uuid
import hmac
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

# ---- Configuration ------------------------------------------------------
TRIAL_DAYS = 7
LICENSE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".license.json")
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# CHANGE THIS to your own secret before building the .exe.
# Must be IDENTICAL in license.py (shipped) and keygen.py (kept private).
SECRET = "change-this-to-your-own-secret-before-shipping"
# -------------------------------------------------------------------------


def get_machine_id() -> str:
    """A stable per-installation ID, derived from the network MAC address."""
    raw = str(uuid.getnode())
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


def generate_key(machine_id: str) -> str:
    """Deterministically derive the license key for a given Machine ID."""
    digest = hmac.new(SECRET.encode(), machine_id.encode(), hashlib.sha256).hexdigest().upper()
    chunk = digest[:16]
    return "-".join(chunk[i:i + 4] for i in range(0, 16, 4))  # XXXX-XXXX-XXXX-XXXX


def _read_license():
    if not os.path.exists(LICENSE_FILE):
        return None
    try:
        with open(LICENSE_FILE, "r") as f:
            data = json.load(f)
        data["activated_on"] = datetime.strptime(data["activated_on"], DATE_FORMAT)
        return data
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _write_license(data: dict):
    to_save = dict(data)
    to_save["activated_on"] = data["activated_on"].strftime(DATE_FORMAT)
    with open(LICENSE_FILE, "w") as f:
        json.dump(to_save, f)


def init_trial():
    """
    Ensures the trial has been started (creates .license.json on first
    run). Safe to call every time the app starts — does nothing if the
    file already exists.
    """
    if _read_license() is None:
        _write_license({"activated_on": datetime.now(), "licensed": False})


def get_status() -> dict:
    """
    {"state": "trial", "days_left": N, "hours_left": N}
    {"state": "expired", "machine_id": "...."}
    {"state": "licensed"}
    """
    data = _read_license()

    if data is None:
        init_trial()
        return {"state": "trial", "days_left": TRIAL_DAYS, "hours_left": 0}

    if data.get("licensed"):
        return {"state": "licensed"}

    activated_on = data["activated_on"]
    expires_on = activated_on + timedelta(days=TRIAL_DAYS)
    now = datetime.now()

    if now > expires_on:
        return {"state": "expired", "machine_id": get_machine_id()}

    remaining = expires_on - now
    return {"state": "trial", "days_left": remaining.days, "hours_left": remaining.seconds // 3600}


def activate(key: str) -> bool:
    """Validates a key against this machine's ID. If valid, unlocks permanently."""
    key = key.strip().upper()
    expected = generate_key(get_machine_id())

    if not hmac.compare_digest(key, expected):
        return False

    data = _read_license() or {"activated_on": datetime.now()}
    data["licensed"] = True
    _write_license(data)
    return True


# ---------------------------------------------------------------------
# Tkinter activation dialog
# ---------------------------------------------------------------------

def require_valid_license_tkinter(root: tk.Tk):
    # NOTE: If you're showing license status directly on the Home page
    # instead, you don't need to call this function from main.py anymore.
    # Use get_status() / activate() inside pages/home.py instead. This
    # function is kept here in case you ever want the popup version back.
    """
    Call this right after init_trial(), before building any other UI.

    - If trial is still active or already licensed -> returns immediately,
      app continues loading as normal.
    - If expired -> shows a modal Activate window. Blocks (via
      wait_window) until the user either activates successfully or
      closes the window. Closing without activating exits the app —
      no further code in main.py's __init__ will run.
    """
    status = get_status()

    if status["state"] in ("trial", "licensed"):
        return  # nothing to do, let the app continue loading

    # state == "expired"
    machine_id = status["machine_id"]

    dialog = tk.Toplevel(root)
    dialog.title("Activate License")
    dialog.geometry("420x300")
    dialog.resizable(False, False)
    dialog.configure(bg="#FFFFFF")

    # Center on screen
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() // 2) - 210
    y = (dialog.winfo_screenheight() // 2) - 150
    dialog.geometry(f"+{x}+{y}")

    result = {"activated": False}

    def on_close():
        # User closed the window without activating -> exit the app.
        dialog.destroy()
        root.destroy()
        sys.exit(0)

    dialog.protocol("WM_DELETE_WINDOW", on_close)

    tk.Label(dialog, text="Trial Expired", font=("Segoe UI", 14, "bold"),
             bg="#FFFFFF", fg="#EF5350").pack(pady=(20, 4))

    tk.Label(dialog, text="Your 7-day trial has ended. Your data is safe —\n"
                          "you just need a license key to continue.",
             font=("Segoe UI", 9), bg="#FFFFFF", fg="#444444",
             justify="center").pack(pady=(0, 12))

    tk.Label(dialog, text="Your Machine ID (send this to the developer):",
             font=("Segoe UI", 9, "bold"), bg="#FFFFFF").pack()

    id_box = tk.Entry(dialog, font=("Consolas", 11), justify="center")
    id_box.insert(0, machine_id)
    id_box.config(state="readonly", readonlybackground="#F0F2F5")
    id_box.pack(pady=(4, 16), padx=30, fill="x")

    tk.Label(dialog, text="Enter License Key:",
             font=("Segoe UI", 9, "bold"), bg="#FFFFFF").pack()

    key_entry = tk.Entry(dialog, font=("Consolas", 11), justify="center")
    key_entry.pack(pady=(4, 8), padx=30, fill="x")
    key_entry.focus_set()

    error_label = tk.Label(dialog, text="", font=("Segoe UI", 9),
                            bg="#FFFFFF", fg="#EF5350")
    error_label.pack()

    def try_activate():
        key = key_entry.get()
        if activate(key):
            result["activated"] = True
            dialog.destroy()
        else:
            error_label.config(text="Invalid key for this machine. Please check and try again.")

    tk.Button(dialog, text="Activate", font=("Segoe UI", 10, "bold"),
              bg="#1A5276", fg="white", bd=0, padx=16, pady=8,
              cursor="hand2", command=try_activate).pack(pady=10)

    dialog.grab_set()      # modal: block interaction with root until closed
    root.wait_window(dialog)  # blocks here until dialog closes

    if not result["activated"]:
        # Dialog was closed via the (already-handled) on_close, so this
        # line normally won't be reached — kept as a safety net.
        root.destroy()
        sys.exit(0)